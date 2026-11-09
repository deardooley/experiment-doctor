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

M1 execution evidence follows below. Dallas dev/test provisioning remains authorized within the remaining $15 total budget. Follow docs/dev-vm.md to recreate an ephemeral host when needed.

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

## M1 — execution vertical slice (2026-11-08)

Status: **M1 complete.** The original healthy decay fixture runs in a fresh constrained container through a private job API, produces bounded logs and hash-bound artifacts, and is cleaned up. Timeout, cancellation, OOM, worker death and runner restart were exercised against the real Dallas rootless daemon. No model-generated code executed on the host. Scientific verification remains M2.

- [x] Private Unix-socket API and asynchronous ExecutionClient adapter implement submit, status, cancel and artifacts, plus cursor events and readiness/liveness. Socket permissions are explicitly 0660; no TCP execution listener is offered.
- [x] Runner independently validates immutable image/bundle allowlists and typed parameters. API bodies, queue size, disk reserve, process deadlines, streams and artifacts are bounded. Duplicate identical submissions reuse one job; mismatched reuse returns 409.
- [x] Runner-owned SQLite WAL journal includes versioned schema, atomic claims, owner leases/heartbeats, cancellation requests, timestamps, reason codes, terminal states, events and artifact manifests. This is separate from the future application DB.
- [x] Singleton supervisor reconciles labeled orphan containers before readiness, marks interrupted work LOST without retry, preserves queued work, periodically cleans orphans/expired terminal artifacts, and fails closed after cleanup failure.
- [x] One fresh sandbox per job: rootless runtime, init process, non-root UID, no network/capabilities, read-only root, cleared environment, bounded tmpfs, CPU/memory/PID controls, no runtime package installs and no host bind mounts. No container is reused.
- [x] Fixed in-container exporter streams bounded regular numeric artifacts; host validation rejects unsafe paths, links, extra files, oversized or malformed archives. Opaque artifact IDs, fsync, SHA-256, manifest binding and attachment-only downloads protect artifact identity. Logs are drained and capped at 256 KiB per stream; total export cap is 10 MiB.
- [x] Original decay fixture with exact final-time sampling; real output initial/endpoint, hashes and continued execution after cancellation were checked. Execution success is not labeled a scientific pass.
- [x] 21 local deterministic tests pass; eight opt-in runtime cases are skipped locally and **all eight pass on the Dallas VM**. Ruff passes. The runtime suite includes actual Unix-socket requests and a killed-and-restarted runner preserving queued work without duplicate execution.
- [x] Runtime CI workflow added as manual dispatch with no deployment/inference secrets; developer guide, systemd template and stable Make targets added. The GitHub workflow itself has not been dispatched; equivalent commands ran on Vultr.

Evidence: [m1-dallas-runtime-tests.txt](evidence/m1-dallas-runtime-tests.txt), eight passed in 69.16 seconds, Linux Python 3.12.3. The final host check found no remaining containers. Rootless preflight runs before the runtime suite and each actual runner startup. Local tests used Python 3.12.11 and fixed fake data, never host execution of candidate fixtures.

Implementation notes: a per-job keeper plus Docker init preserves tmpfs until output is captured. Real tests showed Docker archive-copy omits tmpfs contents, so collection uses a fixed bounded exec exporter rather than a host mount or Docker cp. Sandbox output is still untrusted and can change during capture; host-captured bytes are immutable/hash-bound and must later pass the independent verifier. Uvicorn's default socket chmod was also caught by the real test; the server now binds the private socket itself.

Scope remaining: M2 adds the trusted verifier, model/control worker, repair policy, attempts and scientific reports. M3 completes containment/authorization probes. Versioned deployment and system-service installation are M5; the supplied unit is a template, not a claimed deployed application.

M2 scientific-doctor evidence follows below.

M1 teardown: all six Terraform resources destroyed; Vultr instance lookup returned HTTP 404 at `2026-11-08T22:02:11Z`. No dev VM remains running. This session used under one hour at $0.014/hour; conservative compute estimate is $0.014, pending final billing. Combined M0+M1 estimate is $0.028, leaving approximately $14.972 of the authorized $15 total.

