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
	uv run --frozen python -m services.runner --root runtime/runner --socket runtime/runner.sock --image "$(SIMULATION_IMAGE)"
test-runtime:
	ED_RUNTIME_TESTS=1 uv run --frozen pytest tests/integration/test_runtime.py -v
