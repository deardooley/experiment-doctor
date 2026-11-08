# M3 authorization and containment operations

The public API, model/control worker and private runner are separate processes. Only the control worker has inference access; only the runner can reach its dedicated rootless Docker daemon. Candidate code still runs in a fresh disposable container per execution, with a separate trusted verifier container for scientific decisions.

## Start the services

Prepare rootless Docker using infra/host/setup-runtime. On a Linux service host, root may run infra/host/setup-control to create the shared control and private execution groups/directories. Build the verifier as described in scientific-doctor.md and start the private runner with its pinned simulation and verifier images.

Use separate credential files. The API file contains API_SESSION_KEY (at least 32 random bytes represented as a strong string), PUBLIC_ORIGIN and, only when operator probes are intentionally enabled, API_OPERATOR_TOKEN. The control worker's inference file contains only INFERENCE_BASE_URL, INFERENCE_MODEL and INFERENCE_API_KEY. Do not put cloud or inference keys in the API file, runner environment or fixture bundle. Entry points re-exec without other services' known project credential variables if a combined development environment was loaded accidentally.

```
# API shell: load API-only credentials privately first.
make api PUBLIC_ORIGIN=https://doctor.example

# Worker shell: runtime/inference.env must be private and ignored by Git.
make control-worker RUNNER_SOCKET=runtime/runner.sock INFERENCE_ENV=runtime/inference.env
```

The API always binds to 127.0.0.1. HTTPS terminates at the future M5 proxy. The explicit `--allow-http-local --origin http://127.0.0.1:8000` development mode allows an insecure cookie only on loopback; it is not a production deployment. The default configuration requires HTTPS/Secure cookies and operator probes are disabled. API_SESSION_KEY must stay stable across service restarts to preserve valid sessions.

For M3 testing without paid inference, the worker CLI supports `--verify-only`. It records that mode, makes no model call and never fabricates a repair. A broken fixture remains NOT_REPAIRED. The M2 evidence separately contains actual live Vultr repairs.

Systemd templates are in infra/systemd. The API runs as doctor-api/doctor-control; the worker as doctor-worker/doctor-control with doctor-execution membership; the runner as doctor-runner/doctor-execution. API/worker share the application queue at explicit mode 0660 and published blobs through the control group. Private diagnosis snapshots remain mode 0700 under the worker; runner data and the rootless daemon remain inaccessible to the API. Full release installation and TLS wiring remain M5.

## Public API contract

First fetch GET /api/v1/session. It sets the signed HttpOnly SameSite=Lax cookie and returns csrf_token/expires_at. Include the exact configured Origin and X-CSRF-Token on mutations; cross-origin or missing/invalid tokens receive 403 and no work is enqueued. Missing/forged/expired sessions receive 401. Client-supplied forwarding headers are not trusted for rate-limit identity.

- GET /api/v1/apps lists only healthy, coarse-step and wrong-sign curated fixtures and bounded input schemas.
- POST /api/v1/experiments accepts fixture_id and an optional task of at most 1000 characters; no code, bundles, images, paths or flags are accepted.
- GET /api/v1/experiments/{id}, /events?after=cursor, /artifacts and POST /cancel require ownership. Foreign and unknown IDs return 404.
- GET /api/v1/artifacts/{id} checks ownership and file integrity before returning a bounded attachment. Logs/source/unknown bytes never become an active page under the API origin.
- /health/live checks the API process; /health/ready also requires a current control-worker lease, ready runtime and disk reserve.

Event pages contain at most 100 ordered records. Continue with the last returned cursor until the page is empty. They include actual job/tool events and containment observations. Treat source, logs, hypotheses and task strings as untrusted text when building M4's interface.

The API has a 4-KiB body cap, 64-connection server bound, per-peer/session creation and submission limits, a global daily diagnosis budget, one active experiment per session and ten globally queued/running experiments. Queues and ownership use SQLite transactions. Completion and cancellation have one atomic winner, including the stored report attachment. Terminal states do not change.

Submission intent is persisted before contacting the runner. If the worker dies after runner acceptance but before it knows the job ID, recovery resolves the idempotency key, cancels/settles that job, marks the interrupted diagnosis INCOMPLETE and preserves queued work. No automatic duplicate diagnosis is submitted. Readiness fails on stale worker leases or unresolved runtime cleanup.

The worker periodically expires terminal-job evidence after 24 hours, removing public blobs, private diagnosis snapshots and their detailed journal entries. A minimal outcome/expired marker remains; active work is never deleted. Export evidence before expiry. Security audit events are rate-bounded and old global denials expire after 24 hours; no cookies, credentials or request bodies are logged in those events.

## Visible containment moment

For a local trusted operator on the runner host:

```
make containment-demo RUNNER_SOCKET=runtime/runner.sock
```

This creates a controlled host listener and proves it is reachable from the host, submits fixed repository-owned connection attempts in a real no-network sandbox, checks that no probe message arrived, verifies cleanup, runs a healthy decay experiment with primary/refinement/held-out verification, and checks continued runtime health. It prints actual errno observations and the measured outcome. It does not print a cosmetic blocked result.

To demonstrate through the public API, explicitly enable the operator route on the API CLI with --enable-operator-probes and a separate strong API_OPERATOR_TOKEN. POST /api/v1/operator/probes/network also requires the normal session, Origin, CSRF token and `Authorization: Bearer <operator-token>`. The request accepts no arbitrary target/source. Poll the owned experiment/events for CONTAINMENT_DENIED and HEALTHY_AFTER_CONTAINMENT; inspect the report's positive control, actual connections, cleanup and numerical checks. Leave this feature disabled for normal public operation unless an operator intentionally needs it.

`scripts/security_smoke.py` exercises actual HTTP session/CSRF/ownership/private-surface denials and that operator workflow. `scripts/verify_service_permissions.py` is a root-only dev/test helper that checks the real Linux service users against the Unix sockets, private runner database and a synthetic credential canary. It prints only booleans, never canary contents or credentials.

## Test and release gate

```
make check
make test-security
SIMULATION_IMAGE=<pinned-image> VERIFIER_IMAGE=<built-digest> make test-runtime
```

Default tests do not execute candidate code on the host. The opt-in Linux suite uses real sandboxes for host-only/synthetic-environment/cross-job canaries, read-only writes, no-network operations, symlinks/hardlinks/FIFOs, oversized/active output, log flooding, actual memory/PID/CPU pressure, and continued API health. The injected-log test uses a clearly labeled scripted attacker proposal to prove a real deterministic verifier-edit denial; it does not claim a live model is immune to prompt injection. M1/M2 execution and science regressions remain in the same suite.

Runtime startup and every job check rootless/cgroup-v2/seccomp availability. Before any candidate executes, a fixed trusted assertion process checks the actual memory/swap/PID/CPU limits, non-root UID, NoNewPrivs=1, Seccomp=2, CapEff=0, loopback-only network, read-only root and bounded writable tmpfs. An enforcement loss stops readiness and new claims; no candidate code executes under unconfirmed controls.

See threat-model.md for boundaries and limitations. These are measured containment controls on a shared host kernel, not hostile multi-tenant security guarantees. M4 supplies the browser product; M5 supplies public HTTPS deployment and release operations.