## M2 — Scientific doctor (2026-11-08)

Status: **M2 complete.** Live Vultr proposals repaired both coarse-step and wrong-sign decay fixtures. Each original run exited successfully but failed independent scientific checks; each repaired candidate passed primary, dt/2 refinement and held-out k=0.5 checks in a separate trusted verifier container. The false-success fixture exited zero and printed self-attestation but was independently rejected.

- [x] Versioned independent decay spec and stdlib-only checker, separate trusted verifier image, bounded numeric parsing, units/header/grid/finite-value checks, initial/endpoint/shape checks, analytic accuracy, refinement convergence and held-out parameters. Missing evidence fails explicitly; unknown specs are UNVERIFIED.
- [x] Runner resolves evidence by immutable job IDs with experiment/attempt ownership, parameters, source and output hashes. Verifier containers receive numeric data only, never candidate code. Result schema/hashes/bindings are validated outside the sandbox; a pass requires all 22 declared independent checks.
- [x] Explicit bounded intake/baseline/diagnose/authorize/rerun/decide/report workflow. At most baseline plus two repairs, twelve jobs, five model calls, 30-second provider timeout, 2048 completion tokens per call and 180-second diagnosis. Auxiliary simulations are skipped for invalid primary evidence, with an actual failing verifier result still obtained.
- [x] Deterministic patch policy permits only simulation.py and dt. It protects the equation, k/x0/t_end, verifier/reference/tolerances, runtime, images and tools. No shell/host/infrastructure tool is exposed. All generated code executes only in ordinary constrained runner sandboxes.
- [x] Live Vultr JSON-object proposals with strict schema validation, bounded response streams and token usage; no scripted production fallback or hidden retry. Provider/schema/configuration failure yields INCOMPLETE while retaining actual completed evidence. Policy denial yields BLOCKED.
- [x] Separate control-plane SQLite journal, immutable original/candidate source snapshots, source/parameter diff, model hypothesis/evidence keys, before/after measurements, job/artifact manifests, runtime/image/spec/checker/Git provenance and deterministic typed reports. Full generated artifacts stay under ignored runtime directories.
- [x] CLI, healthy/coarse/wrong-sign/false-success registry, build/diagnose commands, verifier-only mode, documentation and runtime CI updated. A local archive of the exact trusted verifier image was preserved before teardown.
- [x] Final local checks: **57 passed**, 12 runtime cases explicitly skipped locally; Ruff and git diff whitespace check pass. Real Dallas regression suite: **12 passed in 138.68 seconds**, including four scientific workflows with a scripted model and the complete eight-case M1 lifecycle/recovery suite. Six saved live verifier outputs were rechecked against their stored hashes and final strict result schema.

### Live outcomes

| Fixture | Baseline execution / science | Final scientific outcome | Max primary absolute error before → after | Live model calls / jobs |
|---|---|---|---|---|
| decay-healthy | SUCCEEDED / PASS | VERIFIED_HEALTHY | 0.00184710 → same | 0 / 4 |
| decay-coarse-step | SUCCEEDED / FAIL | VERIFIED_REPAIR | 2.24326205 → 0.00184710 | 1 / 6 |
| decay-wrong-sign | SUCCEEDED / FAIL | VERIFIED_REPAIR | 144.76603449 → 0.00184710 | 1 / 6 |
| decay-false-success | SUCCEEDED / FAIL | NOT_REPAIRED (verification-only) | 144.76603449 → same | 0 / 2 |

Tolerance is 0.01*x0 (x0=1); repaired passes also include refinement and held-out results. This establishes only the stated model/parameters/tolerances, not general scientific validity.

