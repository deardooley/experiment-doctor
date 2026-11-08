from typing import Literal

from pydantic import Field, model_validator

from packages.contracts import Contract, Digest


class Check(Contract):
    key: str = Field(max_length=100)
    passed: bool
    measured: float | None = None
    tolerance: float | None = None
    detail: str = Field(default="", max_length=500)


class VerificationResult(Contract):
    spec_version: Literal["decay-v1"]
    spec_hash: Digest
    verifier_hash: Digest
    verdict: Literal["PASS", "FAIL", "UNVERIFIED"]
    checks: tuple[Check, ...] = Field(max_length=40)
    evidence: tuple[dict, ...] = Field(max_length=3)
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def complete_pass(self):
        expected = {f"{role}.{key}" for role in ("primary", "refinement", "held_out")
                    for key in ("binding", "valid_numeric", "time_grid", "initial_value",
                                "nonnegative", "nonincreasing", "analytic_error")}
        expected.add("refinement.convergence")
        if self.verdict == "PASS" and (len(self.checks) != len(expected)
                or {check.key for check in self.checks} != expected
                or not all(check.passed for check in self.checks)):
            raise ValueError("scientific pass requires every declared independent check")
        return self
