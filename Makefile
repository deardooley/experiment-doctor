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

.PHONY: api control-worker containment-demo test-security
PUBLIC_ORIGIN ?= https://doctor.example
api:
	uv run --frozen python -m apps.api --root runtime/control --origin "$(PUBLIC_ORIGIN)"
control-worker:
	uv run --frozen --env-file "$(INFERENCE_ENV)" python -m services.control --root runtime/control --socket "$(RUNNER_SOCKET)"
containment-demo:
	uv run --frozen python -m packages.security.demo --socket "$(RUNNER_SOCKET)" --output runtime/security
test-security:
	uv run --frozen pytest tests/security -v
INFERENCE_ENV ?= runtime/inference.env

.PHONY: web-setup web-dev web-contracts web-check web-e2e
web-setup:
	cd apps/web && npm ci --ignore-scripts
web-dev:
	cd apps/web && npm run dev
web-contracts:
	uv run --frozen python -m scripts.export_browser_contracts
	cd apps/web && npm run contracts
web-check:
	uv run --frozen python -m scripts.export_browser_contracts --check
	cd apps/web && npm run contracts:check && npm test && npm run build
web-e2e:
	cd apps/web && npm run test:e2e
