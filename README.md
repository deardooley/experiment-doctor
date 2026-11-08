# Experiment Doctor

A scientific simulation repair service with independently checked evidence and disposable execution sandboxes. Original project code is covered by LICENSE. See IMPLEMENTATION_PLAN.md for scope and milestones.

M0 is complete: live Vultr inference and constrained rootless-container execution were verified. See [milestone evidence](docs/milestones.md). The temporary test VM was destroyed; application workflows and production deployment are subsequent milestones.

Prerequisites: Python 3.12 or 3.13, uv, Terraform >=1.5.7, and a dedicated Linux rootless Docker daemon with cgroup v2 delegation. Docker Desktop alone does not satisfy the target runtime gate.

Developer entry points use make. If macOS cannot locate make through Xcode, run `.venv/bin/ruff check .` and `.venv/bin/python -m pytest` directly after dependency setup.

```
make setup
make check
cp .env.example .env  # only if no private .env already exists
make probe-inference
SIMULATION_IMAGE=repository@sha256:<actual-digest> make preflight
make infra-check
```

`make probe-inference` makes a real, bounded Vultr Serverless Inference call using the privately configured model and key. It validates JSON for a future server-side dispatcher; it does not claim native tool support. Cloud provisioning credentials are separate from inference credentials. Neither is passed to containers. Never commit .env.

`make preflight` runs on Linux with GNU timeout and fails closed on a non-rootless daemon or missing immutable image. Fixed probes check cgroup limits, non-root identity, read-only root, writable tmpfs, a cleared environment, denied egress, actual memory OOM/PID enforcement, CPU throttling and supervisor deadline cleanup. On a one-core host, CPU stress uses a half-core quota to make throttling observable. No arbitrary candidate executes on the host. The broader containment suite remains M3 work.

Terraform starts the secret-free VM bootstrap and defaults to no IPv6. Actual plan/region/OS IDs and costs must be checked before an operator reviews and applies a plan. The user authorized Dallas dev/test resources with a $15 total limit; see [VM operations and budget](docs/dev-vm.md). `infra/host/setup-runtime` installs the dedicated rootless daemon after bootstrap; it does not deploy application services.

See [milestone evidence](docs/milestones.md) for actual results and blockers. M1 will add the execution service and persistence. Full replay and public deployment commands are future work.
