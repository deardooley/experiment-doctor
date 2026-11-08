"""ExecutionClient implementation for the private runner Unix socket."""
from pathlib import Path
from uuid import UUID

import httpx

from packages.contracts import JobResult, JobSpec


class LocalExecutionClient:
    def __init__(self, socket: Path):
        self.client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket)),
                                        base_url="http://runner", timeout=10)

    async def close(self):
        await self.client.aclose()

    async def submit(self, spec: JobSpec) -> UUID:
        response = await self.client.post("/execution/v1/jobs", json=spec.model_dump(mode="json"))
        response.raise_for_status()
        return UUID(response.json()["job_id"])

    async def status(self, job_id: UUID) -> JobResult:
        response = await self.client.get(f"/execution/v1/jobs/{job_id}")
        response.raise_for_status()
        return JobResult.model_validate(response.json())

    async def cancel(self, job_id: UUID) -> JobResult:
        response = await self.client.post(f"/execution/v1/jobs/{job_id}/cancel")
        response.raise_for_status()
        return JobResult.model_validate(response.json())

    async def artifacts(self, job_id: UUID) -> tuple[UUID, ...]:
        response = await self.client.get(f"/execution/v1/jobs/{job_id}/artifacts")
        response.raise_for_status()
        return tuple(UUID(item["id"]) for item in response.json())

    async def read_artifact(self, artifact_id: UUID) -> bytes:
        async with self.client.stream("GET", f"/execution/v1/artifacts/{artifact_id}") as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > 10 * 1024 * 1024:
                    raise ValueError("artifact exceeds client limit")
                data.extend(chunk)
            return bytes(data)