Evidence: [live metadata summary](evidence/m2-live-summary.json), [actual inference usage](evidence/m2-inference-usage.json), [model capabilities/pricing](evidence/m2-inference-capabilities.json), [real-container regression output](evidence/m2-dallas-runtime-tests.txt). Live model: mimo-v2.6-flash. One earlier trial exhausted its 2048 completion-token budget and was honestly finalized INCOMPLETE; it is included in usage/cost evidence. After checking the provider's documented controls, a new diagnosis used disabled reasoning and JSON-object output and succeeded. The independent JSON proposal path is used; native tool support is not claimed as tested.

Trusted verifier image ID: `sha256:b0012ce97e78ee3c38f4a2bda9a5b90fb8584616bc1e76027c02ec76293686db`. Simulation base: `python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`. The image archive remains private at runtime/dev-vm/m2-verifier-image.tar.gz; archive SHA-256 is `426380df89d2bf898df6a5922cb5862abfb86e13192bebe7c4e61cc54e71c4bc`. Public image releases and a complete replay command remain M5 work.

Teardown: no containers remained at the final host check. All six Terraform resources were destroyed; Vultr instance GET returned HTTP 404 at **2026-11-08T22:26:59Z**. No VM remains running. The session ran under one hour: conservative compute estimate $0.014. Three live inference calls used 2684 prompt and 2693 completion tokens, estimated $0.00094165 from live model pricing. Cumulative tracked M0–M2 estimate is approximately **$0.04294** (plus the small unmetered M0 probe, pending provider invoice), leaving about **$14.957** of the authorized $15 budget.

M3 containment and public authorization evidence follows below. See [scientific doctor operations](scientific-doctor.md) for the M2 numerical workflow.

## M3 — Containment (2026-11-08)

Status: **M3 complete.** The security suite passed on Vultr. Real denied network operations were followed by a verified healthy simulation and continued API readiness. The public API enforces signed sessions, CSRF and ownership; three separate Linux service identities were exercised against the real Unix sockets and data directories. No public production deployment or TLS termination is claimed.

- [x] Public curated API: signed HttpOnly SameSite=Lax sessions, Secure cookies for HTTPS, exact-Origin/CSRF checks, ownership for experiments/events/cancellation/artifacts, opaque IDs, bounded bodies/connections, per-session/global queue caps and usage limits. Foreign/unknown IDs return 404. Forwarding headers are not trusted for rate identity.
- [x] No generic public execution/upload/registration route. Operator probes are disabled by default and require a separate token plus normal session/CSRF checks. The only operator job is a fixed network demonstration; arbitrary source, images and destinations are rejected.
- [x] Separate API, control-worker and runner processes/users/groups. The API cannot reach the runner socket or Docker; the worker reaches only the runner API; the runner alone reaches Docker. Private runner data and synthetic worker credentials were unreadable to the API. Role entry points remove other services' project credentials by re-exec, verified using synthetic wrong-role environment variables.
- [x] Startup **and per-job** enforcement checks: rootless/cgroup-v2/builtin-seccomp availability, actual memory/swap/PID/CPU limits, non-root UID, Seccomp=2, NoNewPrivs=1, CapEff=0, loopback-only network, read-only root and bounded writable tmpfs. Candidate code never executes until these checks pass. Enforcement loss disables readiness/new claims and records a policy event.
- [x] Real host-only/environment/cross-job canaries, read-only writes, writable tmpfs, symlink/hardlink/FIFO/oversize/active-output rejection, bounded log flooding, and real memory/PID/CPU pressure while the API stays responsive. Malformed/traversal archives are rejected without host extraction.
- [x] Real injected logs followed by an explicitly scripted attacker proposal caused an actual deterministic verifier-edit denial and security event. This proves policy enforcement, not live-model immunity; no cosmetic security response or scripted live repair fallback was substituted.
- [x] Separate application queue with atomic claims/caps, cancellation/report consistency, worker leases and persisted submission intents. Lost acceptance responses are recovered by idempotency key; interrupted jobs are cancelled/settled without resubmission, queued work survives and a subsequent healthy job succeeds.
- [x] Integrity-checked attachment-only downloads, no active sandbox content under the API origin, no-store/nosniff/restrictive CSP. Periodic retention removes expired terminal public/private evidence, preserves active work and cleans unpublished blobs. Security audit records are bounded and do not contain credentials/cookies/request bodies.
- [x] Final checks: **82 local tests passed**, 23 runtime cases explicitly skipped locally, Ruff and whitespace checks passed. The complete Vultr regression suite passed **23 cases in 248.37 seconds**. The separate-user loopback HTTP smoke and eleven service-permission/environment observations passed after the suite.

