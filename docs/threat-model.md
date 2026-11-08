# Trust boundaries and measured containment

Experiment Doctor accepts only curated scientific fixtures through its public API. Model output, candidate Python, logs and trajectory files remain untrusted. Only deterministic policy authorizes execution and only a separately pinned trusted verifier supplies a scientific verdict.

| Service / identity | Authorized access | Excluded access |
|---|---|---|
| API / doctor-api | Signed sessions, CSRF/ownership, public queue, published attachments | Runner socket, Docker daemon, model/cloud credentials |
| Control worker / doctor-worker | Model credential, application queue, private runner API via doctor-execution group | Docker daemon, runner journal/work directories |
| Runner / doctor-runner | Private runner journal, immutable bundles, dedicated rootless daemon | Model/cloud credentials, control session credentials |
| Simulation container | Its own source/parameters, capped tmpfs and bounded streams | Network, host/job files, secrets, devices, host namespaces, runtime sockets |
| Verifier container | Trusted checker/spec plus hash-bound numeric evidence | Candidate modules, model authority, mutable judging criteria |

The Unix socket is mode 0660 in a restricted directory. The API user is not a member of doctor-execution; the worker can use the runner API but cannot traverse the rootless daemon's private runtime directory. `infra/host/setup-control` prepares these groups and directories without secrets. Service units are templates until M5 release installation.

Public mutations require a signed HttpOnly SameSite=Lax session cookie, exact configured Origin and a per-session CSRF header. HTTPS cookies are Secure. The only HTTP exception is an explicit loopback development flag. Experiments, reports, events, cancellation and artifact downloads all check session ownership; foreign and unknown IDs return 404. Operator routes are disabled by default, require a separate credential plus normal session/CSRF checks, and accept no source, images or destination input.

The public surface has no generic job, bundle, shell, image, upload or arbitrary fixture endpoint. The worker independently checks allowed queue kinds/fixtures before executing. Rate limits do not trust caller-provided forwarding headers. One active experiment per session, ten globally queued/running experiments, request-size/connection limits, daily usage caps and disk reserve checks bound the demo service.

Each execution uses a fresh rootless container with non-root identity, read-only root, no network, all capabilities dropped, no-new-privileges, builtin seccomp, fixed environment and CPU/memory/PID/deadline/storage/output limits. Readiness requires real enforcement probes, including Seccomp=2, NoNewPrivs=1 and CapEff=0 observations. Missing required controls stop startup. No generated code is executed on the host, and no writable host directory is mounted into a candidate.

Artifacts are streamed through a fixed exporter, bounded and validated again outside the container. Symlinks, hardlinks, FIFOs, unexpected/active files, unsafe archive paths, malformed streams, excess sizes and excess counts fail closed. The host never extracts an arbitrary sandbox archive. Downloads verify stored size/hash and use attachments, octet-stream, nosniff, no-store and a restrictive CSP; candidate HTML/SVG is never served as an active page at the application origin.

Restart reconciliation uses persisted submission intents and private idempotency-key lookup, covering a crash after runner acceptance but before job-ID persistence. Interrupted control work is cancelled, settled and marked INCOMPLETE without retry; queued work survives. Terminal state is immutable. Cleanup failures make readiness fail. Retention only removes terminal-job evidence after 24 hours; unpublished orphan blobs are removed between jobs.

Measured probes use only synthetic host canaries and environment markers, a controlled host listener with a positive control, an external connection attempt under no-network policy, read-only writes, cross-job files, bounded resource pressure, unsafe artifacts, and an explicitly scripted malicious-model proposal after real injected logs. The scripted model test proves policy enforcement, not that a live model always ignores prompt injection. The visible containment moment comes from actual denied network operations followed by independently verified healthy computation and continued API health.

Limitations: containers share the host kernel. These controls and observed denials are not a guarantee against kernel exploits or hostile multi-tenant workloads. The single-host demo still requires current host security maintenance. M5 supplies deployed HTTPS/proxy configuration, release installation, backup/restore and operational monitoring; M3's loopback test service is not a public production deployment.
