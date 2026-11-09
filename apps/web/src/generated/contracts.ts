/* Generated from packages/contracts/presentation.py. Do not edit. */

export type Id = 'decay-healthy' | 'decay-coarse-step' | 'decay-wrong-sign';
export type VerifierVersion = string;
export type Version = string;
export type At = number;
export type Cursor = number;
export type Kind = string;
export type Id1 = string;
export type Label = string;
export type Name = string;
export type Sha256 = string;
export type Size = number;
export type Artifacts = ArtifactView[];
export type CancelRequested = boolean;
export type CreatedAt = number;
export type EndedAt = number | null;
export type ExperimentId = string;
export type FixtureId = string;
export type Kind1 = string;
/**
 * @maxItems 3
 */
export type Attempts = [] | [AttemptView] | [AttemptView, AttemptView] | [AttemptView, AttemptView, AttemptView];
/**
 * @maxItems 4
 */
export type Jobs =
  [] | [JobView] | [JobView, JobView] | [JobView, JobView, JobView] | [JobView, JobView, JobView, JobView];
export type Artifacts1 = ArtifactView[];
export type ArtifactManifestHash = string | null;
export type Cleanup = 'pending' | 'removed' | 'failed';
export type CreatedAt1 = number | null;
export type EndedAt1 = number | null;
export type ExitCode = number | null;
export type JobId = string;
export type PolicyVersion = 'sandbox-v1';
export type Reason = ('SUCCESS' | 'TIMEOUT' | 'OOM' | 'CANCELLED' | 'POLICY_DENIED' | 'RUNTIME_ERROR' | 'LOST') | null;
export type StartedAt = number | null;
export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'TIMED_OUT' | 'CANCELLED' | 'LOST';
export type JobId1 = string;
export type Role = 'primary' | 'refinement' | 'held_out' | 'verification';
export type Dt = number;
export type K = number;
export type TEnd = 5;
export type X0 = number;
export type Revision = number;
export type Source = string;
export type Detail = string;
export type Key = string;
export type Measured = number | null;
export type Passed = boolean;
export type Tolerance = number | null;
/**
 * @maxItems 40
 */
export type Checks = Check[];
/**
 * @maxItems 3
 */
export type Evidence =
  | []
  | [
      {
        [k: string]: unknown;
      }
    ]
  | [
      {
        [k: string]: unknown;
      },
      {
        [k: string]: unknown;
      }
    ]
  | [
      {
        [k: string]: unknown;
      },
      {
        [k: string]: unknown;
      },
      {
        [k: string]: unknown;
      }
    ];
export type Limitations = string[];
export type SpecHash = string;
export type SpecVersion = 'decay-v1';
export type Verdict = 'PASS' | 'FAIL' | 'UNVERIFIED';
export type VerifierHash = string;
export type Cleanup1 = string;
export type Connected = boolean;
export type Errno = number | null;
export type Target = string;
export type Connections = ConnectionView[];
export type MessagesReceived = number;
export type PositiveControl = boolean;
export type RunnerHealthyAfter = boolean;
export type Error = string | null;
export type EvidenceExpired = boolean;
export type Hypothesis = string | null;
export type Limitations1 = string[];
export type Outcome =
  | 'QUEUED'
  | 'RUNNING'
  | 'VERIFIED_REPAIR'
  | 'VERIFIED_HEALTHY'
  | 'NOT_REPAIRED'
  | 'UNVERIFIED'
  | 'BLOCKED'
  | 'INCOMPLETE'
  | 'CANCELLED'
  | 'CONTAINED'
  | 'NOT_CONTAINED';
export type Patch = string;
export type ElapsedSeconds = number | null;
export type GitSha = string | null;
export type JobsUsed = number | null;
export type Mode = string | null;
export type ModelCalls = number | null;
export type ModelId = string | null;
export type ModelUsage = {
  [k: string]: number;
}[];
export type RuntimePolicy = string | null;
export type SimulationImage = string | null;
export type SpecHash1 = string | null;
export type VerifierHash1 = string | null;
export type VerifierImage = string | null;
export type WorkingTreeDirty = boolean | null;
export type Status =
  | 'QUEUED'
  | 'RUNNING'
  | 'VERIFIED_REPAIR'
  | 'VERIFIED_HEALTHY'
  | 'NOT_REPAIRED'
  | 'UNVERIFIED'
  | 'BLOCKED'
  | 'INCOMPLETE'
  | 'CANCELLED'
  | 'CONTAINED'
  | 'NOT_CONTAINED';
