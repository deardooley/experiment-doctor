"""Opt-in Linux/rootless tests. Candidate fixtures execute ONLY via DockerRuntime."""
import asyncio
import csv
import hashlib
import io
import json
import multiprocessing
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from packages.contracts import JobSpec
from packages.execution.local import LocalExecutionClient
from services.runner.runtime import DockerRuntime, Settings
from services.runner.store import Store
from services.worker.supervisor import Supervisor

pytestmark = pytest.mark.skipif(os.environ.get("ED_RUNTIME_TESTS") != "1",
                                reason="requires explicit Linux rootless runtime opt-in")
ROOT = Path(__file__).resolve().parents[2]
HEALTHY = (ROOT / "experiments/decay/simulation.py").read_bytes()
# Repository-owned adversarial fixtures; never executed by the test host.
SLEEP = b"import time\nprint('started', flush=True)\ntime.sleep(60)\n"
EXCEPTION = b"raise RuntimeError('controlled fixture exception')\n"
OOM = b"x = bytearray(700 * 1024 * 1024)\n"


def digest(code):
    return "sha256:" + hashlib.sha256(code).hexdigest()


def make_settings(root, deadline=30):
    return Settings(root=root, image=os.environ["SIMULATION_IMAGE"],
                    bundles={digest(code): code for code in (HEALTHY, SLEEP, EXCEPTION, OOM)},
                    scope="m1-" + hashlib.sha256(str(root).encode()).hexdigest()[:8],
                    deadline=deadline)


def spec(settings, code):
    return JobSpec(experiment_id=uuid4(), attempt_id=uuid4(),
                   image_digest=settings.image.split("@")[1], bundle_hash=digest(code),
                   parameters={}, idempotency_key=str(uuid4()))


@pytest.fixture(scope="module", autouse=True)
def enforce_runtime(tmp_path_factory):
    if os.environ.get("ED_RUNTIME_TESTS") == "1":
        settings = make_settings(tmp_path_factory.mktemp("preflight"))
        DockerRuntime(settings).preflight()


@pytest.mark.parametrize("code,expected,reason", [
    (HEALTHY, "SUCCEEDED", "SUCCESS"), (EXCEPTION, "FAILED", "RUNTIME_ERROR"),
    (SLEEP, "TIMED_OUT", "TIMEOUT"), (OOM, "FAILED", "OOM")],
    ids=["healthy", "exception", "timeout", "oom"])
