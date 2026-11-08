# M2 scientific doctor

The doctor runs original code, measures failure against a trusted decay specification, asks a live Vultr model for a bounded repair proposal, authorizes it deterministically, and reruns it in fresh sandboxes. Execution success and scientific validity are separate fields. Supported fixtures are decay-healthy, decay-coarse-step, decay-wrong-sign and decay-false-success.

## Running it

Use a Linux host with the M1 rootless runtime. Pre-pull the pinned simulation image, then build the trusted image separately:

```
make build-verifier
export VERIFIER_IMAGE=$(docker image inspect --format '{{.Id}}' experiment-doctor-verifier:dev)
export SIMULATION_IMAGE=python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
make runner
```

The runner accepts immutable local `sha256:` image IDs for a built verifier, or published repository@sha256 references. It never pulls an image on job submission. The Docker build context explicitly excludes everything except trusted verifier files and Dockerfiles. No experiment/candidate source is copied into the verifier image.

Keep inference configuration only on the control worker, never on the runner or in any sandbox. In another terminal:

```
make diagnose FIXTURE=decay-coarse-step RUNNER_SOCKET=runtime/runner.sock
make diagnose FIXTURE=decay-wrong-sign RUNNER_SOCKET=runtime/runner.sock
```

Without make, load the private .env in the local shell and run `.venv/bin/python -m packages.agent --socket runtime/runner.sock --fixture decay-coarse-step --output runtime/doctor`. The runner needs no model credentials. To use a remote runner, forward only its private Unix socket through SSH; the live M2 checks kept all inference/cloud credentials local.

`--verify-only` executes baseline verification without a model or repair. It needs no inference credential. It exits zero only on verified healthy output; false success returns NOT_REPAIRED and a nonzero CLI status, preserving the actual failed checks. Runtime/operator errors produce INCOMPLETE rather than fabricated repairs.

## Trust and numeric checks

The independently versioned `verifiers/decay-v1/spec.json` declares dx/dt=-k*x, seconds, fixed primary k=1/x0=1/t_end=5, held-out k=0.5 and tolerances. Its SHA-256 and the checker-plus-spec SHA-256 are included in the verifier result. The actual trusted image ID is recorded separately in every report.

Each revision uses one primary simulation. The controller performs only a trusted numeric *screen* to decide whether auxiliary computation is worthwhile. A valid-looking primary receives a dt/2 refinement run and a separate held-out k=0.5 run. The scientific verdict always comes from one fresh trusted verifier container, including when primary screening fails and auxiliaries are skipped.

The verifier accepts only bounded numeric CSV with header t,x. It never imports, evaluates or executes candidate source. It checks finite values, bounded row count, initial value, increasing dt grid, exact endpoint, nonnegativity/nonincrease within 1e-12, maximum analytic error <=0.01*x0, and refinement error no greater than primary error plus 1e-10. Missing auxiliary evidence fails explicitly. Unknown specs produce UNVERIFIED. Self-attestation and simulation logs do not enter verdict computation.

The runner resolves verification inputs from terminal simulation job IDs, checking experiment/attempt ownership before submission and again during input construction. It reads only regular bounded numeric artifacts with matching stored hashes. Each verifier input binds role, job, attempt, source hash, parameters, execution/cleanup state and artifact hash. The controller validates the returned schema, checker/spec hashes, job IDs, source/parameter/output bindings and the consistency of a claimed pass. No candidate-provided verified field can populate VerificationResult.

## Workflow and patch policy

The explicit state machine audits read_experiment, submit_job, get_job, read_artifact, propose_patch, verify_candidate and finalize_report. There is no shell, network, host-file, infrastructure or verifier-edit tool exposed to the model. Only schema-validated proposals enter deterministic authorization. Proposals may replace simulation.py and modify dt; all governing parameters, verifier files, references, runtime settings and image selection are protected. Candidate Python remains untrusted regardless of what it contains and executes only through the runner.

Limits: at most three revisions (baseline plus two repairs), twelve total jobs, five model calls, 2048 completion tokens per call, 30-second provider timeout and 180-second diagnosis deadline. Each revision needs at most three simulation jobs and one verifier job. Patch sources are capped at 32 KiB; dt >=0.001 bounds the verification grid. No automatic provider retries or scripted live fallback are used. An incomplete diagnosis requests cancellation of its active job and retains completed evidence.

The configured model's capabilities were queried live. The selected integration uses JSON-object output plus strict local Proposal validation and disabled reasoning, using the [Vultr Chat Completion API controls](https://api.vultrinference.com/docs/reference/create-chat-completion). Native tools are advertised but are not required or claimed as the live integration path. The initial trial exhausted its response budget; it was recorded as INCOMPLETE. The next independent trial used the bounded JSON controls and completed. There is no hidden retry inside a diagnosis.

## Reports and evidence

A separate control-plane SQLite journal stores experiments, revisions, submitted job specs, tool events, artifact metadata and verification results. The runner never opens it. Original/repaired source, parameter sets, unified source/parameter diff, model hypothesis/evidence keys, raw artifact copies, measured before/after checks, execution statuses, image/spec/checker hashes, Git SHA/dirty flag, model ID/token usage, timestamps and a SHA-256 file manifest are preserved under the experiment UUID. Reports are deterministic server templates validated by a Report schema; model prose never supplies the outcome.

Full reports and generated source remain under ignored runtime/doctor* directories, outside Git. Curated metadata-only live summaries are in docs/evidence/m2-live-summary.json. A local export of the exact built verifier image is retained at runtime/dev-vm/m2-verifier-image.tar.gz; it contains only the trusted image, not credentials. Published image manifests, a full replay command and deployed browser delivery remain later milestones.

These numerical checks establish credibility only for this model, parameters and tolerances. They do not establish general scientific validity. Containers share a kernel, and artifact hashes establish identity rather than correctness. The public session/API authorization and full containment suite remain M3; the private candidate-registration endpoint must never be exposed through the public frontend.

## Verification commands

```
make check
VERIFIER_IMAGE=<actual-built-sha256> SIMULATION_IMAGE=<pinned-reference> make test-runtime
```

Default tests never execute candidate source on the host; workflow tests use explicitly labeled fixed numeric/model fixtures. Opt-in Linux tests run real simulations, a separate trusted verifier and the complete M1 recovery suite, with a scripted model for repeatability. Live model evidence is recorded separately. A manually dispatched runtime CI workflow builds the trusted image and runs these tests without inference/deployment secrets; it has not yet been dispatched on GitHub.