Evidence: [curated containment/authorization/service summary](evidence/m3-containment-summary.json). Raw test logs, smoke downloads, private reports and credential files remain outside Git under ignored runtime paths (or were destroyed with the VM). The integration suite uses actual sandbox jobs with explicitly scripted/verification-only model modes; M3 made zero paid inference calls. M2's actual live Vultr repairs remain the independent live-model evidence.

### Visible containment result

The host listener passed its positive connection control. The sandbox's connection to that listener and to an external address both returned **errno 101 (network unreachable)**; zero probe messages reached the listener. Probe cleanup was recorded as removed. A new healthy experiment then passed all **22** primary/refinement/held-out checks, and the actual API returned ready. A successful TCP connection is never reported as blocked merely because a later send fails.

The actual HTTP smoke observed 401 for anonymous mutations, 403 for CSRF/foreign Origin/missing operator credential, 404 for foreign experiment/cancel/artifact IDs and 404 for the private execution surface. HTTPS cookie flags were checked through ASGI tests; the three-user live smoke intentionally used explicit loopback HTTP development mode, with no public listener or production TLS claim.

### Findings resolved during implementation

The separate-user smoke caught SQLite's default shared-file mode 0640 blocking worker writes. The shared control database is now explicitly 0660 in doctor-control; private diagnosis/runner directories remain 0700. A cursor test initially read only the first 100 events and missed the later healthy event; it now follows ordered pages, with a regression test. Neither fix weakened the security controls.

The trusted verifier image used for M3 was `sha256:7a92039d60938054e91db123b99ad10cb688697ce7a14a551b5668b4ce14fc62`; the simulation base remains the pinned M0/M2 Python digest. Host Docker was 29.9.3 with cgroup v2, builtin seccomp and rootless security options; details are in the curated summary.

Teardown: all service processes were stopped, the dedicated daemon had **zero containers remaining**, and all six Terraform resources were destroyed. Vultr instance lookup returned HTTP 404 at **2026-11-08T23:28:36Z**. No dev VM remains running. This session was under one hour; conservative M3 compute estimate **$0.014**, with no M3 inference charge. Cumulative tracked M0–M3 estimate is approximately **$0.05694** plus the small unmetered M0 inference probe, pending provider billing; roughly **$14.943** remains authorized.

Next milestone: **M4 — Product interface**. Use the existing session bootstrap, CSRF header, owned cursor events, typed reports and attachment routes. Render model/source/log data as escaped text. Production HTTPS, versioned installation and public release operations remain M5. See [security operations](security.md) and [threat model](threat-model.md) for commands and boundaries.

## M4 — Product interface (2026-11-08)

Status: **M4 complete.** A visitor can select a fixture, submit a diagnosis, follow recorded progress, inspect the patch and measured before/after plot, inspect independent measurements and download owned evidence through the browser. Local UI was reviewed in Chrome; desktop/mobile acceptance runs against both explicit edge fixtures and the actual signed-session FastAPI/Doctor/presentation/export path. Production HTTPS delivery remains M5.

- [x] React/TypeScript/Vite workbench with three curated fixture cards, bounded optional task, queue/progress/cancellation, recent owned experiments and URL-based reload recovery.
- [x] Escaped diagnosis and unified diff, original/candidate source, integrity-checked numeric plots with analytical overlay, curve visibility and keyboard time readout. Display-only reference never supplies the scientific verdict.
- [x] Independent per-revision check tables with measurements/tolerances, execution and cleanup details, actual model mode, provenance/hashes and limitations. Failed, blocked, incomplete, cancelled, unavailable and expired evidence states remain explicit.
- [x] Generated read-only browser contracts, with drift checks. New recent/view/ZIP endpoints retain ownership, signed HttpOnly sessions and CSRF mutation protection; no execution/upload/target surface was added.
- [x] Bounded attachment-only evidence ZIP with sources, parameter files, raw numeric results/logs, patch, report, environment/replay notes and SHA-256 manifest; stored size/hash verification, export limits and explicit corrupt/expired errors.
- [x] Frontend CI job and local commands for install, contract generation, unit tests, typecheck/build and isolated browser tests. Commit message: [M4](commits/M4.txt).