def test_real_execution(tmp_path, code, expected, reason):
    settings = make_settings(tmp_path, deadline=2 if code == SLEEP else 30)
    store = Store(tmp_path / "runner.sqlite3")
    runtime = DockerRuntime(settings)
    supervisor = Supervisor(store, runtime, settings)
    supervisor.reconcile()
    request = spec(settings, code)
    job_id = store.submit(request)
    assert store.submit(request) == job_id
    assert supervisor.tick()
    result = store.get(job_id)
    assert (result["status"], result["reason"], result["cleanup"]) == (expected, reason, "removed")
    assert runtime.command("ps", "-aq", "--filter", f"name=^/{runtime.name(job_id)}$") == b""
    artifacts = store.artifacts(job_id)
    for item in artifacts:
        data = (supervisor.artifact_dir / item["id"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
    if code == HEALTHY:
        trajectory = next(a for a in artifacts if a["name"] == "trajectory.csv")
        data = (supervisor.artifact_dir / trajectory["id"]).read_text()
        rows = list(csv.DictReader(io.StringIO(data)))
        assert float(rows[0]["x"]) == 1
        assert float(rows[-1]["t"]) == 5
        assert len(rows) >= 501
    elif code == SLEEP:
        stdout = next(a for a in artifacts if a["name"] == "stdout.txt")
        assert b"started" in (supervisor.artifact_dir / stdout["id"]).read_bytes()


def test_real_cancel_and_next_job(tmp_path):
    settings = make_settings(tmp_path)
    store = Store(tmp_path / "runner.sqlite3")
    runtime = DockerRuntime(settings)
    supervisor = Supervisor(store, runtime, settings)
    supervisor.reconcile()
    job_id = store.submit(spec(settings, SLEEP))
    thread = threading.Thread(target=supervisor.tick)
    thread.start()
    for _ in range(100):
        if runtime.command("ps", "-q", "--filter", f"name=^/{runtime.name(job_id)}$").strip():
            break
        time.sleep(0.05)
    else:
        raise AssertionError("sandbox did not start")
    store.cancel(job_id)
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert (store.get(job_id)["status"], store.get(job_id)["cleanup"]) == ("CANCELLED", "removed")
    healthy = store.submit(spec(settings, HEALTHY))
    supervisor.tick()
    assert store.get(healthy)["status"] == "SUCCEEDED"


def crashed_worker(settings):
    store = Store(settings.root / "runner.sqlite3")
    Supervisor(store, DockerRuntime(settings), settings).tick()


def test_real_killed_worker_reconciliation(tmp_path):
    settings = make_settings(tmp_path)
    runtime = DockerRuntime(settings)
    store = Store(tmp_path / "runner.sqlite3")
    interrupted_request = spec(settings, SLEEP)
    interrupted = store.submit(interrupted_request)
    queued = store.submit(spec(settings, HEALTHY))
    process = multiprocessing.get_context("spawn").Process(target=crashed_worker, args=(settings,))
    process.start()
    try:
        for _ in range(150):
            if runtime.command("ps", "-q", "--filter", f"name=^/{runtime.name(interrupted)}$").strip():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("interrupted sandbox did not start")
        process.kill()
        process.join(5)
        assert process.exitcode != 0
        restarted = Supervisor(Store(store.path), runtime, settings)
        assert restarted.reconcile() == 1
        assert store.get(interrupted)["status"] == "LOST"
        assert store.submit(interrupted_request) == interrupted
        assert restarted.tick()
        assert store.get(queued)["status"] == "SUCCEEDED"
        assert not restarted.tick()
        assert runtime.command("ps", "-aq", "--filter",
                               f"label=org.experiment-doctor.runner={settings.scope}") == b""
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        runtime.cleanup_all()


def test_real_unix_socket_client(tmp_path):
    root = tmp_path / "api"
    socket = tmp_path / "runner.sock"
    process = subprocess.Popen([
        sys.executable, "-m", "services.runner", "--root", str(root), "--socket", str(socket),
        "--image", os.environ["SIMULATION_IMAGE"], "--scope", "m1-uds"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def workflow():
        client = LocalExecutionClient(socket)
        try:
            for _ in range(300):
                try:
                    response = await client.client.get("/health/ready")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if process.poll() is not None:
                    raise AssertionError("runner server exited")
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("runner not ready")
            settings = make_settings(root)
            request = spec(settings, HEALTHY)
            job_id = await client.submit(request)
            assert await client.submit(request) == job_id
            for _ in range(200):
                result = await client.status(job_id)
                if result.status not in ("QUEUED", "RUNNING"):
                    break
                await asyncio.sleep(0.1)
            assert result.status == "SUCCEEDED"
            ids = await client.artifacts(job_id)
            data = [await client.read_artifact(item) for item in ids]
            assert any(item.startswith(b"t,x") for item in data)
            assert (await client.cancel(job_id)).status == "SUCCEEDED"
            assert (await client.client.get("/health/ready")).status_code == 200
            assert socket.stat().st_mode & 0o007 == 0
            print(json.dumps({"uds_submit_status_artifacts_cleanup": "PASS"}))
        finally:
            await client.close()
    try:
        asyncio.run(workflow())
    finally:
        process.terminate()
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def serve_test_runner(settings, socket):
    from services.runner.__main__ import serve
    serve(settings, socket)


def test_real_runner_crash_and_queued_recovery(tmp_path):
    settings = make_settings(tmp_path / "runner")
    socket = tmp_path / "crash.sock"
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=serve_test_runner, args=(settings, socket))
    process.start()
    runtime = DockerRuntime(settings)

    async def ready(client):
        for _ in range(500):
            try:
                if (await client.client.get("/health/ready")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)
        raise AssertionError("restarted runner did not become ready")

    async def workflow():
        nonlocal process
        client = LocalExecutionClient(socket)
        try:
            await ready(client)
            request = spec(settings, SLEEP)
            running = await client.submit(request)
            queued = await client.submit(spec(settings, HEALTHY))
            for _ in range(100):
                if runtime.command("ps", "-q", "--filter",
                                   f"name=^/{runtime.name(running)}$").strip():
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("sandbox did not start")
            process.kill()
            process.join(5)
            process = context.Process(target=serve_test_runner, args=(settings, socket))
            process.start()
            await ready(client)
            assert (await client.status(running)).status == "LOST"
            assert await client.submit(request) == running
            for _ in range(100):
                result = await client.status(queued)
                if result.status not in ("QUEUED", "RUNNING"):
                    break
                await asyncio.sleep(0.1)
            assert result.status == "SUCCEEDED"
            store = Store(settings.root / "runner.sqlite3")
            assert [event["kind"] for event in store.events(str(running))].count("RUNNING") == 1
            assert (await client.status(running)).cleanup == "removed"
        finally:
            await client.close()
    try:
        asyncio.run(workflow())
    finally:
        process.terminate()
        process.join(45)
        if process.is_alive():
            process.kill()
            process.join(5)
        runtime.cleanup_all()
