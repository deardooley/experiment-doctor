import hashlib
import math

import pytest

from packages.verification.trusted import SPEC_HASH, checker


def csv_for(dt, k=1, sign=-1):
    return "t,x\n" + "".join(f"{min(i*dt,5)},{math.exp(sign*k*min(i*dt,5))}\n"
                              for i in range(math.ceil(5/dt) + 1))


def evidence(role, dt, k=1, csv=None):
    text = csv if csv is not None else csv_for(dt, k)
    return {"role": role, "job_id": role, "attempt_id": "same-attempt",
            "bundle_hash": "sha256:" + "a" * 64,
            "parameters": {"k": k, "x0": 1, "t_end": 5, "dt": dt},
            "csv": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "artifact_id": role + "-artifact", "execution_status": "SUCCEEDED", "cleanup": "removed"}


def valid_payload():
    return {"spec_hash": SPEC_HASH, "runs": [evidence("primary", .01),
            evidence("refinement", .005), evidence("held_out", .01, .5)]}


def test_complete_independent_reference_passes():
    result = checker.verify(valid_payload())
    assert result["verdict"] == "PASS"
    assert all(c["passed"] for c in result["checks"])


@pytest.mark.parametrize("csv", ["t,x\n0,1\n2.5,-1.5\n5,2.25\n", csv_for(.01, sign=1),
                                 "t,x\n0,1\n5,nan\n", "t_ms,x\n0,1\n5,.0067\n",
                                 "t,x\n0,1\n1,.3\n", "t,x\n0,1\n0,.5\n5,.0067\n"])
def test_bad_numeric_and_false_attestation(csv):
    payload = valid_payload()
    payload["verified"] = True
    payload["runs"][0] = evidence("primary", .01, csv=csv)
    assert checker.verify(payload)["verdict"] == "FAIL"


def test_missing_auxiliary_is_never_a_pass():
    payload = valid_payload()
    payload["runs"] = payload["runs"][:1]
    result = checker.verify(payload)
    assert result["verdict"] == "FAIL"
    assert not next(c["passed"] for c in result["checks"] if c["key"] == "refinement.present")


@pytest.mark.parametrize("change", ["hash", "parameters", "candidate", "attempt", "execution", "cleanup"])
def test_evidence_bindings(change):
    payload = valid_payload()
    run = payload["runs"][1]
    if change == "hash":
        run["sha256"] = "0" * 64
    elif change == "parameters":
        run["parameters"]["k"] = 2
    elif change == "candidate":
        run["bundle_hash"] = "sha256:" + "b" * 64
    elif change == "attempt":
        run["attempt_id"] = "other"
    elif change == "execution":
        run["execution_status"] = "FAILED"
    else:
        run["cleanup"] = "failed"
    assert checker.verify(payload)["verdict"] == "FAIL"


def test_unknown_spec_is_unverified():
    payload = valid_payload()
    payload["spec_hash"] = "unknown-equation"
    assert checker.verify(payload)["verdict"] == "UNVERIFIED"


def test_analytic_error_and_refinement_tolerances():
    payload = valid_payload()
    payload["runs"][1] = evidence("refinement", .005,
        csv="t,x\n" + "".join(f"{i*.005},{math.exp(-i*.005) * .999}\n" for i in range(1001)))
    result = checker.verify(payload)
    assert not next(c["passed"] for c in result["checks"] if c["key"] == "refinement.convergence")


def test_typed_result_rejects_empty_or_missing_pass_checks():
    from pydantic import ValidationError
    from packages.verification.contracts import VerificationResult
    payload = checker.verify(valid_payload())
    assert VerificationResult.model_validate(payload).verdict == "PASS"
    payload["checks"] = []
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(payload)