Validation: **84 Python tests passed**, **23 Linux/runtime cases skipped locally** (previous real-container M3 evidence remains separate); **2 numeric frontend tests passed**; **14 desktop/mobile browser cases passed**. TypeScript/Vite build, Python/TypeScript contract drift, Ruff and whitespace checks passed. Browser tests use a deterministic model plus fixed numeric execution fixtures and run the trusted checker against those inputs. They never run candidate code on this host and do not establish fresh live inference or sandbox containment. The real API path verified coarse repair and healthy control, all 22 final checks, owned downloads/reload, and foreign-session denial. Edge interception tests explicitly cover UI errors/injection rather than claiming real runtime failures. CI is configured but has not been dispatched on GitHub.

Findings resolved: Chrome review caught the original brand crop including wordmark fragments; its CSS crop was corrected. Browser automation caught a timeline text binding mismatch and a session-rate-limit collision across repeated test sessions. Timeline labels now have explicit text spans, and the actual-API acceptance flow reuses its owning session rather than relaxing production limits. Test services start automatically and stop after acceptance; test-server data is removed on graceful shutdown.

Evidence: [curated interface summary](evidence/m4-interface-summary.json). See [product interface operations](product-interface.md) for the real worker setup and deterministic tests. Raw reports, test traces and downloaded evidence remain ignored/outside Git. No M4 VM was provisioned and no paid inference was used; cumulative tracked cloud cost remains approximately **$0.05694** plus the small unmetered M0 probe, pending provider billing.

Next milestone: **M5 — Reproducible delivery**: production static hosting/TLS, reproducible deployment, release/rollback smoke and public submission assets. M4 does not claim a public deployment.

## M5 — Reproducible delivery (2026-11-08)

Status: **implementation prepared for local review; M5 exit gates remain incomplete.** Per the user's clarified direction, builds stay local, the container preview uses `experiment-doctor.local`, and publication tooling supports Docker Hub locally and GitLab Registry from GitLab CI. Nothing was pushed to a registry or repository. The local preview is explicitly offline and is not substituted for fresh live Vultr execution.

- [x] Digest-addressed control/web/verifier/simulation release images, locked offline wheels, Git/policy/per-database-schema/verifier provenance and SHA-256 archive/manifest verification. Dirty review snapshots are explicit and cannot be promoted.
- [x] Versioned root-owned service installation, separate Linux service identities, secret-free embedded cloud-init setup, loopback API/private runner socket, public HTTPS Caddy configuration and IPv6-disabled firewall. Role-scoped credentials arrive separately over authenticated SSH.
- [x] Prepare bytes before downtime, consistent SQLite/evidence backup before release switch, readiness-based code/image fallback, explicit rollback and a separate reviewed promotion gate. Backup/restore checks cover WAL consolidation, tampering, symlinks, displaced-state preservation and initially empty service directories.
- [x] Explicit registry push and digest-verified pull/re-export. Docker Hub uses flat role repository names; GitLab uses nested project paths. GitLab CI runs only protected refs, with a protected dedicated shell builder and a manual registry-publication job using short-lived registry credentials. No inference/cloud credentials enter builds or CI.
- [x] Read-only, non-root local web container at **http://experiment-doctor.local:8080**, loopback-only publishing, all capabilities dropped and no service secrets/socket mounts. Two actual container browser cases passed, including plotting and evidence ZIP download. The Mac already resolves the hostname; no host-file or certificate-trust setting was changed by this implementation.
- [x] Live HTTPS smoke tooling for healthy/live repair, strict verifier contracts, cleanup, cancellation, ZIP integrity, cross-session denial and optional supervised containment; aggregate operator status output; delivery/recovery documentation and recording/presentation outlines. Provisional commit message: [M5](commits/M5.txt).
- [ ] Fresh Dallas IaC/bootstrap/install, idempotent host rerun and real on-host release validation. Vultr refused API access for the current outbound IP; creation failed before any resource was created. Restored provider access is required.
- [ ] Actual HTTPS/live-inference smoke, rollback/restart/reboot and deployed-data restoration on that fresh host.
- [ ] Reviewed publication/promotion, public demo lifetime, and actual live recording/presentation assets. These remain held for review; local artifacts and outlines are not a public submission.

