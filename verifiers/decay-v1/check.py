"""Trusted stdlib-only numeric checker. Never imports/executes candidate source."""
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path

SPEC = json.loads(Path(__file__).with_name("spec.json").read_text())
SPEC_HASH = "sha256:" + hashlib.sha256(Path(__file__).with_name("spec.json").read_bytes()).hexdigest()
VERIFIER_HASH = "sha256:" + hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("spec.json").read_bytes()).hexdigest()
LIMITATION = "Checks cover only the declared decay equation, parameters and numeric tolerances; not general scientific validity."


def check(key, passed, measured=None, tolerance=None, detail=""):
    return {"key": key, "passed": bool(passed), "measured": measured,
            "tolerance": tolerance, "detail": detail}


def trajectory(text, parameters, role):
    checks = []
    try:
        if not isinstance(text, str) or len(text.encode()) > SPEC["max_csv_bytes"]:
            raise ValueError()
        reader = csv.reader(io.StringIO(text))
        if next(reader) != ["t", "x"]:
            raise ValueError()
        rows = []
        for row in reader:
            if len(row) != 2 or len(rows) >= SPEC["max_rows"]:
                raise ValueError()
            pair = tuple(map(float, row))
            if not all(map(math.isfinite, pair)):
                raise ValueError()
            rows.append(pair)
        if len(rows) < 2:
            raise ValueError()
        p = parameters
        if not all(math.isfinite(p[k]) and p[k] > 0 for k in ("k", "x0", "dt", "t_end")):
            raise ValueError()
    except (ValueError, TypeError, KeyError, StopIteration, OverflowError, csv.Error):
        return [check(f"{role}.valid_numeric", False, detail="Missing, malformed, oversized or nonfinite numeric evidence")], None
    checks.append(check(f"{role}.valid_numeric", True))
    stamp = SPEC["timestamp_tolerance"]
    count = math.ceil(p["t_end"] / p["dt"] - 1e-10) + 1
    # Allow one harmless tiny final partial step due to floating point accumulation.
    grid = len(rows) in (count, count + 1) and all(
        abs(t - min(i * p["dt"], p["t_end"])) <= stamp for i, (t, _) in enumerate(rows))
    grid = grid and abs(rows[-1][0] - p["t_end"]) <= stamp
    grid = grid and all(b[0] > a[0] for a, b in zip(rows, rows[1:]))
    checks.append(check(f"{role}.time_grid", grid, tolerance=stamp,
                        detail="Increasing dt grid, initial t=0 and exact endpoint required"))
    checks.append(check(f"{role}.initial_value", abs(rows[0][1] - p["x0"]) <= 1e-12,
                        abs(rows[0][1] - p["x0"]), 1e-12))
    minimum = min(x for _, x in rows)
    growth = max(b[1] - a[1] for a, b in zip(rows, rows[1:]))
    shape = SPEC["shape_tolerance"]
    checks.append(check(f"{role}.nonnegative", minimum >= -shape, minimum, shape))
    checks.append(check(f"{role}.nonincreasing", growth <= shape, growth if math.isfinite(growth) else None, shape))
    try:
        error = max(abs(x - p["x0"] * math.exp(-p["k"] * t)) for t, x in rows)
        if not math.isfinite(error):
            raise ValueError()
    except (ValueError, OverflowError):
        return checks + [check(f"{role}.analytic_error", False, detail="Invalid reference domain")], None
    tolerance = SPEC["absolute_error_fraction"] * p["x0"]
    checks.append(check(f"{role}.analytic_error", error <= tolerance, error, tolerance))
    return checks, error


def verify(payload):
    checks = []
    runs = payload.get("runs", [])
    if payload.get("spec_hash") != SPEC_HASH:
        return {"spec_version": "decay-v1", "spec_hash": SPEC_HASH, "verifier_hash": VERIFIER_HASH, "verdict": "UNVERIFIED",
                "checks": [check("known_spec", False)], "evidence": [], "limitations": [LIMITATION]}
    roles = {run["role"]: run for run in runs}
    if len(roles) != len(runs) or set(roles) - {"primary", "refinement", "held_out"}:
        raise ValueError("invalid evidence roles")
    primary = roles.get("primary")
    errors = {}
    for role in ("primary", "refinement", "held_out"):
        run = roles.get(role)
        if run is None:
            checks.append(check(f"{role}.present", False, detail="Auxiliary evidence missing or skipped after invalid primary"))
            continue
        p = run["parameters"]
        bound = hashlib.sha256(run["csv"].encode()).hexdigest() == run["sha256"]
        bound = bound and (primary is not None and run["bundle_hash"] == primary["bundle_hash"])
        bound = bound and primary is not None and run["attempt_id"] == primary["attempt_id"]
        bound = bound and run["execution_status"] == "SUCCEEDED" and run["cleanup"] == "removed"
        expected = dict(SPEC["parameters"])
        if role == "held_out":
            expected["k"] = SPEC["held_out_k"]
        bound = bound and all(p[k] == value for k, value in expected.items())
        if primary and role != "primary":
            dt = primary["parameters"]["dt"] / (2 if role == "refinement" else 1)
            bound = bound and abs(p["dt"] - dt) <= 1e-15
        checks.append(check(f"{role}.binding", bound, detail="Hash, candidate, attempt and immutable parameter binding"))
        measured, error = trajectory(run["csv"], p, role)
        checks.extend(measured)
        errors[role] = error
    refined = errors.get("refinement")
    coarse = errors.get("primary")
    improvement = refined is not None and coarse is not None and refined <= coarse + SPEC["refinement_slack"]
    checks.append(check("refinement.convergence", improvement, refined,
                        coarse + SPEC["refinement_slack"] if coarse is not None else None))
    return {"spec_version": "decay-v1", "spec_hash": SPEC_HASH, "verifier_hash": VERIFIER_HASH,
            "verdict": "PASS" if all(c["passed"] for c in checks) else "FAIL",
            "checks": checks,
            "evidence": [{k: v for k, v in run.items() if k != "csv"} for run in runs],
            "limitations": [LIMITATION]}


def main():
    payload = json.loads(sys.stdin.buffer.read(2 * 1024 * 1024 + 1))
    result = verify(payload)
    Path("/output/verification.json").write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
