.PHONY: setup check probe-inference preflight infra-check
setup:
	uv sync --frozen
check:
	uv run --frozen ruff check .
	uv run --frozen pytest
probe-inference:
	uv run --frozen --env-file .env python scripts/probe_inference.py
preflight:
	bash scripts/doctor
infra-check:
	terraform -chdir=infra/terraform fmt -check
	terraform -chdir=infra/terraform init -backend=false
	terraform -chdir=infra/terraform validate

.PHONY: runner test-runtime
runner:
	uv run --frozen python -m services.runner --root runtime/runner --socket runtime/runner.sock --image "$(SIMULATION_IMAGE)" $(if $(VERIFIER_IMAGE),--verifier-image "$(VERIFIER_IMAGE)")
test-runtime:
	ED_RUNTIME_TESTS=1 uv run --frozen pytest tests/integration -v

.PHONY: diagnose build-verifier
FIXTURE ?= decay-coarse-step
RUNNER_SOCKET ?= runtime/runner.sock
diagnose:
	uv run --frozen --env-file .env python -m packages.agent --fixture "$(FIXTURE)" --socket "$(RUNNER_SOCKET)" --output runtime/doctor
build-verifier:
	docker build --pull=false -f containers/verifier.Dockerfile -t experiment-doctor-verifier:dev .
	docker image inspect --format '{{.Id}}' experiment-doctor-verifier:dev
