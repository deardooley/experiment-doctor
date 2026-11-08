import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app import APISettings, create_app
from apps.api.store import LimitExceeded

ORIGIN = "https://doctor.test"


@pytest.fixture
def app(tmp_path):
    app = create_app(APISettings(root=tmp_path, origin=ORIGIN, session_key=b"unit-test-signing-key-" * 3))
    app.state.store.heartbeat("unit-worker")
    return app


def client_session(app):
    client = TestClient(app, base_url=ORIGIN)
    bootstrap = client.get("/api/v1/session")
    assert bootstrap.status_code == 200
    csrf = bootstrap.json()["csrf_token"]
    return client, {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def submit(client, headers):
    return client.post("/api/v1/experiments", headers=headers, json={"fixture_id": "decay-healthy"})


def complete(app, experiment_id, files=None):
    row = app.state.store.claim("unit-worker")
    assert row["id"] == experiment_id
    app.state.store.finish(experiment_id, "unit-worker", {"outcome": "VERIFIED_HEALTHY"}, files)


def test_signed_secure_cookie_and_csrf(app):
    with TestClient(app, base_url=ORIGIN) as anonymous:
        assert submit(anonymous, {}).status_code == 401
    client, headers = client_session(app)
    cookie = client.get("/api/v1/session").headers["set-cookie"].lower()
    assert all(part in cookie for part in ("httponly", "secure", "samesite=lax", "path=/"))
    assert submit(client, {}).status_code == 403
    assert submit(client, headers | {"Origin": "https://evil.test"}).status_code == 403
    assert submit(client, headers | {"X-CSRF-Token": "wrong"}).status_code == 403
    assert submit(client, headers).status_code == 202
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM events WHERE kind='CSRF_DENIED'").fetchone()[0] == 3


def test_forged_and_expired_cookies(app):
    client, headers = client_session(app)
    real = client.cookies["ed_session"]
    client.cookies.set("ed_session", real[:-1] + ("0" if real[-1] != "0" else "1"), domain="doctor.test", path="/")
    assert submit(client, headers).status_code == 401
    client.cookies.set("ed_session", real, domain="doctor.test", path="/")
    with app.state.store.connect() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert submit(client, headers).status_code == 401


def test_cross_session_every_resource_is_denied(app):
    first, headers = client_session(app)
    other, other_headers = client_session(app)
    experiment_id = submit(first, headers).json()["experiment_id"]
    for path in (f"/api/v1/experiments/{experiment_id}", f"/api/v1/experiments/{experiment_id}/events",
                 f"/api/v1/experiments/{experiment_id}/artifacts"):
        assert other.get(path).status_code == 404
    assert other.post(f"/api/v1/experiments/{experiment_id}/cancel", headers=other_headers).status_code == 404
    complete(app, experiment_id, {"trajectory.csv": b"t,x\n0,1\n5,0\n"})
    artifacts = first.get(f"/api/v1/experiments/{experiment_id}/artifacts").json()
    for item in artifacts:
        assert other.get(f'/api/v1/artifacts/{item["id"]}').status_code == 404
        assert first.get(f'/api/v1/artifacts/{item["id"]}').status_code == 200
    assert other.get(f"/api/v1/artifacts/{uuid4()}").status_code == 404


def test_active_markup_is_attachment_and_reports_are_json(app):
    client, headers = client_session(app)
    experiment_id = submit(client, headers).json()["experiment_id"]
    complete(app, experiment_id, {"attack.svg": b'<svg onload="alert(1)"></svg>'})
    item = next(a for a in client.get(f"/api/v1/experiments/{experiment_id}/artifacts").json() if a["name"] == "attack.svg")
    response = client.get(f'/api/v1/artifacts/{item["id"]}')
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    assert "no-store" in response.headers["cache-control"]
    assert client.get(f"/api/v1/experiments/{experiment_id}").headers["content-type"].startswith("application/json")


def test_public_surface_has_no_execution_upload_or_adversarial_fixture(app):
    client, headers = client_session(app)
    for path in ("/execution/v1/jobs", "/execution/v1/bundles", "/api/v1/operator/probes/network"):
        assert client.post(path, headers=headers, json={}).status_code == 404
    for payload in ({"fixture_id": "decay-false-success"}, {"fixture_id": "decay-healthy", "code": "pass"},
                    {"fixture_id": "../simulation.py"}, {"fixture_id": "decay-healthy", "task": "x"*1001}):
        assert client.post("/api/v1/experiments", headers=headers, json=payload).status_code == 422
    assert client.post("/api/v1/experiments", headers=headers, content=b"x"*4097).status_code == 413
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0


def test_operator_requires_separate_credential(tmp_path):
    settings = APISettings(root=tmp_path, origin=ORIGIN, session_key=b"s"*32,
                           operator_enabled=True, operator_token="o"*32)
    app = create_app(settings)
    app.state.store.heartbeat("unit-worker")
    client, headers = client_session(app)
    assert client.post("/api/v1/operator/probes/network", headers=headers).status_code == 403
    assert client.post("/api/v1/operator/probes/network", headers=headers | {"Authorization": "Bearer wrong"}).status_code == 403
    response = client.post("/api/v1/operator/probes/network", headers=headers | {"Authorization": "Bearer " + "o"*32})
    assert response.status_code == 202
    assert app.state.store.get(response.json()["experiment_id"])["kind"] == "containment"


def test_per_session_and_global_queue_caps_are_atomic(app):
    store = app.state.store
    with ThreadPoolExecutor(max_workers=4) as executor:
        def enqueue(_):
            try:
                return store.enqueue("same-session", "decay-healthy")
            except LimitExceeded:
                return None
        results = list(executor.map(enqueue, range(8)))
    assert sum(value is not None for value in results) == 1
    for i in range(9):
        store.enqueue(f"session-{i}", "decay-healthy")
    with pytest.raises(LimitExceeded):
        store.enqueue("another-session", "decay-healthy")


def test_rate_and_readiness_fail_closed(app):
    client, headers = client_session(app)
    app.state.store.heartbeat("unit-worker", ready=False)
    assert client.get("/health/ready").status_code == 503
    assert submit(client, headers).status_code == 503
    assert client.get("/health/live").status_code == 200
    for _ in range(9):
        assert client.get("/api/v1/session").status_code == 200
    assert client.get("/api/v1/session", headers={"X-Forwarded-For": "198.51.100.10"}).status_code == 429
    assert client.get("/health/live", headers={"Host": "evil.test"}).status_code == 400


def test_queued_cancellation_and_retention(app):
    client, headers = client_session(app)
    experiment_id = submit(client, headers).json()["experiment_id"]
    for _ in range(2):
        assert client.post(f"/api/v1/experiments/{experiment_id}/cancel", headers=headers).status_code == 200
    assert client.get(f"/api/v1/experiments/{experiment_id}").json()["status"] == "CANCELLED"
    assert app.state.store.claim("worker") is None
    second = submit(client, headers).json()["experiment_id"]
    complete(app, second, {"evidence.txt": b"bounded evidence"})
    ids = [a["id"] for a in app.state.store.artifacts(second, app.state.store.get(second)["session_id"])]
    with app.state.store.connect() as db:
        db.execute("UPDATE experiments SET ended=? WHERE id=?", (time.time()-90000, second))
    app.state.store.cleanup()
    assert all(not (app.state.store.blobs / value).exists() for value in ids)


def test_production_configuration_requires_strong_keys_and_https(tmp_path):
    with pytest.raises(ValueError):
        APISettings(root=tmp_path, origin=ORIGIN, session_key=b"short")
    with pytest.raises(ValueError):
        APISettings(root=tmp_path, origin="http://public.test", session_key=b"s"*32, allow_http_local=True)
    with pytest.raises(ValueError):
        APISettings(root=tmp_path, origin=ORIGIN, session_key=b"s"*32, operator_enabled=True)


def test_operator_cannot_select_a_target_or_upload_source(tmp_path):
    app = create_app(APISettings(root=tmp_path, origin=ORIGIN, session_key=b"s"*32,
                                operator_enabled=True, operator_token="o"*32))
    app.state.store.heartbeat("unit-worker")
    client, headers = client_session(app)
    response = client.post("/api/v1/operator/probes/network", headers=headers | {"Authorization": "Bearer " + "o"*32},
                           json={"target": "example.com", "source": "untrusted"})
    assert response.status_code == 422
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM experiments").fetchone()[0] == 0


def test_cursor_pagination_preserves_final_events(app):
    client, headers = client_session(app)
    experiment_id = submit(client, headers).json()["experiment_id"]
    for number in range(210):
        app.state.store.event(experiment_id, "MEASURED_EVENT", {"index": number})
    cursor, collected = 0, []
    while True:
        page = client.get(f"/api/v1/experiments/{experiment_id}/events", params={"after": cursor}).json()
        if not page:
            break
        assert len(page) <= 100
        collected.extend(page)
        cursor = page[-1]["cursor"]
    assert len(collected) == 211
    assert collected[-1]["data"]["index"] == 209
