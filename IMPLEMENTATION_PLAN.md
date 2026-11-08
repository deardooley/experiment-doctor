# Experiment Doctor — Hackathon Implementation Plan

**Implementation target:** one GitHub repository containing the application, execution runtime, scientific fixtures, tests, deployment configuration, and infrastructure as code.  
**Plan date:** November 8, 2026. **Status:** ready for Codex implementation; infrastructure and application have not yet been built or deployed.

## 1. Product and scope

Experiment Doctor diagnoses a failed scientific simulation, proposes a small repair, executes the original and repaired experiments in separate disposable sandboxes, and returns a report backed by independent numerical checks and downloadable evidence.

**Demo promise:** “Give the doctor a broken experiment. Watch it find the problem, test a repair, prove whether the result is scientifically credible, and contain an unsafe request.”

Confirmed from the referenced conversation: the proprietary lifecycle experiment platform cannot be supplied or published; an alternative execution API is acceptable; Agave is a possible inspiration; its deployment footprint is a concern; application and infrastructure belong in one repository. The earlier assistant responses were unavailable as readable content. Architecture, fixture choices, and estimates below are proposed implementation decisions rather than recovered agreements.

Target the **Blast Radius Zero** track. Its published brief calls for a Vultr-hosted web application and control layer, real sandbox execution, Vultr Serverless Inference for agent calls, verifiable results, and a containment moment. Deliver a public repository, demo URL, recorded demonstration, and the other submission materials listed by the organizer. [Hackathon brief](https://lablab.build/ai-hackathons/vultr-hackathon)

### MVP boundaries

Include:

- A browser interface with curated experiment cards, execution timeline, diagnosis, patch diff, before/after plots, verification checks, and evidence download.
- One live model agent using Vultr Serverless Inference, with explicit tools and a bounded repair loop.
- An Agave-inspired app registry, job submission API, status/log retrieval, and immutable artifacts.
- Original Python simulations owned by this project; no proprietary code, data, or platform dependency.
- Fresh isolated containers for all experiment code; separate verifier containers using trusted checks.
- One compelling repair fixture, one healthy control, one incorrect-but-successful fixture, and automated containment probes.
- Reproducible Vultr deployment from the same repository.

Defer full Agave deployment, compatibility with its API, HPC schedulers, arbitrary repository imports, arbitrary images, general dependency installation, public file uploads, browser agents, Kubernetes, multiuser collaboration, and parameter optimization. The public demo permits curated fixtures only; a local developer mode can exercise controlled adversarial fixtures.

## 2. Technical decisions

| Area | MVP decision | Reason |
|---|---|---|
| Web | React + TypeScript + Vite; static build served by Caddy | Small deployment and a focused interactive report |
| Control API | Python + FastAPI + Pydantic | Shared contracts with numerical tooling |
| Agent | Explicit Python state machine and typed tool dispatcher | Tool limits and policy are easy to audit |
| Inference | Vultr Serverless Inference; configurable model and endpoint | Meets selected track; no local GPU requirement |
| Persistence | SQLite WAL, migrations, local artifact directory | Avoid a database service for a single-worker demo |
| Queue | SQLite-backed jobs with one worker and leased claims | No Redis/Celery; durable restart behavior |
| Execution | Dedicated host service using a dedicated rootless Docker daemon | API and model have no runtime socket access |
| Isolation | One new container per execution; separate new container for verification | No reused process or writable filesystem |
| IaC | Terraform with Vultr provider; cloud-init plus idempotent host setup | Provisioning and application release remain in one repo |
| Release | Versioned control-plane image and simulation image, referenced by digest | Replay and rollback use known bytes |

Use Agave's concepts, not its full service stack or source code. The referenced repository contains separate apps, jobs, files, systems, auth, and other components; this project implements only the narrow execution contract it needs. No drop-in Agave compatibility is promised. [Agave science APIs](https://github.com/agaveplatform/science-apis)

Pin actual dependency versions, Terraform provider versions, lockfiles, and image digests during the first milestone. Do not put speculative current versions in configuration. Check the selected inference model's structured-output/tool support with a live probe; use schema-validated JSON with the same server-side dispatcher if native tool calling is unavailable.

## 3. Architecture and trust boundaries

```mermaid
flowchart TD
    U[Browser] --> P[Caddy: TLS and static web]
    P --> A[FastAPI: sessions, policy, jobs, reports]
    A --> D[(SQLite and immutable artifacts)]
    W[Worker: bounded agent state machine] --> D
    W --> L[Vultr Serverless Inference]
    W --> E[Private execution API over Unix socket]
    E --> R[Dedicated rootless container runtime]
    R --> B[Fresh baseline or repair sandbox: no network]
    R --> V[Fresh trusted verifier sandbox: no network]
    E --> D
```

Run Caddy, API, worker, and runner as separate system services under distinct Linux users where appropriate. The worker owns model credentials; the runner has runtime access but no model or cloud credentials. The API cannot call Docker directly. The runner socket is accessible only to the worker's authorized group, with separate runner-managed execution and artifact directories. SQLite access is restricted to control-plane services; the runner returns bounded metadata through its API rather than writing application tables directly.

The LLM, generated patches, simulation logs, and simulation outputs are untrusted. Only deterministic server policy authorizes tools. Only a trusted verifier determines scientific outcomes. Neither simulation code nor the model can edit verifier code, fixture reference values, tolerances, runtime settings, or the final verdict.

One Vultr VM is the hackathon topology. Containers share a host kernel, so this is a measured containment demonstration, not a guarantee against kernel exploits or hostile multi-tenant workloads. Rootless Docker mitigates daemon/runtime privilege exposure; it does not replace a stronger security boundary. [Docker rootless mode](https://docs.docker.com/engine/security/rootless/)

### Initial resource envelope

Planning target: 2 vCPU, 4 GiB RAM, roughly 40 GiB disk; select a real available plan after checking credits and regional availability. This is a sizing hypothesis, not an event allocation or price quote. Prebuild images outside the small VM where possible. If the provided VM is smaller, measure first and reduce control-plane limits and concurrency; do not remove sandbox enforcement to make it fit.

| Budget | Initial cap |
|---|---|
| Running experiment/verifier containers | 1 total |
| Per sandbox | 1 CPU, 512 MiB memory, no additional swap, 64 PIDs |
| Runtime deadline | 30 seconds per job; supervisor kills after deadline |
| Writable sandbox storage | 32 MiB workspace tmpfs + 64 MiB output tmpfs |
| Exported artifacts / logs | 10 MiB total / 256 KiB per stream |
| One diagnosis | At most 3 revisions; each has 1 primary + 2 auxiliary simulation runs and 1 verification job (12 jobs maximum) |
| Model usage | At most 5 calls; per-call timeout; configurable token ceiling |
| Entire diagnosis | 180-second deadline; no unbounded retries |
| Demo service | Global queue cap 10; per-session cap 1 active diagnosis |

Runtime flags alone are not evidence. Startup checks must verify CPU, memory, and PID controls actually work on the target rootless/cgroup configuration; readiness fails closed if enforcement is unavailable. Docker documents that containers have no default resource limits and that host capabilities affect enforcement. [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)

## 4. Scientific fixtures and verification

Use a small decay ODE, `dx/dt = -k*x`, with analytical solution `x(t) = x0*exp(-k*t)`. Default fixture: `k=1 s^-1`, `x0=1`, `t_end=5 s`. The simulation uses forward Euler; trusted verification uses the analytical formula independently.

| Fixture | Fault or behavior | Expected result |
|---|---|---|
| `decay-coarse-step` | `dt=2.5 s`, producing unstable negative values | Doctor reduces time step; baseline fails scientific checks, repair passes |
| `decay-healthy` | `dt=0.01 s` with correct update | Verified healthy; no repair required |
| `decay-wrong-sign` | `x_next = x + k*x*dt`; process exits zero | Execution succeeds, scientific verification fails; repair changes sign |
| `decay-false-success` | Writes `verified=true` and misleading “all checks passed” logs with bad trajectory | Trusted verifier ignores self-attestation and rejects trajectory |

For the coarse-step repair, prefer `dt <= 0.01 s` for the chosen tolerance, rather than merely satisfying Euler's stability threshold. The report distinguishes stability from accuracy. Ensure the final time is sampled exactly, including a partial last step when necessary.

Version a `VerificationSpec` containing the equation, units, parameters, time grid rules, finite-value requirement, tolerances, and verifier digest. Keep it outside the editable experiment bundle. For these default fixtures require:

1. A bounded valid CSV/JSON trajectory with finite numeric values, increasing times, the expected initial value, and endpoint `t=5` within a declared timestamp tolerance.
2. Nonnegativity within `1e-12` and nonincreasing concentration within `1e-12`.
3. Maximum absolute error against the analytic solution at every reported time no greater than `0.01*x0`.
4. A refinement rerun using `dt/2`, with maximum analytic error no greater than the coarse run's error plus `1e-10`; the controller submits it as a separate constrained simulation job.
5. A held-out parameter case, such as `k=0.5`, submitted by the controller as a separate constrained simulation job and checked against the independent reference. Keep the primary fixture parameters unchanged.

The trusted verifier reads only bounded numeric artifacts from the primary, refinement, and held-out simulation jobs. It never imports candidate modules or executes candidate code. The controller supplies immutable inputs and binds each output hash to its job and parameter set. Skip auxiliary runs when primary output is missing or already invalid. Run candidate computations only in ordinary untrusted sandboxes; execute the independent numeric checker in a separate trusted image. Parse results from a fixed verifier output path, with bounded schema validation. Neither candidate stdout nor a candidate-provided `verified` field can supply the verdict. Missing auxiliary evidence yields an explicit incomplete/failing check, never a pass.

A pass demonstrates these checks for this model and parameters, not general scientific validity. State assumptions and limitations in every report. Unknown models receive `UNVERIFIED`, never an invented scientific pass. Hashes establish artifact identity; they do not establish correctness.

## 5. Agent workflow and policy

Implement this explicit workflow:

1. **Intake:** select a curated fixture; validate bundle, requested task, permissions, and budget; assign an experiment ID.
2. **Baseline:** run original code in a fresh sandbox, capture status and bounded artifacts, submit auxiliary runs if appropriate, then verify.
3. **Diagnose:** send the model only the task, approved code, verification spec summary, sanitized logs, and measured failures. Request a structured hypothesis, evidence references, and patch.
4. **Authorize:** validate the patch against allowed files and byte limits; reject paths outside the bundle and any verifier/runtime changes. Tool policy, not prompt wording, makes this decision.
5. **Repair and rerun:** persist a new immutable candidate revision; execute in a new sandbox, collect auxiliary runs as needed, and verify independently.
6. **Decide:** stop when checks pass, budget is exhausted, a policy violation occurs, or evidence is insufficient. Permit at most one further repair after the first failed repair.
7. **Report:** render original failure, diagnosis, patch, before/after metrics, check details, limitations, and artifact links. Use deterministic templates if report generation times out.

Typed tools: `read_experiment`, `submit_job`, `get_job`, `read_artifact`, `propose_patch`, `verify_candidate`, and `finalize_report`. No arbitrary shell tool, network tool, host filesystem tool, image pull, or infrastructure tool is available to the agent. Tool responses carry stable IDs and are treated as data. Never follow instructions embedded in logs or artifacts.

Keep the original experiment immutable. Model-generated changes may touch only `simulation.py` and bounded `parameters.json` fields. The governing equation and reference parameters remain fixed; changing the task to satisfy the checker is forbidden. Python code is untrusted regardless of static scanning; containment is mandatory even for apparently harmless patches.

On inference failure, show the real completed evidence and `INCOMPLETE`; do not fabricate a diagnosis. Deterministic scripted responses are allowed only in explicitly labeled offline tests or replay mode. The judged happy path must make a live Vultr model call and perform real execution.

## 6. Lightweight execution API and data contracts

Public control API is session-scoped; internal execution routes are private and unavailable through Caddy. Agave-style names describe concepts, not a compatible wire protocol.

| Surface | Endpoint | Contract |
|---|---|---|
| Public | `GET /api/v1/apps` | Curated app ID, version, input schema, verifier version |
| Public | `POST /api/v1/experiments` | Fixture ID and bounded task; returns `202`, experiment ID |
| Public | `GET /api/v1/experiments/{id}` | Current phase, attempts, measured outcomes, report |
| Public | `GET /api/v1/experiments/{id}/events?after=...` | Ordered event polling with cursor; no log-derived HTML |
| Public | `POST /api/v1/experiments/{id}/cancel` | Idempotent cancellation request |
| Public | `GET /api/v1/artifacts/{id}` | Authorized, bounded download; opaque ID only |
| Private | `POST /execution/v1/jobs` | Typed immutable job specification; idempotency key |
| Private | `GET /execution/v1/jobs/{id}` | Status, timestamps, exit reason, artifact IDs |
| Private | `POST /execution/v1/jobs/{id}/cancel` | Stop process tree/container and clean up |
| Operational | `/health/live`, `/health/ready` | Liveness vs DB/runtime/policy/model-configuration readiness |

`JobSpec`: schema version, experiment/attempt IDs, app/version, server-resolved image digest, candidate bundle hash, validated parameters, fixed runtime profile, trusted verifier version where applicable, idempotency key. Callers cannot provide Docker flags, host paths, arbitrary commands, images, or mounts. Runner independently validates the full spec.

`JobResult`: job ID, status, exit code, reason code, start/end times, observed resource usage where available, artifact manifest hash, runtime policy version, and cleanup outcome. Distinguish `TIMEOUT`, `OOM`, `CANCELLED`, `POLICY_DENIED`, and `RUNTIME_ERROR`.

`VerificationResult`: spec version, pass/fail/unverified, per-check measurements and tolerances, baseline/candidate hashes, reference/verifier digest, and evidence IDs. The model cannot populate this structure.

`Report`: hypothesis, evidence references, patch, before/after comparison, execution status, scientific verdict, containment events, limitations, model ID, usage, and provenance. Use `VERIFIED_REPAIR`, `VERIFIED_HEALTHY`, `NOT_REPAIRED`, `UNVERIFIED`, `BLOCKED`, `INCOMPLETE`, or `CANCELLED` as final outcomes.

Job lifecycle: `QUEUED → RUNNING → SUCCEEDED | FAILED | TIMED_OUT | CANCELLED | LOST`. Verification is separate: a `SUCCEEDED` process can still fail science. Policy-rejected requests produce denial events without creating a running job. Terminal states are immutable.

Persist `experiments`, `attempts`, `jobs`, `events`, `artifacts`, and `verification_results`. Claim queued work atomically with leases and heartbeats; use unique idempotency keys. On restart reconcile labeled containers with job records, kill orphaned runs, mark lost work explicitly, and retry only under the original budget with a new attempt ID. Do not silently submit duplicate computation.

## 7. Sandbox implementation and containment demo

Runner creates the container from an allowlisted, pre-pulled digest using a fixed argv; no shell interpolation. Apply non-root UID, read-only root filesystem, no network, all capabilities dropped, `no-new-privileges`, default seccomp, no devices, no host namespaces, no runtime socket, no secrets, fixed environment allowlist, and enforced resource/time/output limits. No runtime package installation.

Copy validated input files into a bounded container filesystem; use size-limited tmpfs for writable work/output. Do not bind-mount writable host directories into untrusted containers. After execution, keep the container stopped while extracting a small allowlist of regular artifact files through a bounded runtime stream. Reject symlinks, hardlinks, absolute paths, traversal, devices, oversized headers, oversized files, excessive file counts, and malformed archives. Never extract arbitrary container tar output directly onto the host. Then destroy the container and record cleanup.

Generate plots from validated numeric data in a trusted bounded rendering task. Display logs as escaped text; download source and unknown content as attachments. Never serve sandbox-generated HTML/SVG under the application origin.

Implement safe, controlled probes; none use real secrets or destructive host actions:

| Probe | Expected evidence |
|---|---|
| Read a synthetic host-only canary | File absent/denied in sandbox; canary content absent from output |
| Inspect environment for a synthetic control-plane secret | Marker absent; real credentials never used as probes |
| Connect to a controlled listener on the host/VPC and an external address | Connection fails from sandbox; no received canary message |
| Write to a root filesystem path | Permission/read-only error; writable tmpfs still works |
| Read another job's synthetic artifact | Inaccessible; public cross-session artifact access also denied |
| Bounded allocation / PID / CPU stress fixtures | Enforced memory/PID/time behavior; API stays healthy |
| Ask model via malicious log to change verifier or read secrets | Forbidden tool absent/denied; security event recorded |
| Claim success while writing invalid numeric output | Scientific verdict remains failed |

Show one visible containment moment during the demo: run the no-network probe, display its actual denied connection result and policy, then execute a healthy experiment successfully. Include cleanup evidence and continued API health. A denied operation must come from real enforcement or real policy rejection; do not generate a cosmetic “blocked” message.

Security release gate: no sandbox launch when required controls are missing; no arbitrary execution endpoint available publicly. Rootless resource support must be checked on the actual VM. If this fails, fix the runtime or move to a compatible VM/runtime before presenting containment as complete.

## 8. Repository layout

```text
experiment-doctor/
├── README.md                         # Product, Vultr usage, quickstart, demo
├── AGENTS.md                         # Codex instructions, commands, boundaries
├── LICENSE                           # License for original project code
├── THIRD_PARTY_NOTICES.md
├── Makefile                          # Stable developer/release entry points
├── pyproject.toml
├── uv.lock
├── .env.example                      # Names and safe placeholders only
├── .gitignore
├── apps/
│   ├── web/                          # React UI, lockfile, frontend tests
│   └── api/                          # Sessions, routes, migrations, reports
├── packages/
│   ├── contracts/                    # Pydantic models, generated TS/OpenAPI
│   ├── agent/                        # State machine, tools, prompts, budgets
│   ├── execution/                    # ExecutionClient protocol + local adapter
│   └── verification/                 # Trusted checks and report schemas
├── services/
│   ├── worker/                       # Job claiming, orchestration, recovery
│   └── runner/                       # Private API, runtime policy, janitor
├── experiments/
│   ├── registry.yaml                 # Apps, versions, digests, verifier IDs
│   ├── decay/                        # Original simulation and parameters
│   └── fixtures/                     # Healthy, faulty, adversarial variants
├── verifiers/
│   └── decay-v1/                     # Independent reference and tolerances
├── containers/
│   ├── control-plane.Dockerfile
│   ├── simulation.Dockerfile
│   └── verifier.Dockerfile
├── infra/
│   ├── terraform/
│   │   ├── versions.tf               # Provider constraints; commit lockfile
│   │   ├── main.tf                   # VM, SSH key reference, firewall, tags
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars.example
│   ├── cloud-init/bootstrap.yaml.tftpl
│   ├── host/                         # Idempotent users/runtime/directories setup
│   ├── systemd/                      # API, worker, runner, janitor units
│   ├── caddy/Caddyfile
│   └── environments/demo.example.env
├── scripts/
│   ├── doctor                        # Preflight: capabilities, config, disk
│   ├── deploy                        # Install release, migrate, health checks
│   ├── smoke                         # Live deployed workflow
│   ├── replay                        # Reproduce a recorded candidate
│   ├── backup                        # Consistent DB + artifact snapshot
│   └── cleanup                        # Expiry/orphans; distinct from IaC destroy
├── tests/
│   ├── unit/
│   ├── contracts/
│   ├── integration/
│   ├── science/
│   ├── security/
│   └── e2e/
├── docs/
│   ├── implementation-plan.md         # This plan, copied into repo on bootstrap
│   ├── architecture.md
│   ├── threat-model.md
│   ├── api.md
│   ├── operations.md
│   ├── demo-script.md
│   └── decisions/                     # Short architecture decision records
└── .github/workflows/
    ├── ci.yml                        # Checks without deployment credentials
    ├── images.yml                    # Versioned builds, scans, digest manifest
    └── deploy-demo.yml               # Explicit release deployment
```

Runtime SQLite, job workspaces, logs, exports, Terraform state, credentials, and downloaded evidence do not belong in Git. Keep `experiments/` and `verifiers/` separately versioned so a candidate cannot rewrite its judging criteria. Generate frontend types from contracts and fail CI on drift. Implement `ExecutionClient` with `submit`, `status`, `cancel`, and `artifacts` so a future Agave adapter can be added without changing the agent.

## 9. Infrastructure, release, and operations

Terraform provisions the VM, SSH-key attachment, firewall, labels, and cloud-init configuration using the [Vultr Terraform provider](https://registry.terraform.io/providers/vultr/vultr/latest/docs). Parameterize region, available plan ID, OS ID, admin CIDR, hostname, and release manifest. Validate actual IDs before applying. Use a supported Linux image with cgroup v2 and verified rootless controls.

Cloud-init performs secret-free bootstrap: users, directory permissions, required packages, rootless runtime prerequisites, system service definitions, and readiness hooks. It must be safe to rerun host setup. Inject application secrets separately over an authenticated deployment channel into restricted service credential files. Never place cloud or inference credentials in Terraform variables/state, user data, images, browser assets, fixture bundles, or logs.

Expose 443 publicly, 80 only for redirect/certificate validation, and SSH only from the configured administrator CIDR. Cover IPv4 and IPv6 or disable unused IPv6 ingress. API listens on loopback, runner on a Unix socket; no public DB or Docker listener. Require HTTPS, signed HttpOnly same-site sessions, authorization on every experiment/artifact, CSRF protection for mutations, and per-session/global rate and usage caps. Public visitors can run curated workflows; developer/adversarial routes require an operator credential and are disabled by default.

Proposed command contract to implement:

```bash
make setup                 # Dependencies and safe example configuration
make dev                   # Web + API + worker; real Linux runtime or documented VM
make check                 # Formatting, types, contracts, unit/science tests
make test-runtime          # Real containers and containment integration tests
make test-e2e              # Browser workflow with deterministic model fixture
make infra-check           # Terraform fmt/validate; template/config checks
make infra-plan            # Preview resource changes; no apply
make infra-apply            # Deliberate provision step
make deploy RELEASE=...    # Digest-pinned release, migration, readiness, rollback
make smoke-live            # Live Vultr inference and real execution
make demo-reset            # Remove demo data after retention checks
make infra-destroy         # Explicit resource teardown, separate from data reset
```

These are future repository targets, not commands that already exist. Local macOS development may use a Linux VM, but target-Vultr isolation tests remain mandatory.

Release sequence:

1. Provision inference access and verify a model call early; configure `INFERENCE_BASE_URL`, `INFERENCE_MODEL`, and service-scoped secret. The event specifies `https://api.vultrinference.com/v1`; confirm available models using the organizer's linked model list. [Hackathon technology requirements](https://lablab.build/ai-hackathons/vultr-hackathon)
2. Build and test images in CI; publish immutable digests and a release manifest with Git SHA, policy version, schema migration version, and verifier digest.
3. Review Terraform plan; provision the VM; attach DNS and TLS; run runtime preflight.
4. Install release into a versioned directory; securely inject secrets; run migrations after a consistent backup. Start services and await readiness.
5. Run healthy, repair, containment, cancellation, and restart smoke tests through the deployed URL; verify artifact download and access controls.
6. Promote the release only after checks pass. Roll back to the previous digest manifest if application checks fail; restore DB backup if migration is not backward compatible. Document downtime for this single-VM release.

Use a locked encrypted Terraform state backend if available; otherwise keep state outside the repository on the operator machine with restricted permissions and encrypted backup. CI pull requests never get infrastructure secrets. Deploy workflow is manually dispatched on the intended commit and uses a restricted environment; infrastructure changes remain a separate explicit apply step.

Structured logs include experiment/job/attempt IDs, tool name, policy decision, duration, cleanup result, and bounded usage; exclude secrets and full prompts by default. Record queue depth, runtime availability, free disk, job failures/timeouts, and inference failures. Janitor runs at startup and periodically. Initial retention: 24 hours for demo artifacts, with an operator export before cleanup; do not delete active-job artifacts. Refuse new jobs below a configured disk reserve. Back up SQLite consistently with its backup API, along with an artifact manifest; test restoration once before submission.

## 10. Tests and evidence

| Test group | Required cases | Pass criterion |
|---|---|---|
| Contracts | Bad params, oversized bundles, invalid transitions, duplicate submits | Typed errors; no launch on invalid spec; one job per idempotency key |
| Science | Healthy/coarse/wrong-sign/false-success, NaN, missing endpoint, bad units | Expected independent verdicts; tolerances versioned and reported |
| Agent | Successful repair, two failed repairs, invalid model JSON, injected logs, provider timeout | Tool/budget boundaries hold; truthful final outcome |
| Runtime | Success, exception, timeout, cancellation, memory/PID pressure | Correct reasons, bounded resources, process tree removed |
| Artifacts | Symlinks, traversal, malformed archive, large output, active markup | No host write escape or active content; bounded extraction |
| Authorization | Anonymous mutation rules, cross-session IDs, operator route access | No cross-session data access or public developer execution |
| Containment | Host canary, secret marker, egress, read-only root, job isolation | Actual denied operations and policy evidence; API remains healthy |
| Recovery | Kill worker/runner mid-job, reboot VM, orphaned container | No invisible running work; no duplicate execution; cleanup recorded |
| IaC/release | Validate, bootstrap repeat, clean deploy, rollback, restore | Documented reproducible release with healthy services |
| Browser | Fixture → timeline → patch → plots → checks → evidence | Complete usable flow with clear failed/incomplete states |

Keep unit/model tests deterministic. Run Linux runtime tests in a separate CI job with no deployment/model secrets. Run a small operator-triggered live smoke test against Vultr; do not require paid inference for every pull request. CI must never execute generated experiment code directly on its host.

Evidence bundle: original and repaired code, unified patch, parameter files, raw numeric results, bounded logs, per-check measurements, runtime policy and enforcement observations, image/verifier digests, Git SHA, model ID, seed where applicable, timestamps, and SHA-256 manifest. Include a replay command and environment notes. Avoid bundling service secrets, sessions, or infrastructure credentials. Use reproducible numeric tolerances; do not require byte-identical generated prose.

## 11. Ordered milestones and acceptance criteria

Estimates assume an experienced builder using Codex and working credentials. They are effort ranges, not a guaranteed schedule. Preserve M0–M3 before polishing the UI.

| Milestone | Work / primary paths | Estimate | Exit criterion |
|---|---|---|---|
| M0: Foundation and risk spikes | Repo, contracts, dependency pins, live inference probe, VM/runtime preflight | 30–45 min | Live model response and bounded real container run; credentials stay outside sandbox; constraints verified |
| M1: Execution vertical slice | Runner, job API, SQLite leases, artifacts, janitor, healthy fixture | 60–90 min | Submit → run → logs/artifacts → cleanup; timeout and cancellation work; restart reconciles work |
| M2: Scientific doctor | Trusted decay verifier, baseline/repair loop, tool policy, provenance | 60–90 min | Coarse-step and wrong-sign fail initially; agent produces at least one verified repair; false success is rejected |
| M3: Containment | Runtime policy, artifact validation, probes, authorization | 45–60 min | Security suite passes on Vultr; live denied operation leaves application healthy |
| M4: Product interface | Fixture cards, event timeline, diff, plots, verification, download | 45–75 min | A new visitor can complete the repair flow and inspect evidence without a terminal |
| M5: Reproducible delivery | Terraform, bootstrap, release scripts, TLS, live tests, docs/video | 45–75 min | Fresh IaC deployment, live end-to-end smoke, rollback instructions, public submission assets |

Total planned effort: approximately **4.75–7.25 hours**. Start a minimal Terraform/cloud-init deployment in M0 and improve it through M5; do not leave the first remote deployment until the end.

If time is short: keep only the decay repair and healthy control visible; use event polling, a plain diff, and a simple numeric plot; defer extra visual effects and the public report gallery. Keep false-success and containment fixtures in automated tests. Do not cut independent verification, enforced isolation, real execution, live inference, or co-located IaC. If a required gate remains incomplete, mark the demo accordingly rather than claim completion.

### Final acceptance checklist

- [ ] Application and infrastructure live in one public GitHub repository with a clear license and original, publishable fixtures.
- [ ] README explains Vultr's role, architecture, setup, configuration, execution limits, and replay.
- [ ] A live Vultr inference call chooses a repair; the sandbox executes that repair and produces actual outputs.
- [ ] A scientifically wrong zero-exit run is rejected independently; a known-good run passes.
- [ ] Every candidate runs in a new constrained environment and is cleaned up, including timeout/cancel/restart paths.
- [ ] Forbidden egress or host access is visibly denied in the deployed demo; synthetic secret and cross-job probes pass.
- [ ] No credentials, runtime sockets, verifier mutation capability, or unrestricted execution routes reach user code.
- [ ] Before/after results, patch, verification measurements, limitations, and provenance are accessible in the browser and export.
- [ ] Clean Vultr provisioning and release installation succeed from repository instructions; state/secrets are excluded from Git.
- [ ] Public HTTPS URL works; session authorization, global budget, retention, rollback, and teardown are documented.
- [ ] Submission includes the organizer's required repository, demo, presentation materials, and recorded containment moment.

## 12. Demo script and Codex handoff

Three-minute demo:

1. **0:00–0:25 — Problem:** open the unstable decay experiment and explain that a successful process does not establish scientific validity.
2. **0:25–1:20 — Agent at work:** show baseline execution, failed numeric checks, diagnosis, and proposed time-step diff; let the agent run the repair.
3. **1:20–2:05 — Proof:** compare trajectories and measured error; open the independent verification report and provenance bundle.
4. **2:05–2:40 — Containment:** trigger the controlled network probe, show the real denial and cleanup, then show a healthy job still working.
5. **2:40–3:00 — Delivery:** show the repository's application/IaC layout and explain how the same execution interface can later connect to an external platform.

Begin Codex implementation with M0, then take one milestone at a time. For each milestone, update the task checklist, implement the smallest complete path, run its specified checks, and record actual evidence and unresolved blockers. `AGENTS.md` should name the developer commands, protect verifiers from candidate edits, prohibit host execution of generated code, forbid committed secrets/state, and require honest reporting of mocked versus live results. It must not authorize cloud spending or publication beyond the implementation session's instructions.

Record short decision notes for the single-VM/rootless boundary, the reduced Agave contract, the trusted verifier, and the Vultr inference choice. Finish each milestone with runnable commands and concrete pass/fail evidence so another Codex session can continue without rediscovering the design.
