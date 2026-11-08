import argparse
import asyncio
import json
from pathlib import Path

from packages.agent.doctor import Doctor
from packages.agent.inference import VerificationOnly, VultrModel
from packages.execution.local import LocalExecutionClient
from packages.security.environment import isolate_environment


async def run(args):
    model = VerificationOnly() if args.verify_only else VultrModel()
    client = LocalExecutionClient(args.socket)
    try:
        report = await Doctor(client, model, args.output).run(args.fixture, repair=not args.verify_only)
        print(json.dumps({key: report[key] for key in (
            "experiment_id", "fixture", "outcome", "model_calls", "jobs_used", "report_path")}))
        return report["outcome"] in ("VERIFIED_HEALTHY", "VERIFIED_REPAIR")
    finally:
        await client.close()


def main():
    isolate_environment("packages.agent", {"INFERENCE_API_KEY"})
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, choices=["decay-healthy", "decay-coarse-step", "decay-wrong-sign", "decay-false-success"])
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("runtime/doctor"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args)) else 1)


if __name__ == "__main__":
    main()
