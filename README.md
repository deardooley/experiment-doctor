# Experiment Doctor

A scientific simulation repair service with independently checked evidence and disposable execution sandboxes. Original project code is covered by LICENSE. See IMPLEMENTATION_PLAN.md for scope and milestones.

M0–M3 are complete: live Vultr-driven repairs passed independent checks; false success was rejected; containment, session authorization and separate service permissions were measured on Vultr. See [milestone evidence](docs/milestones.md). Temporary test VMs were destroyed. The browser product and production HTTPS release remain M4/M5.

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

The [private execution guide](docs/execution.md) covers `make runner`, the Unix-socket ExecutionClient, and `make test-runtime`. The [scientific doctor guide](docs/scientific-doctor.md) covers `make build-verifier` and `make diagnose`, the four curated fixtures, patch policy, trusted checks and provenance reports. Full replay and public deployment commands are future work.

The [security operations guide](docs/security.md) covers the public API, separate control worker, signed sessions/CSRF, operator-only network demonstration, service identities and retention. `make test-security` runs authorization checks; `make containment-demo` performs a real denied connection followed by verified healthy computation on the Linux runner host. See the [threat model](docs/threat-model.md) for measured boundaries and shared-kernel limitations.

## Browser workbench (M4)

The interface supports fixture selection, event progress, diagnosis/diff, measured before/after plots, independent checks and evidence downloads. See [product interface operations](docs/product-interface.md) for the API/worker setup and browser checks. Run `make web-setup web-dev` for the loopback frontend; it needs the API and worker described there. Browser tests use labelled deterministic fixtures; live inference and sandbox evidence are recorded separately. Production HTTPS delivery remains M5.
