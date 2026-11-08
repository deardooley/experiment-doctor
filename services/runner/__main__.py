"""Run only the private UDS server; no TCP listener option."""
import argparse
import hashlib
import os
import socket
import stat
from pathlib import Path

import uvicorn

from services.runner.api import create_app
from services.runner.runtime import Settings


def serve(settings, socket_path):
    os.umask(0o007)
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.lstat().st_mode):
            raise RuntimeError("socket path is not a socket")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as check:
            try:
                check.connect(str(socket_path))
            except ConnectionRefusedError:
                socket_path.unlink()
            else:
                raise RuntimeError("runner socket is already active")
    # Bind explicitly: Uvicorn's automatic UDS binding may chmod to 0666.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o660)
        listener.listen(128)
        config = uvicorn.Config(create_app(settings), workers=1, access_log=False)
        try:
            uvicorn.Server(config).run(sockets=[listener])
        finally:
            socket_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--scope", default="dev")
    parser.add_argument("--verifier-image")
    args = parser.parse_args()
    code = (Path(__file__).resolve().parents[2] / "experiments/decay/simulation.py").read_bytes()
    settings = Settings(root=args.root.resolve(), image=args.image,
                        bundles={"sha256:" + hashlib.sha256(code).hexdigest(): code}, scope=args.scope,
                        verifier_image=args.verifier_image)
    serve(settings, args.socket.resolve())


if __name__ == "__main__":
    main()
