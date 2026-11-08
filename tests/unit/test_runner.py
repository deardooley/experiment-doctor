import hashlib
import io
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts import JobSpec
from services.runner.api import create_app
from services.runner.runtime import RuntimeFailure, Settings, parse_artifacts
from services.runner.store import Conflict, Store
from services.worker.supervisor import Supervisor

IMAGE = "python@sha256:" + "a" * 64
CODE = b"# never executed on host"
HASH = "sha256:" + hashlib.sha256(CODE).hexdigest()


def spec(key=None, **changes):
    return JobSpec.model_validate(dict(
        experiment_id=str(uuid4()), attempt_id=str(uuid4()),
        image_digest="sha256:" + "a" * 64, bundle_hash=HASH,
        parameters={}, idempotency_key=key or str(uuid4()), **changes))


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, image=IMAGE, bundles={HASH: CODE}, disk_reserve=0)


class FakeRuntime:
    """Only fixed bytes; no source execution or Docker invocation in unit tests."""
    def __init__(self, blocking=False):
        self.blocking = blocking
        self.started = threading.Event()
        self.removed = []
        self.cleaned = 0

    def preflight(self):
        pass

    def cleanup_all(self):
        self.cleaned += 1

    def name(self, job_id):
        return job_id

    def remove(self, name):
        self.removed.append(name)

    def execute(self, job_id, spec, poll):
        self.started.set()
        if self.blocking:
            while True:
                poll()
                time.sleep(0.01)
        return "SUCCEEDED", "SUCCESS", 0, {"trajectory.csv": b"t,x\n0,1\n5,0.0067\n"}


def wait_job(client, job_id):
    for _ in range(100):
        result = client.get(f"/execution/v1/jobs/{job_id}").json()
        if result["status"] not in ("QUEUED", "RUNNING"):
            return result
        time.sleep(0.02)
    raise AssertionError("job did not terminate")


def test_private_api_idempotency_artifacts_and_events(settings):
    runtime = FakeRuntime()
    with TestClient(create_app(settings, runtime)) as client:
        payload = spec().model_dump(mode="json")
        first = client.post("/execution/v1/jobs", json=payload)
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        assert client.post("/execution/v1/jobs", json=payload).json()["job_id"] == job_id
        payload["parameters"]["dt"] = 0.02
        assert client.post("/execution/v1/jobs", json=payload).status_code == 409
        result = wait_job(client, job_id)
        assert (result["status"], result["cleanup"]) == ("SUCCEEDED", "removed")
        assert result["artifact_manifest_hash"]
        items = client.get(f"/execution/v1/jobs/{job_id}/artifacts").json()
        response = client.get(f'/execution/v1/artifacts/{items[0]["id"]}')
        assert hashlib.sha256(response.content).hexdigest() == items[0]["sha256"]
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert [e["kind"] for e in client.get(
            f"/execution/v1/jobs/{job_id}/events").json()] == ["QUEUED", "RUNNING", "SUCCEEDED"]
        assert client.post(f"/execution/v1/jobs/{job_id}/cancel").json()["status"] == "SUCCEEDED"
        assert client.get("/health/ready").status_code == 200


def test_cancel_running(settings):
    runtime = FakeRuntime(blocking=True)
    with TestClient(create_app(settings, runtime)) as client:
        job_id = client.post("/execution/v1/jobs", json=spec().model_dump(mode="json")).json()["job_id"]
        assert runtime.started.wait(2)
        client.post(f"/execution/v1/jobs/{job_id}/cancel")
        assert wait_job(client, job_id)["status"] == "CANCELLED"
        assert job_id in runtime.removed


def test_deadline_and_restart_preserves_queued_work(settings):
    settings = replace(settings, deadline=0.1)
    store = Store(settings.root / "db")
    runtime = FakeRuntime(blocking=True)
    first = store.submit(spec())
    queued = store.submit(spec())
    supervisor = Supervisor(store, runtime, settings)
    supervisor.reconcile()
    supervisor.tick()
    assert store.get(first)["status"] == "TIMED_OUT"
    claimed = store.claim("dead-process")
    assert claimed["id"] == queued
    restarted = Supervisor(Store(store.path), runtime, settings)
    assert restarted.reconcile() == 1
    assert store.get(queued)["status"] == "LOST"
    assert store.get(queued)["cleanup"] == "removed"
    assert store.claim("new-process") is None


def test_atomic_claim_and_submit(settings):
    store = Store(settings.root / "db")
    payload = spec()
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(lambda _: store.submit(payload), range(8)))
    assert len(set(ids)) == 1
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda n: store.claim(str(n)), range(4)))
    assert sum(c is not None for c in claims) == 1
    with pytest.raises(Conflict):
        store.submit(payload.model_copy(update={"attempt_id": uuid4()}))


def test_queued_cancel_and_terminal_immutability(settings):
    store = Store(settings.root / "db")
    job_id = store.submit(spec())
    store.cancel(job_id)
    before = store.get(job_id)
    store.cancel(job_id)
    assert store.get(job_id) == before
    assert store.claim("worker") is None


@pytest.mark.parametrize("kind,name", [(tarfile.SYMTYPE, "trajectory.csv"),
                                       (tarfile.LNKTYPE, "trajectory.csv"),
                                       (tarfile.REGTYPE, "../trajectory.csv"),
                                       (tarfile.REGTYPE, "/trajectory.csv"),
                                       (tarfile.REGTYPE, "evil.svg")])
def test_archive_denies_unsafe_entries(kind, name):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        archive.addfile(member)
    with pytest.raises(RuntimeFailure):
        parse_artifacts(raw.getvalue())


def test_allowlist_and_body_limit(settings):
    with TestClient(create_app(settings, FakeRuntime())) as client:
        payload = spec().model_dump(mode="json")
        payload["bundle_hash"] = "sha256:" + "b" * 64
        assert client.post("/execution/v1/jobs", json=payload).status_code == 403
        payload["command"] = "sh"
        assert client.post("/execution/v1/jobs", json=payload).status_code == 422
        assert client.post("/execution/v1/jobs", content=b" " * 65537).status_code == 413
        assert client.get(f"/execution/v1/jobs/{uuid4()}").status_code == 404


def test_cleanup_failure_stops_claims(settings):
    class BrokenCleanup(FakeRuntime):
        def remove(self, name):
            raise RuntimeError("controlled failure")

    store = Store(settings.root / "db")
    supervisor = Supervisor(store, BrokenCleanup(), settings)
    supervisor.reconcile()
    job_id = store.submit(spec())
    supervisor.tick()
    assert not supervisor.ready
    assert store.get(job_id)["cleanup"] == "failed"
    assert store.get(job_id)["status"] == "FAILED"


def test_janitor_retains_active_and_removes_expired(settings):
    store = Store(settings.root / "db")
    supervisor = Supervisor(store, FakeRuntime(), settings)
    supervisor.reconcile()
    job_id = store.submit(spec())
    supervisor.tick()
    artifacts = store.artifacts(job_id)
    assert artifacts
    supervisor.janitor()
    assert store.artifacts(job_id)
    with store.connect() as db:
        db.execute("UPDATE jobs SET ended=? WHERE id=?", (time.time() - 90000, job_id))
    supervisor.janitor()
    assert store.artifacts(job_id) == []
    assert not (supervisor.artifact_dir / artifacts[0]["id"]).exists()
