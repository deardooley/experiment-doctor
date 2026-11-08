"""Session-owned control queue. Never opens runner data or a runtime socket."""
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

TERMINAL = {"VERIFIED_REPAIR", "VERIFIED_HEALTHY", "NOT_REPAIRED", "UNVERIFIED", "BLOCKED",
            "INCOMPLETE", "CANCELLED", "CONTAINED", "NOT_CONTAINED"}


class LimitExceeded(ValueError):
    pass


class ControlStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(mode=0o770, parents=True, exist_ok=True)
        self.blobs = root / "blobs"
        self.blobs.mkdir(mode=0o770, exist_ok=True)
        path = root / "api.sqlite3"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
        except FileExistsError:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("control database must be a regular file")
            if info.st_uid == os.geteuid():
                path.chmod(0o660)
            elif stat.S_IMODE(info.st_mode) != 0o660:
                raise PermissionError("shared control database requires 0660 permissions")
        else:
            try:
                os.fchmod(fd, 0o660)
            finally:
                os.close(fd)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, expires REAL, csrf TEXT);
                CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    fixture TEXT NOT NULL, task TEXT NOT NULL, kind TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL, started REAL, ended REAL,
                    cancel INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL, report TEXT);
                CREATE TABLE IF NOT EXISTS events(cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT, session_id TEXT, at REAL, kind TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, experiment_id TEXT,
                    name TEXT, size INTEGER, sha256 TEXT);
                CREATE TABLE IF NOT EXISTS rates(scope TEXT, bucket TEXT, window INTEGER,
                    count INTEGER, PRIMARY KEY(scope,bucket,window));
                CREATE TABLE IF NOT EXISTS health(key TEXT PRIMARY KEY, value REAL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "api.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def emit(db, experiment_id, session_id, kind, data=None):
        db.execute("INSERT INTO events(experiment_id,session_id,at,kind,data) VALUES(?,?,?,?,?)",
                   (experiment_id, session_id, time.time(), kind, json.dumps(data or {}, allow_nan=False)))

    def security(self, kind, session_id=None):
        try:
            self.rate("security-event-budget", "all", 1000)
        except LimitExceeded:
            return
        with self.connect() as db:
            self.emit(db, None, session_id, kind)

    def rate(self, scope, bucket, maximum, seconds=60):
        window = int(time.time() // seconds)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rates WHERE window<? AND scope=?", (window - 2, scope))
            row = db.execute("SELECT count FROM rates WHERE scope=? AND bucket=? AND window=?",
                             (scope, bucket, window)).fetchone()
            if row and row[0] >= maximum:
                raise LimitExceeded("rate limit")
            db.execute("INSERT INTO rates VALUES(?,?,?,1) ON CONFLICT(scope,bucket,window) "
                       "DO UPDATE SET count=count+1", (scope, bucket, window))

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND expires>?",
                             (session_id, time.time())).fetchone()
            return dict(row) if row else None

    def add_session(self, session_id, csrf):
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (session_id, time.time() + 86400, csrf))

    def enqueue(self, session_id, fixture, task="", kind="diagnosis"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = "status IN ('QUEUED','RUNNING')"
            if db.execute(f"SELECT 1 FROM experiments WHERE session_id=? AND {active}", (session_id,)).fetchone():
                raise LimitExceeded("one active diagnosis per session")
            if db.execute(f"SELECT count(*) FROM experiments WHERE {active}").fetchone()[0] >= 10:
                raise LimitExceeded("global queue full")
            experiment_id = str(uuid4())
            db.execute("INSERT INTO experiments(id,session_id,fixture,task,kind,status,created) "
                       "VALUES(?,?,?,?,?,'QUEUED',?)",
                       (experiment_id, session_id, fixture, task, kind, time.time()))
            self.emit(db, experiment_id, session_id, "QUEUED")
            return experiment_id

    def get(self, experiment_id, session_id=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM experiments WHERE id=?", (str(experiment_id),)).fetchone()
            if row is None or (session_id is not None and row["session_id"] != session_id):
                raise KeyError(experiment_id)
            return dict(row)

    def event(self, experiment_id, kind, data=None):
        row = self.get(experiment_id)
        with self.connect() as db:
            self.emit(db, str(experiment_id), row["session_id"], kind, data)

    def events(self, experiment_id, session_id, after):
        self.get(experiment_id, session_id)
        with self.connect() as db:
            return [{"cursor": r["cursor"], "at": r["at"], "kind": r["kind"], "data": json.loads(r["data"])}
                    for r in db.execute("SELECT * FROM events WHERE experiment_id=? AND cursor>? "
                                        "ORDER BY cursor LIMIT 100", (str(experiment_id), after))]

    def cancel(self, experiment_id, session_id):
        self.get(experiment_id, session_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM experiments WHERE id=?", (str(experiment_id),)).fetchone()
            if row["status"] in TERMINAL or row["cancel"]:
                return
            db.execute("UPDATE experiments SET cancel=1 WHERE id=?", (str(experiment_id),))
            if row["status"] == "QUEUED":
                db.execute("UPDATE experiments SET status='CANCELLED',ended=? WHERE id=?",
                           (time.time(), str(experiment_id)))
            self.emit(db, str(experiment_id), session_id, "CANCEL_REQUESTED")

    def claim(self, owner):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM experiments WHERE status='RUNNING'").fetchone():
                return None
            row = db.execute("SELECT id FROM experiments WHERE status='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            now = time.time()
            db.execute("UPDATE experiments SET status='RUNNING',owner=?,started=?,lease_until=? WHERE id=?",
                       (owner, now, now + 15, row[0]))
            result = db.execute("SELECT * FROM experiments WHERE id=?", (row[0],)).fetchone()
            self.emit(db, row[0], result["session_id"], "RUNNING")
            return dict(result)

    def heartbeat(self, owner, ready=True):
        with self.connect() as db:
            db.execute("INSERT INTO health VALUES('worker_until',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (time.time() + 15 if ready else 0,))
            db.execute("UPDATE experiments SET lease_until=? WHERE owner=? AND status='RUNNING'",
                       (time.time() + 15, owner))

    def ready(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM health WHERE key='worker_until'").fetchone()
            return row is not None and row[0] > time.time()

    def interrupted(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM experiments WHERE status='RUNNING'")]

    def finish(self, experiment_id, owner, report, files=None):
        if report["outcome"] not in TERMINAL:
            raise ValueError("invalid terminal outcome")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            if row["status"] != "RUNNING" or row["owner"] != owner:
                raise ValueError("experiment claim lost")
            # Completion and cancellation have one atomic winner. A pending
            # cancellation must agree with both the report and its attachment.
            if row["cancel"] and report["outcome"] != "NOT_CONTAINED":
                report = report | {"outcome": "CANCELLED"}
            items = []
            files = dict(files or {})
            files["report.json"] = json.dumps(report, allow_nan=False, indent=2).encode()
            if len(files) > 64 or sum(map(len, files.values())) > 32 * 1024 * 1024:
                raise ValueError("public evidence export limit")
            for name, data in files.items():
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name) or len(data) > 10 * 1024 * 1024:
                    raise ValueError("unsafe evidence export")
                artifact_id = str(uuid4())
                with (self.blobs / artifact_id).open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                items.append((artifact_id, experiment_id, name, len(data), hashlib.sha256(data).hexdigest()))
            db.executemany("INSERT INTO artifacts VALUES(?,?,?,?,?)", items)
            db.execute("UPDATE experiments SET status=?,ended=?,lease_until=NULL,report=? WHERE id=?",
                       (report["outcome"], time.time(), json.dumps(report, allow_nan=False), experiment_id))
            self.emit(db, experiment_id, row["session_id"], report["outcome"])

    def artifacts(self, experiment_id, session_id):
        self.get(experiment_id, session_id)
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM artifacts WHERE experiment_id=?",
                                                  (str(experiment_id),))]

    def artifact(self, artifact_id, session_id):
        with self.connect() as db:
            row = db.execute("SELECT artifacts.* FROM artifacts JOIN experiments "
                             "ON experiments.id=artifacts.experiment_id WHERE artifacts.id=? AND session_id=?",
                             (str(artifact_id), session_id)).fetchone()
            if row is None:
                raise KeyError(artifact_id)
            return dict(row)

    def cleanup(self):
        with self.connect() as db:
            # Active work is never eligible. Keep job/event audit metadata after expiry.
            rows = db.execute("SELECT artifacts.id FROM artifacts JOIN experiments ON experiments.id=artifacts.experiment_id "
                              "WHERE ended<? AND status NOT IN ('QUEUED','RUNNING')", (time.time() - 86400,)).fetchall()
            for row in rows:
                (self.blobs / row[0]).unlink(missing_ok=True)
                db.execute("DELETE FROM artifacts WHERE id=?", (row[0],))
            expired = db.execute("SELECT id,status,session_id FROM experiments WHERE ended<? "
                                 "AND status NOT IN ('QUEUED','RUNNING')", (time.time() - 86400,)).fetchall()
            for row in expired:
                summary = {"outcome": row["status"], "evidence_expired": True}
                db.execute("UPDATE experiments SET task='',report=? WHERE id=?", (json.dumps(summary), row["id"]))
                db.execute("DELETE FROM events WHERE experiment_id=?", (row["id"],))
                self.emit(db, row["id"], row["session_id"], "EVIDENCE_EXPIRED")
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time() - 86400,))
            db.execute("DELETE FROM events WHERE experiment_id IS NULL AND at<?", (time.time() - 86400,))
            retained = {row[0] for row in db.execute("SELECT id FROM artifacts")}
        # Only the singleton worker publishes blobs, and cleanup runs between jobs.
        for path in self.blobs.iterdir():
            if path.name not in retained and (path.is_file() or path.is_symlink()):
                path.unlink()
