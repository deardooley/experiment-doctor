"""Operator smoke through the actual public HTTP API. Never prints credentials."""
import argparse
import json
import os
import time
from pathlib import Path

import httpx

from packages.verification.contracts import VerificationResult


def wait(client, experiment_id):
    started = time.monotonic()
    while time.monotonic() - started < 90:
        response = client.get(f"/api/v1/experiments/{experiment_id}")
        response.raise_for_status()
        result = response.json()
        if result["status"] not in ("QUEUED", "RUNNING"):
            return result
        time.sleep(.25)
    raise TimeoutError("public workflow deadline")


def run(origin):
    token = os.environ.get("API_OPERATOR_TOKEN", "")
    if len(token) < 32:
        raise ValueError("operator credential required")
    with httpx.Client(base_url=origin, timeout=10, trust_env=False) as first, httpx.Client(
            base_url=origin, timeout=10, trust_env=False) as other:
        first.get("/health/ready").raise_for_status()
        anonymous = first.post("/api/v1/experiments", json={"fixture_id": "decay-healthy"}).status_code
        assert anonymous == 401
        first_csrf = first.get("/api/v1/session").json()["csrf_token"]
        other_csrf = other.get("/api/v1/session").json()["csrf_token"]
        headers = {"Origin": origin, "X-CSRF-Token": first_csrf}
        csrf_denial = first.post("/api/v1/experiments", json={"fixture_id": "decay-healthy"}).status_code
        foreign_origin = first.post("/api/v1/experiments", headers=headers | {"Origin": "https://untrusted.invalid"},
                                    json={"fixture_id": "decay-healthy"}).status_code
        private_denial = first.post("/execution/v1/bundles", json={"code": "pass"}).status_code
        assert (csrf_denial, foreign_origin, private_denial) == (403, 403, 404)
        submitted = first.post("/api/v1/experiments", headers=headers, json={"fixture_id": "decay-healthy"})
        submitted.raise_for_status()
        experiment_id = submitted.json()["experiment_id"]
        foreign_experiment = other.get(f"/api/v1/experiments/{experiment_id}").status_code
        foreign_cancel = other.post(f"/api/v1/experiments/{experiment_id}/cancel",
                                   headers={"Origin": origin, "X-CSRF-Token": other_csrf}).status_code
        assert foreign_experiment == foreign_cancel == 404
        healthy = wait(first, experiment_id)
        assert healthy["status"] == "VERIFIED_HEALTHY"
        VerificationResult.model_validate(healthy["report"]["attempts"][0]["verification"])
        artifacts = first.get(f"/api/v1/experiments/{experiment_id}/artifacts").json()
        assert artifacts
        foreign_artifact = other.get(f'/api/v1/artifacts/{artifacts[0]["id"]}').status_code
        assert foreign_artifact == 404
        operator_denial = first.post("/api/v1/operator/probes/network", headers=headers).status_code
        assert operator_denial == 403
        submitted = first.post("/api/v1/operator/probes/network", headers=headers | {"Authorization": "Bearer " + token})
        submitted.raise_for_status()
        result = wait(first, submitted.json()["experiment_id"])
        assert result["status"] == "CONTAINED"
        report = result["report"]
        assert report["host_listener_positive_control"] and report["probe_messages_received"] == 0
        assert report["following_healthy"]["outcome"] == "VERIFIED_HEALTHY"
        assert report["probe"]["execution"]["cleanup"] == "removed"
        after = first.get("/health/ready")
        after.raise_for_status()
        return {"transport": "loopback HTTP development mode" if origin.startswith("http:") else "HTTPS",
                "authorization": {"anonymous_mutation": anonymous, "csrf": csrf_denial,
                    "foreign_origin": foreign_origin, "cross_session_experiment": foreign_experiment,
                    "cross_session_cancel": foreign_cancel, "cross_session_artifact": foreign_artifact,
                    "operator_without_token": operator_denial, "private_execution_surface": private_denial},
                "actual_connections": report["observations"]["connections"],
                "listener_positive_control": report["host_listener_positive_control"],
                "probe_messages_received": report["probe_messages_received"],
                "probe_cleanup": report["probe"]["execution"]["cleanup"],
                "probe_job_id": report["probe"]["job_id"], "probe_source_hash": report["probe"]["source_hash"],
                "following_healthy": report["following_healthy"]["outcome"],
                "scientific_checks": len(report["following_healthy"]["attempts"][0]["verification"]["checks"]),
                "api_ready_after": after.json(), "policy": report["policy"],
                "mode": report["following_healthy"]["mode"],
                "model_calls": report["following_healthy"]["model_calls"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.origin)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
