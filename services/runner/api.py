"""Private Unix-socket API. Never proxy /execution through the public frontend."""
import fcntl
import hashlib
import shutil
import threading
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from packages.contracts import JobResult, JobSpec
from services.runner.runtime import DockerRuntime
from services.runner.store import Conflict, QueueFull, Store
from services.worker.supervisor import Supervisor


def create_app(settings, runtime=None):
    settings.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(settings.root / "runner.sqlite3")
    runtime = runtime or DockerRuntime(settings)
    supervisor = Supervisor(store, runtime, settings)

    @asynccontextmanager
    async def lifespan(app):
        lock = (settings.root / "supervisor.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Remove crash survivors before launching even the fixed probes.
            runtime.cleanup_all()
            runtime.preflight()
            supervisor.reconcile()
            thread = threading.Thread(target=supervisor.run, name="runner-supervisor", daemon=True)
            thread.start()
            app.state.thread = thread
            yield
        finally:
            supervisor.stop.set()
            if hasattr(app.state, "thread"):
                app.state.thread.join(timeout=45)
            supervisor.ready = False
            lock.close()

    app = FastAPI(title="Experiment Doctor private runner", version="1", lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.store, app.state.supervisor = store, supervisor

    @app.middleware("http")
    async def bound_request(request: Request, call_next):
        # Protect JSON parsing even when Content-Length is absent or dishonest.
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 65536:
                return Response(status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        return await call_next(request)

    def job(job_id):
        try:
            row = store.get(job_id)
        except KeyError:
            raise HTTPException(404, "unknown job") from None
        return JobResult(job_id=row["id"], status=row["status"], reason=row["reason"],
                         exit_code=row["exit_code"], cleanup=row["cleanup"],
                         created_at=row["created"], started_at=row["started"],
                         ended_at=row["ended"], artifact_manifest_hash=row["manifest_hash"])

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready():
        if (not supervisor.ready or not app.state.thread.is_alive()
                or shutil.disk_usage(settings.root).free < settings.disk_reserve):
            raise HTTPException(503, "runner unavailable")
        with store.connect() as db:
            db.execute("SELECT 1")
        return {"status": "ready", "policy": "sandbox-v1"}

    @app.post("/execution/v1/jobs", status_code=202)
    def submit(spec: JobSpec):
        try:
            settings.authorize(spec)
        except ValueError:
            raise HTTPException(403, "job denied by runner allowlist") from None
        ready()
        try:
            job_id = store.submit(spec)
        except Conflict:
            raise HTTPException(409, "idempotency conflict") from None
        except QueueFull:
            raise HTTPException(429, "queue full") from None
        return {"job_id": job_id}

    @app.get("/execution/v1/jobs/{job_id}", response_model=JobResult)
    def status(job_id: UUID):
        return job(job_id)

    @app.post("/execution/v1/jobs/{job_id}/cancel", response_model=JobResult)
    def cancel(job_id: UUID):
        job(job_id)
        store.cancel(job_id)
        return job(job_id)

    @app.get("/execution/v1/jobs/{job_id}/events")
    def events(job_id: UUID, after: int = Query(default=0, ge=0)):
        job(job_id)
        return store.events(job_id, after)

    @app.get("/execution/v1/jobs/{job_id}/artifacts")
    def artifacts(job_id: UUID):
        job(job_id)
        return store.artifacts(job_id)

    @app.get("/execution/v1/artifacts/{artifact_id}")
    def download(artifact_id: UUID):
        with store.connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (str(artifact_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "unknown artifact")
        path = supervisor.artifact_dir / str(artifact_id)
        # Download uses bounded immutable bytes; paths and names never come from URLs.
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row["size"]:
            raise HTTPException(500, "artifact integrity failure")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise HTTPException(500, "artifact integrity failure")
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{row["name"]}"',
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    return app
