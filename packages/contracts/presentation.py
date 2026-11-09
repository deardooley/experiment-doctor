"""Read-only browser contracts; scientific verdicts remain verifier-owned."""
from typing import Literal
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, JobResult, Parameters
from packages.verification.contracts import VerificationResult

FixtureId = Literal['decay-healthy', 'decay-coarse-step', 'decay-wrong-sign']
Outcome = Literal['QUEUED', 'RUNNING', 'VERIFIED_REPAIR', 'VERIFIED_HEALTHY', 'NOT_REPAIRED',
                  'UNVERIFIED', 'BLOCKED', 'INCOMPLETE', 'CANCELLED', 'CONTAINED', 'NOT_CONTAINED']


class SessionView(Contract):
    csrf_token: str
    expires_at: float


class AppView(Contract):
    id: FixtureId
    version: str
    verifier_version: str
    input_schema: dict


class ArtifactView(Contract):
    id: UUID
    name: str
    label: str
    size: int = Field(ge=0, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class JobView(Contract):
    job_id: UUID
    role: Literal['primary', 'refinement', 'held_out', 'verification']
    execution: JobResult
    artifacts: list[ArtifactView]


class AttemptView(Contract):
    revision: int = Field(ge=0, le=2)
    parameters: Parameters
    source: str = Field(max_length=32768)
    jobs: list[JobView] = Field(max_length=4)
    verification: VerificationResult | None = None


class ProvenanceView(Contract):
    model_id: str | None = None
    mode: str | None = None
    model_calls: int | None = None
    jobs_used: int | None = None
    model_usage: list[dict[str, int]] = Field(default_factory=list)
    git_sha: str | None = None
    working_tree_dirty: bool | None = None
    simulation_image: str | None = None
    verifier_image: str | None = None
    spec_hash: str | None = None
    verifier_hash: str | None = None
    runtime_policy: str | None = None
    elapsed_seconds: float | None = None


class ConnectionView(Contract):
    target: str
    connected: bool
    errno: int | None = None


class ContainmentView(Contract):
    connections: list[ConnectionView]
    positive_control: bool
    messages_received: int = Field(ge=0)
    cleanup: str
    runner_healthy_after: bool


class ReportView(Contract):
    outcome: Outcome
    evidence_expired: bool = False
    error: str | None = None
    hypothesis: str | None = None
    patch: str = ''
    attempts: list[AttemptView] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list)
    provenance: ProvenanceView = Field(default_factory=ProvenanceView)
    containment: ContainmentView | None = None


class ExperimentView(Contract):
    experiment_id: UUID
    fixture_id: str
    kind: str
    status: Outcome
    created_at: float
    ended_at: float | None = None
    cancel_requested: bool
    report: ReportView | None = None
    artifacts: list[ArtifactView]


class ExperimentSummary(Contract):
    experiment_id: UUID
    fixture_id: str
    kind: str
    status: Outcome
    created_at: float


class EventView(Contract):
    cursor: int
    at: float
    kind: str
    data: dict


class BrowserContracts(Contract):
    session: SessionView
    app: AppView
    experiment: ExperimentView
    summary: ExperimentSummary
    event: EventView
