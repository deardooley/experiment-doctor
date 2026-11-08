# Milestone evidence

## M0 — foundation and risk spikes (2026-11-08)

Status: **M0 complete.** A live Vultr response passed schema validation, and a bounded real container run plus enforcement probes passed on a temporary Dallas rootless runtime. The VM was destroyed after testing. Application execution workflows and deployment are subsequent milestones.

- [x] Repository instructions, secret/state ignores, safe example config, developer commands, architecture decision notes.
- [x] Immutable Pydantic job/parameter contracts, lifecycle validation, transport protocol; eight deterministic contract tests pass.
- [x] Exact Python dependency pins and resolved uv.lock; Python 3.12.11 environment attached to PyCharm. Ruff passes.
- [x] Vultr provider 2.28.1 and checksum lock; Terraform fmt and validate pass. Validation required sandbox escalation for provider process execution.
- [x] Secret-free Terraform/cloud-init scaffold, separate service users, restricted SSH and IPv4 web ingress, IPv6 disabled. Actual Dallas plan and Ubuntu OS selected and applied; dedicated rootless runtime installed. Application deployment remains pending.
- [x] Schema-validated live inference probe implemented with 30-second timeout, token limit, no credential/error-body logging, no redirects, fixed official HTTPS endpoint.
- [x] Live inference response: `mimo-v2.6-flash` returned HTTP 200 and schema-valid `{"status":"ok"}` using the updated private .env. The call used a 64-token ceiling and 30-second timeout. Evidence: [m0-vultr-inference.json](evidence/m0-vultr-inference.json). Schema-validated JSON is the selected integration path; native tools were not tested. Model dispatch implementation belongs to M2. No credential was printed or passed to a sandbox.
- [x] Real local constrained container launched and removed using an existing immutable Python image digest. Observed UID 65532, memory.max=536870912, pids.max=64, cpu.max=100000 100000. Initial credential-name assertion rejected an image-inherited variable; probe now clears inherited image environment via env -i.
- [x] Target runtime enforcement: Dallas rootless/cgroup-v2 preflight passed. Memory exhaustion was OOM-killed, PID exhaustion stopped at 63 children, half-core CPU stress was throttled, egress failed, read-only root rejected writes, supervisor deadline fired, and container removal was verified. This is M0 evidence; broader host/cross-job canaries and M3 containment remain pending.
- [x] Target VM provision/preflight: authorized Dallas instance was provisioned and tested; teardown and cost evidence recorded below.
- [x] M0 dependency/image foundation: Python dependencies and Terraform provider locked; actual Python simulation base digest pinned. Production control/verifier images and frontend dependencies will be locked when introduced in M1–M5; no speculative digests or frontend lockfiles are claimed.

Next milestone: **M1**, execution vertical slice (runner, private job API, SQLite leases, artifacts, janitor, healthy fixture, timeout/cancellation and recovery). Dallas dev/test provisioning remains authorized within the remaining $15 total budget. Follow docs/dev-vm.md to recreate an ephemeral host when needed.

Final M0 checks: Ruff, all eight contract tests, shell syntax, Terraform fmt and Terraform validate passed. `make check` itself could not start because this macOS machine's Xcode-selected make executable is unavailable; its underlying Ruff and pytest commands were run directly and passed. Until make is available, use `.venv/bin/ruff check .` and `.venv/bin/python -m pytest`; the live probe can run with `.venv/bin/python scripts/probe_inference.py` after loading the private environment. This local command-wrapper issue does not invalidate the live inference/runtime evidence.

### Dallas follow-up evidence

- Live API selection: `dfw`, `vc2-1c-2gb` (1 vCPU, 2 GiB RAM), Ubuntu 24.04 LTS x64 (`2284`); $0.014/hour, $10 monthly cap. No paid add-ons. The monthly cap is not a lifetime budget.
- Terraform created six resources: VM, dedicated SSH key, firewall group and three ingress rules. SSH was limited to the operator's /32. No cloud/model credentials were copied onto the VM.
- Rootless daemon ran as doctor-runner, with CPU/memory/PID cgroup delegation; rootful Docker service/socket disabled.
- Installed Docker engine/CLI/rootless extras: `5:29.9.3-1~ubuntu.24.04~noble`; containerd: `2.4.2-3~ubuntu.24.04~noble`.
- Official Python 3.12 base resolved live to `python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`, now pinned in the simulation Dockerfile.
- Raw fixed-probe output: [m0-dallas-preflight.txt](evidence/m0-dallas-preflight.txt). Initial one-core CPU stress did not report throttling on a one-core VM; a half-core quota produced 37 throttled periods. Normal one-core cgroup configuration was checked separately.
- GNU timeout killed the blocked Docker client after its grace period; explicit container removal then verified no remaining named container. The shell `Killed` diagnostic in the evidence is expected.
- Teardown completed: all six Terraform resources destroyed; Vultr instance GET returned HTTP 404 at `2026-11-08T21:36:35Z`. No VM remains running. This session lasted under one hour; conservative compute estimate is one billed hour, **$0.014**, pending the provider's final invoice. Remaining authorization is approximately $14.986; keep cumulative usage below $15.
