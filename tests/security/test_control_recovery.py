import asyncio
from uuid import uuid4

from apps.api.store import ControlStore
from packages.agent.inference import VerificationOnly
from packages.contracts import JobResult
from services.control.worker import ControlWorker


def test_lost_submit_response_is_resolved_before_queue_resumes(tmp_path):
    """A kill between runner acceptance and job-ID persistence cannot hide a run."""
    store = ControlStore(tmp_path)
    interrupted = store.enqueue("session-one", "network-probe", kind="containment")
    queued = store.enqueue("session-two", "decay-healthy")
    store.claim("dead-worker")
    store.event(interrupted, "PROBE_SUBMIT_INTENT", {"idempotency_key": "accepted-with-lost-response"})
    job_id = uuid4()

    class Client:
        cancelled = []

        async def by_key(self, key):
            assert key == "accepted-with-lost-response"
            return JobResult(job_id=job_id, status="RUNNING", cleanup="pending")

        async def status(self, query):
            return JobResult(job_id=query, status="CANCELLED" if self.cancelled else "RUNNING",
                             cleanup="removed" if self.cancelled else "pending")

        async def cancel(self, query):
            self.cancelled.append(query)

    client = Client()
    worker = ControlWorker(tmp_path, client, VerificationOnly())
    asyncio.run(worker.recover())
    assert client.cancelled == [job_id]
    recovered = store.get(interrupted)
    assert recovered["status"] == "INCOMPLETE"
    assert store.get(queued)["status"] == "QUEUED"
    assert store.claim("new-worker")["id"] == queued


def test_session_and_queue_state_survive_api_reopen(tmp_path):
    store = ControlStore(tmp_path)
    store.add_session("session", "csrf")
    experiment_id = store.enqueue("session", "decay-healthy")
    reopened = ControlStore(tmp_path)
    assert reopened.session("session")["csrf"] == "csrf"
    assert reopened.get(experiment_id, "session")["status"] == "QUEUED"


def test_cancellation_and_report_attachment_share_atomic_outcome(tmp_path):
    import json
    store = ControlStore(tmp_path)
    experiment_id = store.enqueue("session", "decay-healthy")
    store.claim("worker")
    store.cancel(experiment_id, "session")
    store.finish(experiment_id, "worker", {"outcome": "VERIFIED_HEALTHY"})
    assert store.get(experiment_id)["status"] == "CANCELLED"
    artifact = next(item for item in store.artifacts(experiment_id, "session") if item["name"] == "report.json")
    report = json.loads((store.blobs / artifact["id"]).read_text())
    assert report["outcome"] == "CANCELLED"


def test_retention_removes_only_terminal_private_snapshots(tmp_path):
    import time
    worker = ControlWorker(tmp_path, object(), VerificationOnly())
    expired = worker.store.enqueue("old", "decay-healthy")
    worker.store.claim(worker.owner)
    worker.store.finish(expired, worker.owner, {"outcome": "VERIFIED_HEALTHY"})
    with worker.store.connect() as db:
        db.execute("UPDATE experiments SET ended=? WHERE id=?", (time.time()-90000, expired))
    active = worker.store.enqueue("active", "decay-healthy")
    old_dir = worker.diagnoses / expired
    active_dir = worker.diagnoses / active
    old_dir.mkdir(parents=True)
    active_dir.mkdir()
    (old_dir / "source.py").write_text("old snapshot, never executed")
    (active_dir / "source.py").write_text("active snapshot, never executed")
    worker.cleanup()
    assert not old_dir.exists()
    assert active_dir.exists()
    assert '"evidence_expired": true' in worker.store.get(expired)["report"]


def test_shared_queue_file_is_0660_even_with_restrictive_umask(tmp_path):
    import os
    import stat
    old = os.umask(0o077)
    try:
        ControlStore(tmp_path)
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "api.sqlite3").stat().st_mode) == 0o660
