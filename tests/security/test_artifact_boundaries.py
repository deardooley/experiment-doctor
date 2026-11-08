import io
import tarfile

import pytest

from services.runner.runtime import MAX_ARTIFACTS, OutputLimit, RuntimeFailure, parse_artifacts


def test_malformed_archive_is_not_extracted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(tarfile.TarError):
        parse_artifacts(b"malformed archive" * 100)
    assert list(tmp_path.iterdir()) == []


def test_oversize_raw_stream_is_rejected_before_tar_parsing():
    with pytest.raises(OutputLimit):
        parse_artifacts(b"x" * (MAX_ARTIFACTS + 65537))


def test_duplicate_and_oversized_member_headers_fail_closed():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for _ in range(2):
            archive.addfile(tarfile.TarInfo("trajectory.csv"))
    with pytest.raises(RuntimeFailure):
        parse_artifacts(stream.getvalue())
    stream = io.BytesIO()
    member = tarfile.TarInfo("trajectory.csv")
    member.size = MAX_ARTIFACTS * 100
    stream.write(member.tobuf())
    stream.write(b"\0" * 1024)
    with pytest.raises(OutputLimit):
        parse_artifacts(stream.getvalue())


def test_missing_enforcement_prevents_supervisor_start(tmp_path):
    from fastapi.testclient import TestClient
    from services.runner.api import create_app
    from services.runner.runtime import Settings
    class MissingControls:
        launches = 0
        def cleanup_all(self):
            pass
        def preflight(self):
            raise RuntimeFailure("required cgroup control absent")
        def execute(self, *args):
            self.launches += 1
            raise AssertionError("must never launch")
    runtime = MissingControls()
    settings = Settings(root=tmp_path, image="python@sha256:" + "a"*64, bundles={})
    with pytest.raises(RuntimeFailure):
        with TestClient(create_app(settings, runtime)):
            pass
    assert runtime.launches == 0
