"""Actual controlled egress attempt, cleanup, then independently healthy computation."""
import argparse
import asyncio
import hashlib
import json
import secrets
import socket
import time
from pathlib import Path
from uuid import UUID, uuid4

from packages.agent.doctor import Doctor
from packages.agent.inference import VerificationOnly
from packages.contracts import JobSpec, Parameters
from packages.execution.local import LocalExecutionClient
from packages.security.probes import network_source


async def probe_job(client, source, experiment_id=None, event=None):
    config = await client.configuration()
    source_hash = await client.register_candidate(source)
    spec = JobSpec(experiment_id=UUID(experiment_id) if experiment_id else uuid4(), attempt_id=uuid4(),
                   image_digest=config["simulation_image"].split("@")[-1], bundle_hash=source_hash,
                   parameters=Parameters(), idempotency_key="probe-" + str(uuid4()))
    if event:
        event("PROBE_SUBMIT_INTENT", {"idempotency_key": spec.idempotency_key})
    job_id = await client.submit(spec)
    if event:
        event("PROBE_SUBMITTED", {"job_id": str(job_id), "source_hash": source_hash})
    try:
        async with asyncio.timeout(40):
            while True:
                result = await client.status(job_id)
                if result.status not in ("QUEUED", "RUNNING"):
                    break
                await asyncio.sleep(.1)
        items = await client.artifact_manifest(job_id)
        output = b""
        for item in items:
            if item["name"] == "stdout.txt":
                output = await client.read_artifact(UUID(item["id"]))
                if len(output) != item["size"] or hashlib.sha256(output).hexdigest() != item["sha256"]:
                    raise ValueError("probe output integrity failure")
        return {"job_id": str(job_id), "source_hash": source_hash,
                "execution": result.model_dump(mode="json"), "artifacts": items}, output
    except BaseException:
        await asyncio.wait_for(client.cancel(job_id), timeout=5)
        raise


async def network_demo(client, root, experiment_id=None, event=None):
    marker = "ed-network-probe-" + secrets.token_hex(16)
    received = []
    control = asyncio.Event()

    async def listen(reader, writer):
        try:
            raw = await asyncio.wait_for(reader.read(256), timeout=2)
            if raw == b"positive-control":
                control.set()
            if marker.encode() in raw:
                received.append(True)
        finally:
            writer.close()
            await writer.wait_closed()

    # This selects a host interface without sending a UDP packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(("1.1.1.1", 443))
        host = route.getsockname()[0]
    server = await asyncio.start_server(listen, "0.0.0.0", 0)
    port = server.sockets[0].getsockname()[1]
    before = await client.client.get("/health/ready")
    before.raise_for_status()
    async with server:
        _, writer = await asyncio.open_connection(host, port)
        writer.write(b"positive-control")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(control.wait(), timeout=2)
        job, stdout = await probe_job(client, network_source(host, port, marker), experiment_id, event)
        observed = json.loads(stdout)
        connections = observed["connections"]
        blocked = (len(connections) == 2 and {c["target"] for c in connections} == {"host_listener", "external"}
                   and all(c["connected"] is False and isinstance(c["errno"], int) for c in connections)
                   and not received and job["execution"]["status"] == "SUCCEEDED"
                   and job["execution"]["cleanup"] == "removed")
        if event:
            event("CONTAINMENT_DENIED" if blocked else "CONTAINMENT_FAILED", observed)
    healthy = await Doctor(client, VerificationOnly(), root, on_event=event).run(
        "decay-healthy", repair=False, experiment_id=experiment_id)
    after = await client.client.get("/health/ready")
    after.raise_for_status()
    healthy.pop("report_path", None)
    if event:
        event("HEALTHY_AFTER_CONTAINMENT", {"outcome": healthy["outcome"]})
    outcome = "NOT_CONTAINED" if not blocked else "CONTAINED" if healthy["outcome"] == "VERIFIED_HEALTHY" else "INCOMPLETE"
    if healthy["outcome"] == "CANCELLED" and blocked:
        outcome = "CANCELLED"
    return {"schema_version": "1", "kind": "containment", "finished_at": time.time(),
            "outcome": outcome,
            "policy": {"version": "sandbox-v1", "network": "none", "fresh_container_per_job": True},
            "probe": job, "observations": observed, "host_listener_positive_control": control.is_set(),
            "probe_messages_received": len(received), "runner_healthy_before": before.status_code == 200,
            "runner_healthy_after": after.status_code == 200, "following_healthy": healthy,
            "limitations": ["Shared host kernel; this is measured containment, not hostile multi-tenant isolation."]}


async def run(args):
    client = LocalExecutionClient(args.socket)
    try:
        report = await network_demo(client, args.output)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = args.output / ("containment-" + str(uuid4()) + ".json")
        path.write_text(json.dumps(report, indent=2, allow_nan=False))
        print(json.dumps({"outcome": report["outcome"], "observations": report["observations"],
                          "following_healthy": report["following_healthy"]["outcome"],
                          "runner_healthy_after": report["runner_healthy_after"], "report_path": str(path)}))
        return report["outcome"] == "CONTAINED"
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("runtime/security"))
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args)) else 1)


if __name__ == "__main__":
    main()
