# Repository instructions

Implement one milestone at a time using IMPLEMENTATION_PLAN.md. Record actual checks and blockers in docs/milestones.md.

Commands: `make setup`, `make check`, `make probe-inference`, `make preflight`, `make infra-check`, `make runner`, `make build-verifier`, `make diagnose`, `make test-runtime` (explicit Linux/rootless opt-in; see docs/execution.md and docs/scientific-doctor.md).
Never execute model-generated or candidate Python code on the host. All candidates require fresh constrained sandboxes. Trusted verifiers and their specifications are outside candidate-editable bundles. Never accept candidate self-attestation as a scientific verdict.
Never commit credentials, .env, Terraform state, runtime data, or downloaded evidence. Logs and reports must omit credentials. Distinguish deterministic tests from live inference and real container execution. Fail readiness closed when required runtime controls cannot be proven.
No cloud spending, publication, or deployment is authorized by this file. Obtain explicit operator authorization before provisioning resources.

After completing a milestone, create a git commit message starting with the milestone id and title, followed by a dash list of the high level compelted activities.
