"""Transport-independent execution boundary."""
from typing import Protocol
from uuid import UUID

from . import JobResult, JobSpec


class ExecutionClient(Protocol):
    async def submit(self, spec: JobSpec) -> UUID: ...

    async def status(self, job_id: UUID) -> JobResult: ...

    async def cancel(self, job_id: UUID) -> JobResult: ...

    async def artifacts(self, job_id: UUID) -> tuple[UUID, ...]: ...
