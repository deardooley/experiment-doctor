# M1 private execution vertical slice

The M1 runner foundation accepts typed simulation jobs whose image and source SHA-256 match its server-owned registry. The CLI registers the original `experiments/decay/simulation.py`; parameters are separately bound in the immutable JobSpec. No caller-supplied command, mount, host path or arbitrary image is accepted. M2 adds bounded private candidate registration and a separately pinned trusted verifier; see [scientific doctor](scientific-doctor.md).

Run on a Linux host with the dedicated rootless Docker service already installed:

```
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
export SIMULATION_IMAGE=python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
uv sync --frozen
docker pull "$SIMULATION_IMAGE"  # operator action; jobs never pull images
make runner
```

Without make, use `.venv/bin/python -m services.runner --root runtime/runner --socket runtime/runner.sock --image "$SIMULATION_IMAGE"`. The CLI exposes only a Unix socket. It binds mode 0660 in a restricted directory, holds a singleton filesystem lock, verifies runtime enforcement, and starts its private supervisor. Do not proxy `/execution` through a public web server. Public session authorization is a later milestone.

Use `packages.execution.local.LocalExecutionClient(Path("runtime/runner.sock"))`. Its asynchronous submit/status/cancel/artifacts methods implement ExecutionClient; `read_artifact` provides a bounded attachment download. Build a JobSpec using the image digest and SHA-256 of the approved simulation source. Each new computation uses a new attempt UUID and idempotency key. Repeating the same immutable specification/key returns the same job, including after cancellation or restart; changing a specification under an existing key returns 409.

Private routes:

| Route | Behavior |
|---|---|
| `POST /execution/v1/jobs` | 202; validates policy and bounded queue before scheduling |
| `GET /execution/v1/jobs/{id}` | Status, reason, timestamps, exit code, cleanup and manifest hash |
| `POST /execution/v1/jobs/{id}/cancel` | Idempotent; queued jobs terminate immediately, running jobs request cleanup |
| `GET /execution/v1/jobs/{id}/events?after=0` | Ordered bounded event page |
| `GET /execution/v1/jobs/{id}/artifacts` | Opaque artifact IDs, names, sizes and SHA-256 |
| `GET /execution/v1/artifacts/{id}` | Integrity-checked attachment, octet-stream and nosniff |
| `/health/live`, `/health/ready` | Process liveness versus preflight, DB, worker and disk readiness |

The runner's SQLite WAL database is its private execution journal, **not the application database**. It stores jobs, leases, cancellation requests, lifecycle events and artifact metadata. Only the runner reads this journal. The model/control worker in packages/agent accesses the private API through ExecutionClient and cannot access Docker. The `services/worker/supervisor.py` module is the runner's execution supervisor, not the model worker.

Claims use an immediate SQLite transaction, unique idempotency keys and owner/lease heartbeats. At most one job runs at a time and at most ten are queued/running. Startup holds a singleton lock, removes scope-labeled containers, proves runtime controls, and marks interrupted jobs LOST without retrying them. Queued jobs survive. The periodic janitor runs between jobs, reconciles orphaned containers and expires terminal-job artifacts after 24 hours. New work is refused below a 64-MiB free-disk reserve. Cleanup failure makes readiness fail and stops further claims.

Every job gets a **fresh container** with Docker `--init`, fixed resource limits, non-root identity, read-only root, no network/capabilities, cleared environment, bounded tmpfs and no host bind mounts. A keeper process remains alive only for that job's lifetime. A fixed bootstrap runs candidate source through an exec process; Docker's exit status supplies execution status. The keeper preserves tmpfs output until collection and init reaps orphaned children. The supervisor removes the entire container tree on success, error, deadline or cancellation. Containers are never reused between jobs.

Docker archive-copy omits tmpfs mount contents. The fixed exporter therefore reads only regular, single-link `trajectory.csv` via O_NOFOLLOW inside the live sandbox, with a size limit, and streams an archive. Returned bytes remain untrusted: the host rejects links, paths, extra members, oversize/malformed archives and never extracts archives onto its filesystem. Candidate background processes could mutate sandbox output during capture; the captured bytes are immutable/hash-bound after collection, and scientific validity remains for the independent M2 verifier. Logs are drained continuously and capped at 256 KiB per stream. Total exported artifacts are capped at 10 MiB. Successful process execution is **not** a scientific pass.

Artifacts are written under opaque UUID names, fsynced before journal publication and returned with a deterministic manifest hash. Download checks the stored size/hash. Startup removes partial, unpublished artifact files. Missing output is not invented. Logs are never rendered as HTML.

Validation:

```
make check
ED_RUNTIME_TESTS=1 make test-runtime  # explicit Linux/rootless opt-in; no credentials needed
```

The real runtime suite exercises healthy numeric output, exceptions, OOM, timeout, cancellation followed by a healthy job, forced worker death, and runner crash/restart over the Unix socket. Unit tests use fixed fake outputs and never execute candidate source on the host.

The systemd unit in `infra/systemd/` is a deployment template. Create the `doctor-execution` group, grant only doctor-runner and the control worker membership, and keep the runner data directory mode 0700. Its runner.env contains only the digest-pinned SIMULATION_IMAGE, VERIFIER_IMAGE and rootless DOCKER_HOST (with the actual runner UID), never inference/cloud keys. Installing versioned releases and service users/groups reproducibly remains M5 work.
