"""Bounded state machine. Model supplies proposals; policy and verifier own decisions."""
import asyncio
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4

from packages.agent.inference import InferenceFailure
from packages.agent.contracts import Report
from packages.agent.journal import Journal
from packages.agent.policy import PolicyDenied, authorize, bundle_hash, patch_diff
from packages.contracts import JobSpec, Parameters
from packages.verification.contracts import VerificationResult
from packages.verification.trusted import ROOT, SPEC_HASH, VERIFIER_HASH, primary_looks_valid

LIMITATIONS = ["Checks cover only the declared decay equation, parameters and numeric tolerances; not general scientific validity.",
               "Containers share a host kernel. Artifact hashes establish identity, not correctness."]
TOOLS = frozenset({"read_experiment", "submit_job", "get_job", "read_artifact", "propose_patch",
                   "verify_candidate", "finalize_report"})


class BudgetExceeded(RuntimeError):
    pass


class Doctor:
    def __init__(self, client, model, root: Path, deadline=180, on_event=None):
        self.client, self.model, self.journal = client, model, Journal(root)
        self.deadline = min(deadline, 180)
        self.jobs = self.calls = 0
        self.active = None
        self.attempts = []
        self.events = []
        self.config = None
        self.on_event = on_event
        self.started = time.monotonic()

    def tool(self, name, data):
        if name not in TOOLS:
            raise PolicyDenied("forbidden tool")
        if time.monotonic() - self.started >= self.deadline:
            raise BudgetExceeded("diagnosis deadline")
        event = {"tool": name, **data}
        self.events.append(event)
        self.journal.event(self.experiment_id, "TOOL", event)
        if self.on_event:
            self.on_event("TOOL", event)

    async def simulation(self, code, parameters, role):
        digest = await self.client.register_candidate(code)
        if digest != bundle_hash(code):
            raise ValueError("runner candidate identity mismatch")
        return await self.run_job(JobSpec(
            experiment_id=UUID(self.experiment_id), attempt_id=UUID(self.attempt_id),
            image_digest=self.config["simulation_image"].split("@")[-1],
            bundle_hash=digest, parameters=Parameters.model_validate(parameters),
            idempotency_key=f"{self.attempt_id}-{role}"), role)

    async def run_job(self, spec, role):
        if self.jobs >= 12:
            raise BudgetExceeded("job budget")
        self.tool("submit_job", {"role": role})
        self.jobs += 1
        # Assigned idempotency key is persisted before submission for audit/recovery.
        self.journal.event(self.experiment_id, "SUBMIT", spec.model_dump(mode="json"))
        job_id = await self.client.submit(spec)
        self.active = job_id
        self.journal.job(job_id, self.experiment_id, spec)
        while True:
            self.tool("get_job", {"job_id": str(job_id)})
            result = await self.client.status(job_id)
            if result.status not in ("QUEUED", "RUNNING"):
                break
            await asyncio.sleep(0.1)
        self.active = None
        items = await self.client.artifact_manifest(job_id)
        self.journal.artifacts(job_id, items)
        data = {}
        for item in items:
            self.tool("read_artifact", {"artifact_id": item["id"]})
            raw = await self.client.read_artifact(UUID(item["id"]))
            if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("artifact binding mismatch")
            data[item["name"]] = raw
            path = self.directory / f'{job_id}-{item["id"]}'
            with path.open("xb") as stream:
                stream.write(raw)
        evidence = {"role": role, "job_id": str(job_id), "spec": spec.model_dump(mode="json"),
                    "execution": result.model_dump(mode="json"), "artifacts": items}
        self.current["jobs"].append(evidence)
        return job_id, result, data

    async def verify(self, code, parameters):
        self.tool("verify_candidate", {"attempt_id": self.attempt_id})
        primary, status, data = await self.simulation(code, parameters, "primary")
        inputs = [primary]
        csv = data.get("trajectory.csv", b"").decode(errors="replace")
        if status.status == "SUCCEEDED" and status.cleanup == "removed" and primary_looks_valid(csv, parameters):
            refined = parameters | {"dt": parameters["dt"] / 2}
            held = parameters | {"k": 0.5}
            inputs.append((await self.simulation(code, refined, "refinement"))[0])
            inputs.append((await self.simulation(code, held, "held_out"))[0])
        _, verification_job, outputs = await self.run_job(JobSpec(
            experiment_id=UUID(self.experiment_id), attempt_id=UUID(self.attempt_id),
            image_digest=self.config["verifier_image"].split("@")[-1], bundle_hash=VERIFIER_HASH,
            parameters=Parameters.model_validate(parameters), kind="verification", verifier_version="decay-v1",
            verification_inputs=tuple(inputs), idempotency_key=f"{self.attempt_id}-verify"), "verification")
        if verification_job.status != "SUCCEEDED" or verification_job.cleanup != "removed":
            raise ValueError("trusted verification job did not complete")
        raw = outputs.get("verification.json", b"")
        if len(raw) > 128 * 1024:
            raise ValueError("verifier response limit")
        result = VerificationResult.model_validate_json(raw)
        if result.spec_hash != SPEC_HASH or result.verifier_hash != VERIFIER_HASH:
            raise ValueError("trusted verifier version mismatch")
        if [item["job_id"] for item in result.evidence] != list(map(str, inputs)):
            raise ValueError("verifier evidence identity mismatch")
        for item, expected in zip(result.evidence, self.current["jobs"]):
            csv_artifact = next((a for a in expected["artifacts"] if a["name"] == "trajectory.csv"), None)
            if (item["bundle_hash"] != bundle_hash(code) or item["parameters"] != expected["spec"]["parameters"]
                    or item["attempt_id"] != self.attempt_id
                    or item["sha256"] != (csv_artifact["sha256"] if csv_artifact else hashlib.sha256(b"").hexdigest())):
                raise ValueError("verifier parameter or output binding mismatch")
        if result.verdict == "PASS" and (len(inputs) != 3 or not all(c.passed for c in result.checks)):
            raise ValueError("inconsistent scientific pass")
        self.journal.verification(self.attempt_id, result)
        return result

    async def run(self, fixture, repair=True, experiment_id=None, task="Diagnose the decay experiment."):
        if hasattr(self, "experiment_id"):
            raise ValueError("one diagnosis per Doctor instance")
        self.started = time.monotonic()
        started_at = time.time()
        self.experiment_id = str(UUID(str(experiment_id))) if experiment_id else str(uuid4())
        self.directory = self.journal.start(self.experiment_id, fixture)
        outcome, error = "INCOMPLETE", None
        try:
            async with asyncio.timeout(self.deadline):
                self.config = await self.client.configuration()
                if (not self.config.get("verifier_image") or self.config["verifier_hash"] != VERIFIER_HASH
                        or self.config["spec_hash"] != SPEC_HASH):
                    raise ValueError("trusted verifier not configured")
                registry = json.loads((ROOT / "experiments/fixtures/registry.json").read_text())
                entry = registry[fixture]
                source = (ROOT / "experiments" / entry["source"]).read_text()
                parameters = Parameters(dt=entry["dt"]).model_dump()
                original = source
                self.tool("read_experiment", {"fixture": fixture})
                for revision in range(3):
                    self.attempt_id = str(uuid4())
                    self.current = {"attempt_id": self.attempt_id, "revision": revision,
                                    "source": source, "parameters": parameters, "jobs": []}
                    self.attempts.append(self.current)
                    self.journal.attempt(self.attempt_id, self.experiment_id, revision, bundle_hash(source), parameters)
                    (self.directory / f"revision-{revision}.py").write_text(source)
                    result = await self.verify(source, parameters)
                    self.current["verification"] = result.model_dump(mode="json")
                    if result.verdict == "PASS":
                        outcome = "VERIFIED_HEALTHY" if revision == 0 else "VERIFIED_REPAIR"
                        break
                    if result.verdict == "UNVERIFIED":
                        outcome = "UNVERIFIED"
                        break
                    if not repair or revision == 2:
                        outcome = "NOT_REPAIRED"
                        break
                    if self.calls >= 5:
                        raise BudgetExceeded("model call budget")
                    self.calls += 1
                    checks = result.model_dump(mode="json")["checks"]
                    logs = []
                    # Logs are escaped JSON data, stripped of terminal/control codes.
                    for job in self.current["jobs"]:
                        for artifact in job["artifacts"]:
                            if artifact["name"] in ("stdout.txt", "stderr.txt"):
                                path = self.directory / f'{job["job_id"]}-{artifact["id"]}'
                                text = path.read_bytes()[:2048].decode(errors="replace")
                                logs.append(re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text))
                    proposal = await self.model.propose({"fixture": fixture, "source": source, "task": task[:1000],
                        "parameters": parameters, "verification_spec": {"equation": "dx/dt=-k*x", "max_abs_error": 0.01},
                        "checks": checks, "untrusted_logs": logs})
                    self.tool("propose_patch", {"revision": revision + 1})
                    source, parameters, patch = authorize(proposal, source, parameters, [c.key for c in result.checks])
                    self.current["proposal"] = proposal.model_dump(mode="json")
                    self.current["patch"] = patch
                    self.current["original_hash"] = bundle_hash(original)
        except PolicyDenied:
            outcome, error = "BLOCKED", "Patch/tool denied by deterministic policy"
            self.journal.event(self.experiment_id, "POLICY_DENIED", {"reason": error})
        except asyncio.CancelledError:
            outcome, error = "CANCELLED", "Diagnosis cancelled"
        except (InferenceFailure, BudgetExceeded, TimeoutError, ValueError, KeyError, OSError):
            outcome, error = "INCOMPLETE", "Diagnosis interrupted; completed evidence retained"
        except Exception:
            outcome, error = "INCOMPLETE", "Execution/provider unavailable; completed evidence retained"
        finally:
            if self.active is not None:
                try:
                    await asyncio.wait_for(self.client.cancel(self.active), timeout=5)
                except Exception:
                    error = "Cancellation request could not be confirmed; runner deadline still applies"
        # Deterministic report finalization never invokes a model.
        event = {"tool": "finalize_report", "outcome": outcome}
        self.events.append(event)
        self.journal.event(self.experiment_id, "TOOL", event)
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
        proposals = [a["proposal"] for a in self.attempts if "proposal" in a]
        comparison = {}
        for label, attempt in zip(("before", "after"), (self.attempts[:1] + self.attempts[-1:])):
            comparison[label] = {"parameters": attempt["parameters"],
                "source_hash": bundle_hash(attempt["source"]),
                "verdict": attempt.get("verification", {}).get("verdict", "INCOMPLETE"),
                "measurements": attempt.get("verification", {}).get("checks", [])}
        patch = patch_diff(self.attempts[0]["source"], self.attempts[-1]["source"],
                           self.attempts[0]["parameters"], self.attempts[-1]["parameters"]) if self.attempts else ""
        report = {"schema_version": "1", "experiment_id": self.experiment_id, "fixture": fixture,
                  "outcome": outcome, "error": error, "attempts": self.attempts, "events": self.events,
                  "model_id": self.model.model, "mode": self.model.mode, "model_usage": self.model.usage,
                  "model_calls": self.calls, "jobs_used": self.jobs,
                  "started_at": started_at, "elapsed_seconds": time.monotonic() - self.started, "finished_at": time.time(),
                  "hypothesis": proposals[-1]["hypothesis"] if proposals else None,
                  "patch": patch, "before_after": comparison,
                  "provenance": {"git_sha": git.stdout.strip() or "unavailable", "runtime_policy": "sandbox-v1",
                                 "working_tree_dirty": bool(dirty.stdout.strip()),
                                 "images": self.config, "spec_hash": SPEC_HASH, "verifier_hash": VERIFIER_HASH},
                  "limitations": LIMITATIONS}
        report["evidence_manifest"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                       for path in self.directory.iterdir() if path.is_file()}
        report = Report.model_validate(report).model_dump(mode="json")
        report["report_path"] = str(self.journal.finish(self.experiment_id, report))
        return report
