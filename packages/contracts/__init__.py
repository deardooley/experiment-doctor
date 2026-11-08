"""Shared wire contracts. Callers cannot select runtime flags, paths, or commands."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Parameters(Contract):
    k: float = Field(default=1, gt=0, le=10)
    x0: float = Field(default=1, gt=0, le=100)
    t_end: Literal[5.0] = 5.0
    dt: float = Field(default=0.01, ge=0.0001, le=2.5)


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


TERMINAL = frozenset(JobStatus) - {JobStatus.QUEUED, JobStatus.RUNNING}


def validate_transition(before: JobStatus, after: JobStatus) -> None:
    allowed = {
        JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.LOST},
        JobStatus.RUNNING: TERMINAL,
    }
    if after not in allowed.get(before, set()):
        raise ValueError(f"invalid job transition: {before} -> {after}")


class JobSpec(Contract):
    schema_version: Literal["1"] = "1"
    experiment_id: UUID
    attempt_id: UUID
    app: Literal["decay"] = "decay"
    app_version: Literal["1"] = "1"
    image_digest: Digest
    bundle_hash: Digest
    parameters: Parameters
    runtime_profile: Literal["sandbox-v1"] = "sandbox-v1"
    kind: Literal["simulation", "verification"] = "simulation"
    verifier_version: Literal["decay-v1"] | None = None
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")

    @model_validator(mode="after")
    def verifier_required(self):
        if (self.kind == "verification") != (self.verifier_version is not None):
            raise ValueError("verifier version required only for verification jobs")
        return self


class JobResult(Contract):
    job_id: UUID
    status: JobStatus
    exit_code: int | None = None
    reason: Literal["SUCCESS", "TIMEOUT", "OOM", "CANCELLED", "POLICY_DENIED", "RUNTIME_ERROR", "LOST"]
    policy_version: Literal["sandbox-v1"] = "sandbox-v1"
    cleanup: Literal["pending", "removed", "failed"]


