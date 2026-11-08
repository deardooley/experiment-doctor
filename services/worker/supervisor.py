"""Runner-side durable job supervisor; no model or cloud credentials required."""
import hashlib
import os
import shutil
import threading
import time
from uuid import uuid4

from packages.contracts import JobSpec
from services.runner.runtime import MAX_ARTIFACTS


class Cancelled(Exception):
    pass


class Supervisor:
    def __init__(self, store, runtime, settings):
        self.store, self.runtime, self.settings = store, runtime, settings
        runtime.store = store
        self.owner = str(uuid4())
        self.stop = threading.Event()
        self.ready = False
        self.last_janitor = 0.0
        self.artifact_dir = settings.root / "artifacts"
        self.artifact_dir.mkdir(mode=0o700, exist_ok=True)

    def reconcile(self):
        self.ready = False
        self.runtime.cleanup_all()
        recovered = self.store.recover()
        # Interrupted writes never become downloadable without a committed manifest.
        with self.store.connect() as db:
            retained = {row[0] for row in db.execute("SELECT id FROM artifacts")}
        for path in self.artifact_dir.iterdir():
            if path.is_file() and path.name not in retained:
                path.unlink()
        self.ready = True
        return recovered

    def tick(self):
        if shutil.disk_usage(self.settings.root).free < self.settings.disk_reserve:
            return False
        job = self.store.claim(self.owner)
        if not job:
            return False
        job_id = job["id"]
        spec = JobSpec.model_validate_json(job["spec"])
        status, reason, code, outputs = "FAILED", "RUNTIME_ERROR", None, {}
        cleanup, artifacts = "failed", []
        started = time.monotonic()

        def poll():
            if self.stop.is_set() or self.store.get(job_id)["cancel"]:
                raise Cancelled()
            if not self.store.heartbeat(job_id, self.owner):
                raise Cancelled()
            if time.monotonic() - started >= self.settings.deadline:
                raise TimeoutError()

        try:
            self.settings.authorize(spec)
            status, reason, code, outputs = self.runtime.execute(job_id, spec, poll)
        except Cancelled as exc:
            status, reason = "CANCELLED", "CANCELLED"
            outputs = self.failure_logs(exc)
        except TimeoutError as exc:
            status, reason = "TIMED_OUT", "TIMEOUT"
            outputs = self.failure_logs(exc)
        except Exception as exc:
            # No untrusted log or Docker error content is put into journal events.
            status, reason = "FAILED", "RUNTIME_ERROR"
            outputs = self.failure_logs(exc)
        finally:
            try:
                self.runtime.remove(self.runtime.name(job_id))
                cleanup = "removed"
            except Exception:
                self.ready = False
                status, reason = "FAILED", "RUNTIME_ERROR"
        try:
            if sum(len(data) for data in outputs.values()) > MAX_ARTIFACTS:
                raise ValueError("artifact budget exceeded")
            for name, data in sorted(outputs.items()):
                artifact_id = str(uuid4())
                path = self.artifact_dir / artifact_id
                with path.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                artifacts.append({"id": artifact_id, "name": name, "size": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
            self.store.finish(job_id, self.owner, status, reason, code, cleanup, artifacts)
        except Exception:
            self.ready = False
            raise
        return True

    @staticmethod
    def failure_logs(exc):
        return {"stdout.txt": getattr(exc, "stdout", b""),
                "stderr.txt": getattr(exc, "stderr", b"")}

    def janitor(self):
        # Called only between jobs by the singleton supervisor. No active output
        # can be deleted, and a stale claim never gets silently resubmitted.
        self.runtime.cleanup_all()
        self.store.recover()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT artifacts.id FROM artifacts JOIN jobs ON jobs.id=artifacts.job_id "
                "WHERE jobs.ended<? AND jobs.status NOT IN ('QUEUED','RUNNING')",
                (time.time() - 86400,)).fetchall()
            for row in rows:
                (self.artifact_dir / row["id"]).unlink(missing_ok=True)
                db.execute("DELETE FROM artifacts WHERE id=?", (row["id"],))
        self.last_janitor = time.monotonic()

    def run(self):
        while not self.stop.is_set() and self.ready:
            try:
                if not self.tick():
                    if time.monotonic() - self.last_janitor > 30:
                        self.janitor()
                    self.stop.wait(0.2)
            except Exception:
                self.ready = False
