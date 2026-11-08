"""Real Linux sandboxes with an explicitly scripted model; live inference is separate."""
import asyncio
import multiprocessing
import os

import httpx
import pytest

from packages.agent.doctor import Doctor
from packages.agent.policy import Proposal
from packages.execution.local import LocalExecutionClient
from packages.verification.trusted import ROOT
from services.runner.__main__ import serve
from services.runner.runtime import Settings

pytestmark = pytest.mark.skipif(os.environ.get("ED_RUNTIME_TESTS") != "1" or not os.environ.get("VERIFIER_IMAGE"),
                                reason="requires explicit Linux rootless and built trusted verifier image")


class ScriptedModel:
    mode, model, usage = "offline-integration", "scripted-integration-fixture", []

    async def propose(self, context):
        return Proposal(hypothesis="The measured primary analytic error fails the decay reference",
                        evidence=["primary.analytic_error"], parameters={"dt": .01},
                        files={"simulation.py": (ROOT / "experiments/decay/simulation.py").read_text()})


@pytest.fixture(scope="module")
def socket(tmp_path_factory):
    root = tmp_path_factory.mktemp("m2")
    settings = Settings(root=root / "runner", image=os.environ["SIMULATION_IMAGE"], bundles={},
                        verifier_image=os.environ["VERIFIER_IMAGE"], scope="m2-integration")
    path = root / "runner.sock"
    process = multiprocessing.get_context("spawn").Process(target=serve, args=(settings, path))
    process.start()
    try:
        async def wait():
            client = LocalExecutionClient(path)
            try:
                for _ in range(500):
                    try:
                        if (await client.client.get("/health/ready")).status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    if not process.is_alive():
                        raise AssertionError("runner exited during startup")
                    await asyncio.sleep(.1)
                raise AssertionError("runner never became ready")
            finally:
                await client.close()
        asyncio.run(wait())
        yield path
    finally:
        process.terminate()
        process.join(45)
        if process.is_alive():
            process.kill()
            process.join(5)


@pytest.mark.parametrize("fixture,outcome,jobs", [
    ("decay-healthy", "VERIFIED_HEALTHY", 4),
    ("decay-coarse-step", "VERIFIED_REPAIR", 6),
    ("decay-wrong-sign", "VERIFIED_REPAIR", 6),
    ("decay-false-success", "NOT_REPAIRED", 2)])
def test_real_scientific_workflow(socket, tmp_path, fixture, outcome, jobs):
    async def run():
        client = LocalExecutionClient(socket)
        try:
            report = await Doctor(client, ScriptedModel(), tmp_path).run(
                fixture, repair=fixture != "decay-false-success")
            assert report["outcome"] == outcome
            assert report["jobs_used"] == jobs
            assert report["mode"] == "offline-integration"
            for attempt in report["attempts"]:
                for job in attempt["jobs"]:
                    assert job["execution"]["cleanup"] == "removed"
                    if job["role"] == "verification":
                        assert job["spec"]["image_digest"] == os.environ["VERIFIER_IMAGE"].split("@")[-1]
                assert attempt["verification"]["verdict"] in ("PASS", "FAIL")
            if fixture != "decay-healthy":
                assert report["attempts"][0]["jobs"][0]["execution"]["status"] == "SUCCEEDED"
                assert report["attempts"][0]["verification"]["verdict"] == "FAIL"
            if outcome == "VERIFIED_REPAIR":
                assert report["attempts"][-1]["verification"]["verdict"] == "PASS"
            # A verification request cannot relabel another experiment's evidence.
            if fixture == "decay-healthy":
                original = report["attempts"][0]["jobs"][-1]["spec"]
                original["experiment_id"] = "00000000-0000-0000-0000-000000000001"
                original["idempotency_key"] += "-foreign"
                from packages.contracts import JobSpec
                with pytest.raises(httpx.HTTPStatusError) as denied:
                    await client.submit(JobSpec.model_validate(original))
                assert denied.value.response.status_code == 403
        finally:
            await client.close()
    asyncio.run(run())
