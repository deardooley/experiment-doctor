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
