"""Private runner journal. Never opens the application's database."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from packages.contracts import JobSpec

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "LOST"}


class Conflict(ValueError):
    pass


class QueueFull(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES(1);
                INSERT OR IGNORE INTO schema_version VALUES(2);
                CREATE TABLE IF NOT EXISTS security_events(
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, experiment_id TEXT, kind TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, spec TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, exit_code INTEGER,
                    created REAL NOT NULL, started REAL, ended REAL,
                    owner TEXT, lease_until REAL, cancel INTEGER NOT NULL DEFAULT 0,
                    cleanup TEXT NOT NULL DEFAULT 'pending', manifest_hash TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts(
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, name TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                    UNIQUE(job_id,name));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db, job_id, kind):
        db.execute("INSERT INTO events(job_id,at,kind) VALUES(?,?,?)",
                   (job_id, time.time(), kind))

    def security(self, kind, experiment_id=None):
        with self.connect() as db:
            db.execute("INSERT INTO security_events(at,experiment_id,kind) VALUES(?,?,?)",
                       (time.time(), experiment_id, kind))

    def submit(self, spec: JobSpec):
        raw = spec.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT id,spec FROM jobs WHERE key=?",
                                  (spec.idempotency_key,)).fetchone()
            if existing:
                if existing["spec"] != raw:
                    raise Conflict("idempotency key already binds a different specification")
                return existing["id"]
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')"
                          ).fetchone()[0] >= 10:
                raise QueueFull("runner queue is full")
            job_id = str(uuid4())
            db.execute("INSERT INTO jobs(id,key,spec,status,created) VALUES(?,?,?,'QUEUED',?)",
                       (job_id, spec.idempotency_key, raw, time.time()))
            self.event(db, job_id, "QUEUED")
            return job_id

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return dict(row)

    def by_key(self, key):
        with self.connect() as db:
            row = db.execute("SELECT id FROM jobs WHERE key=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            return self.get(row[0])

    def claim(self, owner, lease_seconds=10):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone():
                return None
            row = db.execute("SELECT id FROM jobs WHERE status='QUEUED' ORDER BY created,id LIMIT 1"
                             ).fetchone()
            if row is None:
                return None
            job_id = row["id"]
            now = time.time()
            db.execute("UPDATE jobs SET status='RUNNING',owner=?,lease_until=?,started=? WHERE id=?",
                       (owner, now + lease_seconds, now, job_id))
            self.event(db, job_id, "RUNNING")
        return self.get(job_id)

    def heartbeat(self, job_id, owner):
        with self.connect() as db:
            return db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND owner=? "
                              "AND status='RUNNING'", (time.time() + 10, job_id, owner)).rowcount == 1

    def cancel(self, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,cancel FROM jobs WHERE id=?", (str(job_id),)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in TERMINAL or row["cancel"]:
                return
            if row["status"] == "QUEUED":
                db.execute("UPDATE jobs SET status='CANCELLED',reason='CANCELLED',cancel=1,"
                           "ended=?,cleanup='removed' WHERE id=?", (time.time(), str(job_id)))
                self.event(db, str(job_id), "CANCELLED")
            else:
                db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (str(job_id),))
                self.event(db, str(job_id), "CANCEL_REQUESTED")

    def finish(self, job_id, owner, status, reason, exit_code, cleanup, artifacts=()):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,owner,cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row["status"] != "RUNNING" or row["owner"] != owner:
                raise Conflict("job no longer owned by supervisor")
            if row["cancel"]:
                status, reason = "CANCELLED", "CANCELLED"
            manifest = json.dumps(list(artifacts), sort_keys=True, separators=(",", ":"))
            for item in artifacts:
                db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                           (item["id"], job_id, item["name"], item["sha256"], item["size"]))
            db.execute("UPDATE jobs SET status=?,reason=?,exit_code=?,cleanup=?,ended=?,"
                       "lease_until=NULL,manifest_hash=? WHERE id=?",
                       (status, reason, exit_code, cleanup, time.time(),
                        hashlib.sha256(manifest.encode()).hexdigest(), job_id))
            self.event(db, job_id, status)

    def recover(self):
        """Called only after singleton lock and successful runtime cleanup."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM jobs WHERE status='RUNNING'").fetchall()
            for row in rows:
                db.execute("UPDATE jobs SET status='LOST',reason='LOST',ended=?,cleanup='removed',"
                           "lease_until=NULL WHERE id=?", (time.time(), row["id"]))
                self.event(db, row["id"], "LOST")
            return len(rows)

    def artifacts(self, job_id):
        self.get(job_id)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM artifacts WHERE job_id=? ORDER BY name", (str(job_id),))]

    def events(self, job_id, after=0):
        self.get(job_id)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT cursor,at,kind FROM events WHERE job_id=? AND cursor>? "
                "ORDER BY cursor LIMIT 100", (str(job_id), after))]
