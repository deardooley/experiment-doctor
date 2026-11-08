"""Trusted checker import is used only for scheduling and deterministic tests.
Authoritative live verdicts always come from a separate verifier container.
"""
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "verifiers/decay-v1/check.py"
SPEC_PATH = CHECKER.with_name("spec.json")
module_spec = importlib.util.spec_from_file_location("trusted_decay_v1", CHECKER)
checker = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(checker)
SPEC_HASH = checker.SPEC_HASH
VERIFIER_HASH = "sha256:" + hashlib.sha256(CHECKER.read_bytes() + SPEC_PATH.read_bytes()).hexdigest()


def primary_looks_valid(csv, parameters):
    checks, _ = checker.trajectory(csv, parameters, "primary")
    return all(check["passed"] for check in checks)