export type CsrfToken = string;
export type ExpiresAt = number;
export type CreatedAt2 = number;
export type ExperimentId1 = string;
export type FixtureId1 = string;
export type Kind2 = string;
export type Status1 =
  | 'QUEUED'
  | 'RUNNING'
  | 'VERIFIED_REPAIR'
  | 'VERIFIED_HEALTHY'
  | 'NOT_REPAIRED'
  | 'UNVERIFIED'
  | 'BLOCKED'
  | 'INCOMPLETE'
  | 'CANCELLED'
  | 'CONTAINED'
  | 'NOT_CONTAINED';

export interface BrowserContracts {
  app: AppView;
  event: EventView;
  experiment: ExperimentView;
  session: SessionView;
  summary: ExperimentSummary;
}
export interface AppView {
  id: Id;
  input_schema: InputSchema;
  verifier_version: VerifierVersion;
  version: Version;
}
export interface InputSchema {
  [k: string]: unknown;
}
export interface EventView {
  at: At;
  cursor: Cursor;
  data: Data;
  kind: Kind;
}
export interface Data {
  [k: string]: unknown;
}
export interface ExperimentView {
  artifacts: Artifacts;
  cancel_requested: CancelRequested;
  created_at: CreatedAt;
  ended_at?: EndedAt;
  experiment_id: ExperimentId;
  fixture_id: FixtureId;
  kind: Kind1;
  report?: ReportView | null;
  status: Status;
}
export interface ArtifactView {
  id: Id1;
  label: Label;
  name: Name;
  sha256: Sha256;
  size: Size;
}
export interface ReportView {
  attempts?: Attempts;
  containment?: ContainmentView | null;
  error?: Error;
  evidence_expired?: EvidenceExpired;
  hypothesis?: Hypothesis;
  limitations?: Limitations1;
  outcome: Outcome;
  patch?: Patch;
  provenance?: ProvenanceView;
}
export interface AttemptView {
  jobs: Jobs;
  parameters: Parameters;
  revision: Revision;
  source: Source;
  verification?: VerificationResult | null;
}
export interface JobView {
  artifacts: Artifacts1;
  execution: JobResult;
  job_id: JobId1;
  role: Role;
}
export interface JobResult {
  artifact_manifest_hash?: ArtifactManifestHash;
  cleanup: Cleanup;
  created_at?: CreatedAt1;
  ended_at?: EndedAt1;
  exit_code?: ExitCode;
  job_id: JobId;
  policy_version?: PolicyVersion;
  reason?: Reason;
  started_at?: StartedAt;
  status: JobStatus;
}
export interface Parameters {
  dt?: Dt;
  k?: K;
  t_end?: TEnd;
  x0?: X0;
}
export interface VerificationResult {
  checks: Checks;
  evidence: Evidence;
  limitations: Limitations;
  spec_hash: SpecHash;
  spec_version: SpecVersion;
  verdict: Verdict;
  verifier_hash: VerifierHash;
}
export interface Check {
  detail?: Detail;
  key: Key;
  measured?: Measured;
  passed: Passed;
  tolerance?: Tolerance;
}
export interface ContainmentView {
  cleanup: Cleanup1;
  connections: Connections;
  messages_received: MessagesReceived;
  positive_control: PositiveControl;
  runner_healthy_after: RunnerHealthyAfter;
}
export interface ConnectionView {
  connected: Connected;
  errno?: Errno;
  target: Target;
}
export interface ProvenanceView {
  elapsed_seconds?: ElapsedSeconds;
  git_sha?: GitSha;
  jobs_used?: JobsUsed;
  mode?: Mode;
  model_calls?: ModelCalls;
  model_id?: ModelId;
  model_usage?: ModelUsage;
  runtime_policy?: RuntimePolicy;
  simulation_image?: SimulationImage;
  spec_hash?: SpecHash1;
  verifier_hash?: VerifierHash1;
  verifier_image?: VerifierImage;
  working_tree_dirty?: WorkingTreeDirty;
}
export interface SessionView {
  csrf_token: CsrfToken;
  expires_at: ExpiresAt;
}
export interface ExperimentSummary {
  created_at: CreatedAt2;
  experiment_id: ExperimentId1;
  fixture_id: FixtureId1;
  kind: Kind2;
  status: Status1;
}
