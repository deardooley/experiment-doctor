"""Deterministic authorization; model replies never select verifier or runtime settings."""
import difflib
import hashlib
import json

from pydantic import Field

from packages.contracts import Contract, Parameters


class PolicyDenied(ValueError):
    pass


class Proposal(Contract):
    hypothesis: str = Field(min_length=1, max_length=2000)
    evidence: tuple[str, ...] = Field(min_length=1, max_length=20)
    files: dict[str, str] = Field(default_factory=dict, max_length=1)
    parameters: dict[str, float] = Field(default_factory=dict, max_length=1)


def authorize(proposal, source, parameters, evidence_ids):
    if set(proposal.files) - {"simulation.py"} or set(proposal.parameters) - {"dt"}:
        raise PolicyDenied("patch touches a forbidden file or governing parameter")
    if not set(proposal.evidence) <= set(evidence_ids):
        raise PolicyDenied("patch references unknown evidence")
    code = proposal.files.get("simulation.py", source)
    if len(code.encode()) > 32768 or "\x00" in code:
        raise PolicyDenied("patch exceeds source policy")
    p = Parameters.model_validate(parameters | proposal.parameters)
    if p.dt < 0.001:
        raise PolicyDenied("patch dt is outside bounded fixture grid")
    if code == source and p.model_dump() == parameters:
        raise PolicyDenied("patch makes no change")
    patch = patch_diff(source, code, parameters, p.model_dump())
    return code, p.model_dump(), patch


def patch_diff(source, code, parameters, candidate):
    patch = "".join(difflib.unified_diff(source.splitlines(True), code.splitlines(True),
                                       fromfile="original/simulation.py", tofile="candidate/simulation.py"))
    before = json.dumps(parameters, sort_keys=True, indent=2) + "\n"
    after = json.dumps(candidate, sort_keys=True, indent=2) + "\n"
    return patch + "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                               fromfile="original/parameters.json", tofile="candidate/parameters.json"))


def bundle_hash(code):
    return "sha256:" + hashlib.sha256(code.encode()).hexdigest()
