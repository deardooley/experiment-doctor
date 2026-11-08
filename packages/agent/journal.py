"""Control-plane persistence. The runner never opens this database."""
import json
import sqlite3
import time
from pathlib import Path


class Journal:
    def __init__(self, root: Path):
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = root
        self.db = sqlite3.connect(root / "control.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, fixture TEXT,
                status TEXT, started REAL, report TEXT);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, experiment_id TEXT,
                revision INTEGER, bundle_hash TEXT, parameters TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, experiment_id TEXT, spec TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, experiment_id TEXT,
                at REAL, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, job_id TEXT, metadata TEXT);
            CREATE TABLE IF NOT EXISTS verification_results(attempt_id TEXT PRIMARY KEY, result TEXT);
        ''')
        self.db.commit()

    def start(self, experiment_id, fixture):
        with self.db:
            self.db.execute("INSERT INTO experiments VALUES(?,?,'RUNNING',?,NULL)",
                            (experiment_id, fixture, time.time()))
        directory = self.root / experiment_id
        directory.mkdir(mode=0o700)
        return directory

    def event(self, experiment_id, kind, data):
        with self.db:
            self.db.execute("INSERT INTO events(experiment_id,at,kind,data) VALUES(?,?,?,?)",
                            (experiment_id, time.time(), kind, json.dumps(data, allow_nan=False)))

    def attempt(self, attempt_id, experiment_id, revision, digest, parameters):
        with self.db:
            self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?)",
                            (attempt_id, experiment_id, revision, digest, json.dumps(parameters)))

    def job(self, job_id, experiment_id, spec):
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES(?,?,?)", (str(job_id), experiment_id, spec.model_dump_json()))

    def artifacts(self, job_id, items):
        with self.db:
            for item in items:
                self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)",
                                (item["id"], str(job_id), json.dumps(item)))

    def verification(self, attempt_id, result):
        with self.db:
            self.db.execute("INSERT INTO verification_results VALUES(?,?)",
                            (attempt_id, result.model_dump_json()))

    def finish(self, experiment_id, report):
        raw = json.dumps(report, indent=2, allow_nan=False)
        path = self.root / experiment_id / "report.json"
        with path.open("x") as stream:
            stream.write(raw)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        with self.db:
            self.db.execute("UPDATE experiments SET status=?,report=? WHERE id=? AND status='RUNNING'",
                            (report["outcome"], raw, experiment_id))
        return path
