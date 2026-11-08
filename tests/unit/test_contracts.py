from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts import JobSpec, JobStatus, Parameters, validate_transition


def spec(**overrides):
    return JobSpec.model_validate(dict(
        experiment_id=uuid4(), attempt_id=uuid4(), image_digest="sha256:" + "a" * 64,
        bundle_hash="sha256:" + "b" * 64, parameters={}, idempotency_key="test", **overrides,
    ))


def test_spec_rejects_runtime_escape():
    with pytest.raises(ValidationError):
        spec(command="sh")
    with pytest.raises(ValidationError):
        spec(image="python:latest")
    with pytest.raises(ValidationError):
        spec(kind="verification")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, 3])
def test_bad_dt(value):
    with pytest.raises(ValidationError):
        Parameters(dt=value)


def test_terminal_states_are_immutable():
    validate_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    for terminal in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
        with pytest.raises(ValueError):
            validate_transition(terminal, JobStatus.RUNNING)


def test_valid_spec():
    assert spec().parameters.dt == 0.01
