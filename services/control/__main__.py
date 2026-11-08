import argparse
import asyncio
import os
from pathlib import Path

from packages.agent.inference import VerificationOnly, VultrModel
from packages.execution.local import LocalExecutionClient
from services.control.worker import ControlWorker
from packages.security.environment import isolate_environment


async def run(args):
    client = LocalExecutionClient(args.socket)
    model = VerificationOnly() if args.verify_only else VultrModel()
    try:
        await ControlWorker(args.root.resolve(), client, model).run()
    finally:
        await client.close()


def main():
    isolate_environment("services.control", {"INFERENCE_API_KEY"})
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime/control"))
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true", help="Explicit no-inference development mode")
    args = parser.parse_args()
    os.umask(0o007)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
