"""Remove other services' credential variables by re-exec before service startup."""
import os
import sys

CREDENTIALS = frozenset({"VULTR_API_KEY", "INFERENCE_API_KEY", "API_SESSION_KEY", "API_OPERATOR_TOKEN"})


def isolate_environment(module, allowed):
    unexpected = CREDENTIALS.difference(allowed).intersection(os.environ)
    if unexpected:
        clean = {key: value for key, value in os.environ.items() if key not in unexpected}
        os.execve(sys.executable, [sys.executable, "-m", module, *sys.argv[1:]], clean)
