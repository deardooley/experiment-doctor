"""Separate control worker. Owns model credentials; accesses execution only via UDS API."""
import asyncio
import fcntl
import hashlib
import json
import re
import sqlite3
import shutil
import time
from uuid import UUID, uuid4

from apps.api.app import PUBLIC_FIXTURES
from apps.api.store import ControlStore
from packages.agent.doctor import Doctor
from packages.security.demo import network_demo


class ControlWorker:
    def __init__(self, root, client, model):
        self.store = ControlStore(root)
        self.root, self.client, self.model = root, client, model
        self.owner = str(uuid4())
        self.stop = asyncio.Event()
        self.ready = False
        self.diagnoses = root / "diagnoses"
        self.last_cleanup = 0.0

    async def runtime_ready(self):
        response = await self.client.client.get("/health/ready")
        response.raise_for_status()
        config = await self.client.configuration()
        if not config.get("verifier_image"):
            raise ValueError("trusted verifier unavailable")
        if self.model.mode == "live" and (not self.model.key or not self.model.model
                or self.model.base != "https://api.vultrinference.com/v1"):
            raise ValueError("model configuration missing")

    async def settle(self, experiment_id):
        journal = self.diagnoses / "control.sqlite3"
        ids = []
        keys = []
        if journal.exists():
            with sqlite3.connect(journal) as db:
                ids.extend(row[0] for row in db.execute("SELECT id FROM jobs WHERE experiment_id=?",
                                                       (experiment_id,)))
                keys.extend(json.loads(row[0])["idempotency_key"] for row in db.execute(
                    "SELECT data FROM events WHERE experiment_id=? AND kind='SUBMIT'", (experiment_id,)))
        # Fixed probe submission is journaled in the public control event stream.
        with self.store.connect() as db:
            for row in db.execute("SELECT data FROM events WHERE experiment_id=? AND kind='PROBE_SUBMITTED'",
                                  (experiment_id,)):
                ids.append(json.loads(row[0])["job_id"])
            keys.extend(json.loads(row[0])["idempotency_key"] for row in db.execute(
                "SELECT data FROM events WHERE experiment_id=? AND kind='PROBE_SUBMIT_INTENT'", (experiment_id,)))
        for key in set(keys):
            result = await self.client.by_key(key)
            if result:
                ids.append(str(result.job_id))
        settled = []
        for job_id in set(ids):
            result = await self.client.status(UUID(job_id))
            if result.status in ("QUEUED", "RUNNING"):
                await self.client.cancel(UUID(job_id))
                async with asyncio.timeout(40):
                    while result.status in ("QUEUED", "RUNNING"):
                        await asyncio.sleep(.1)
                        result = await self.client.status(UUID(job_id))
            if result.cleanup != "removed":
                raise ValueError("runner cleanup unresolved")
            settled.append(result.model_dump(mode="json"))
        return settled

    async def recover(self):
        # The singleton worker lock ensures these claims cannot belong to a live peer.
        for row in self.store.interrupted():
            settled = await self.settle(row["id"])
            with self.store.connect() as db:
                db.execute("UPDATE experiments SET owner=? WHERE id=? AND status='RUNNING'",
                           (self.owner, row["id"]))
            self.store.finish(row["id"], self.owner, {"outcome": "INCOMPLETE", "kind": row["kind"],
                "experiment_id": row["id"], "interrupted_jobs": settled,
                "error": "Control worker restarted; interrupted work was cancelled, never retried"})

    def files(self, experiment_id, report):
        directory = self.diagnoses / experiment_id
        manifest = report.get("evidence_manifest", {})
        if report.get("kind") == "containment":
            manifest = report["following_healthy"].get("evidence_manifest", {})
        files = {}
        for name, digest in manifest.items():
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
                raise ValueError("unsafe evidence name")
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("unsafe evidence snapshot")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("evidence snapshot changed")
            files[name] = raw
        return files

    async def tick(self):
        row = self.store.claim(self.owner)
        if row is None:
            return False
        experiment_id = row["id"]
        def event(kind, data):
            self.store.event(experiment_id, kind, data)
        doctor = None
        if row["kind"] == "containment" and row["fixture"] == "network-probe":
            task = asyncio.create_task(network_demo(self.client, self.diagnoses, experiment_id, event))
        elif row["kind"] == "diagnosis" and row["fixture"] in PUBLIC_FIXTURES:
            doctor = Doctor(self.client, self.model, self.diagnoses, on_event=event)
            task = asyncio.create_task(doctor.run(row["fixture"], repair=self.model.mode != "verification-only",
                                                 experiment_id=experiment_id, task=row["task"]))
        else:
            self.store.finish(experiment_id, self.owner, {"outcome": "BLOCKED", "error": "Unapproved queue operation"})
            return True
        report = None
        try:
            async with asyncio.timeout(190):
                cancelled = False
                while not task.done():
                    self.store.heartbeat(self.owner)
                    if (self.store.get(experiment_id)["cancel"] or self.stop.is_set()) and not cancelled:
                        task.cancel()
                        cancelled = True
                    await asyncio.sleep(.1)
                report = await task
            await self.settle(experiment_id)
            report.pop("report_path", None)
            self.store.finish(experiment_id, self.owner, report, self.files(experiment_id, report))
            if report["outcome"] == "NOT_CONTAINED":
                self.ready = False
        except BaseException as exc:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            try:
                await self.settle(experiment_id)
            except Exception:
                self.ready = False
            self.store.finish(experiment_id, self.owner, {
                "outcome": "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "INCOMPLETE",
                "experiment_id": experiment_id, "error": "Interrupted; no scientific pass was inferred"})
        finally:
            if doctor:
                doctor.journal.db.close()
        return True

    def cleanup(self):
        self.store.cleanup()
        with self.store.connect() as db:
            expired = [row[0] for row in db.execute("SELECT id FROM experiments WHERE ended<? "
                       "AND status NOT IN ('QUEUED','RUNNING')", (time.time() - 86400,))]
        for experiment_id in expired:
            UUID(experiment_id)  # Never turn arbitrary database text into a deletion path.
            directory = self.diagnoses / experiment_id
            if directory.is_symlink():
                directory.unlink()
            elif directory.is_dir():
                shutil.rmtree(directory)
            journal = self.diagnoses / "control.sqlite3"
            if journal.exists():
                with sqlite3.connect(journal) as db:
                    db.execute("DELETE FROM verification_results WHERE attempt_id IN "
                               "(SELECT id FROM attempts WHERE experiment_id=?)", (experiment_id,))
                    db.execute("DELETE FROM artifacts WHERE job_id IN "
                               "(SELECT id FROM jobs WHERE experiment_id=?)", (experiment_id,))
                    for table in ("attempts", "jobs", "events"):
                        db.execute(f"DELETE FROM {table} WHERE experiment_id=?", (experiment_id,))
                    db.execute("DELETE FROM experiments WHERE id=?", (experiment_id,))
        self.last_cleanup = time.monotonic()

    async def run(self):
        self.root.mkdir(mode=0o770, parents=True, exist_ok=True)
        with (self.root / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self.store.heartbeat(self.owner, ready=False)
                await self.runtime_ready()
                await self.recover()
                self.ready = True
                while self.ready and not self.stop.is_set():
                    await self.runtime_ready()
                    self.store.heartbeat(self.owner)
                    if time.monotonic() - self.last_cleanup > 30:
                        self.cleanup()
                    if not await self.tick():
                        await asyncio.sleep(.25)
            finally:
                self.ready = False
                self.store.heartbeat(self.owner, ready=False)