Validation: **93 Python tests passed**, **23 Linux/runtime cases skipped locally**, **3 frontend numeric/digest tests passed**, **14 desktop/mobile browser regressions passed**, and **2 named-container desktop/mobile cases passed**. TypeScript/Vite build, contract and wheel-requirements drift, Ruff, shell syntax, whitespace, Terraform fmt/validate, rendered cloud-init YAML and GitLab YAML parsing passed. The pinned Caddy configuration validated. A trusted carrier installed its wheels and imported API/control/verifier modules with networking disabled; no candidate code executed on the host. Actual registry credentials/push/pull and the new host installer/rollback remain untested against an external registry/fresh VM.

Findings resolved: the official Caddy binary's low-port file capability prevented execution with every container capability dropped; the local web image now removes that unnecessary file capability and listens on 8080. Named local HTTP origins lack secure-context Web Crypto; a pinned SHA-256 implementation preserves artifact byte/hash checks on that origin, with reference-vector checks and an actual plotted container flow. Restored shared artifacts retain API-group read access; backups consolidate WAL and preserve empty initial directories. Installed reports read immutable release metadata instead of requiring a .git directory on the VM.

Evidence: [local delivery summary](evidence/m5-local-delivery-summary.json), [delivery guide](delivery.md), [submission preparation](submission.md). Private build archives and raw browser traces remain under ignored runtime/test paths. The local preview is left running for review with fixed numeric/model fixtures and a prominent offline label. No M5 cloud spending occurred; cumulative tracked estimate remains approximately **$0.05694** plus the small unmetered M0 inference probe, pending provider billing.

### M5 follow-up — Automated service configuration (2026-11-09)

The manual credential-staging gap is closed. `make deploy` now validates local `.env`/exported settings and stages only api.env, inference.env and web.env over strict-host-key-verified SSH before release upload or shutdown. Exported variables override dotenv values; DEPLOY_ENV_FILE selects another file, or `-` selects environment-only input. The root .env is never sourced or transferred. SSH/SCP child environments exclude project/cloud/registry credentials; role settings travel exclusively through encrypted stdin and never appear in argv or logs.

The root receiver creates the configuration directory with mode 0700, writes owned regular files with mode 0600 using atomic replacements, and restores prior file contents if a later write fails. It rejects symlink/unowned-file targets and respects staging/deployment locks. Missing session keys preserve the existing remote key or generate a 32-byte random key on first staging; ordinary redeployments retain browser sessions. Operator probes remain disabled unless explicitly enabled with a separate strong token. The installer now reads the generated quoted origin correctly for readiness checks.

Validation: **113 Python tests passed**, including **20 synthetic configuration/staging cases**; **23 Linux/runtime cases skipped locally**. Ruff, shell syntax and whitespace checks passed. Coverage includes dotenv filtering and literal parsing, environment precedence, private permissions, session-key preservation/rotation, legacy key quoting, invalid input, role isolation, partial-write rollback, symlink denial, secret redaction and an actual deploy-script invocation against fake SSH/SCP endpoints verifying configure-before-copy-before-install order. No real credentials were transferred, no remote host was changed and no cloud resources were provisioned. Fresh-host SSH/systemd validation remains part of the outstanding M5 deployment gate.
