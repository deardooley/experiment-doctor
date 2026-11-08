import argparse
import os
from pathlib import Path

import uvicorn

from apps.api.app import APISettings, create_app
from packages.security.environment import isolate_environment


def main():
    isolate_environment("apps.api", {"API_SESSION_KEY", "API_OPERATOR_TOKEN"})
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("runtime/control"))
    parser.add_argument("--origin", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--allow-http-local", action="store_true")
    parser.add_argument("--enable-operator-probes", action="store_true")
    args = parser.parse_args()
    os.umask(0o007)
    settings = APISettings(root=args.root.resolve(), origin=args.origin,
                          session_key=os.environ.get("API_SESSION_KEY", "").encode(),
                          operator_enabled=args.enable_operator_probes,
                          operator_token=os.environ.get("API_OPERATOR_TOKEN", ""),
                          allow_http_local=args.allow_http_local)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False,
                proxy_headers=False, workers=1, limit_concurrency=64, backlog=128)


if __name__ == "__main__":
    main()
