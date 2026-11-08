"""Live provider probe. Never prints request headers, credentials, or provider error bodies."""
import json
import os
import sys

import httpx
from pydantic import BaseModel, ConfigDict


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


def main():
    base = os.environ.get("INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    model = os.environ.get("INFERENCE_MODEL")
    key = os.environ.get("INFERENCE_API_KEY")
    if base.rstrip("/") != "https://api.vultrinference.com/v1" or not model or not key:
        sys.exit("BLOCKED: set Vultr INFERENCE_MODEL and INFERENCE_API_KEY; use the official HTTPS endpoint")
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            result = client.post(base.rstrip("/") + "/chat/completions", headers={
                "Authorization": f"Bearer {key}",
            }, json={"model": model, "max_tokens": 64, "temperature": 0,
                     "messages": [{"role": "user", "content":
                                   'Return only JSON: {"status":"ok"}'}]})
            if result.status_code != 200:
                sys.exit(f"FAIL: inference HTTP {result.status_code}")
            parsed = Response.model_validate_json(result.json()["choices"][0]["message"]["content"])
            if parsed.status != "ok":
                sys.exit("FAIL: schema-valid response had unexpected status")
        print(json.dumps({"live": True, "model": model, "schema_validated": True,
                          "dispatch": "server-side JSON; native tools not yet tested"}))
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        sys.exit("FAIL: inference transport or response validation failed")


if __name__ == "__main__":
    main()
