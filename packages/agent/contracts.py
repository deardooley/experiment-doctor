from typing import Literal

from pydantic import Field

from packages.contracts import Contract


class Report(Contract):
    schema_version: Literal["1"]
    experiment_id: str
    fixture: str
    outcome: Literal["VERIFIED_REPAIR", "VERIFIED_HEALTHY", "NOT_REPAIRED", "UNVERIFIED", "BLOCKED", "INCOMPLETE", "CANCELLED"]
    error: str | None
    attempts: list[dict] = Field(max_length=3)
    events: list[dict]
    hypothesis: str | None
    patch: str
    before_after: dict
    model_id: str
    mode: str
    model_usage: list[dict] = Field(max_length=5)
    model_calls: int = Field(ge=0, le=5)
    jobs_used: int = Field(ge=0, le=12)
    started_at: float
    elapsed_seconds: float
    finished_at: float
    provenance: dict
    limitations: list[str]
    evidence_manifest: dict[str, str]
