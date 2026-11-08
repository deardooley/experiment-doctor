"""Fixed Docker argv, bounded streams, no bind mounts or host candidate execution."""
import hashlib
import io
import json
import re
import subprocess
import tarfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

MAX_LOG = 256 * 1024
MAX_ARTIFACTS = 10 * 1024 * 1024
LABEL = "org.experiment-doctor.runner"
# Candidate code executes only in the sandbox. Exec status comes from Docker,
# not candidate logs. The independent keeper preserves tmpfs until extraction.
BOOTSTRAP = '''
import json, pathlib, subprocess, sys
p = json.loads(sys.stdin.buffer.read(65537))
path = pathlib.Path('/tmp/simulation.py')
path.write_text(p['code'])
r = subprocess.run([sys.executable, '-I', str(path), json.dumps(p['parameters'])],
                   cwd='/tmp', env={'PATH':'/usr/local/bin:/usr/bin:/bin'})
sys.exit(r.returncode)
'''
# Docker archive-copy omits tmpfs mount contents. Export through exec instead;
# every returned byte remains untrusted and is validated again outside the job.
EXPORTER = '''
import io, os, stat, sys, tarfile
names = os.listdir('/output')
if any(name != 'trajectory.csv' for name in names):
    sys.exit(2)
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    if names:
        fd = os.open('/output/trajectory.csv', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 9961472:
                sys.exit(2)
            data = stream.read(9961473)
        if len(data) > 9961472:
            sys.exit(2)
        member = tarfile.TarInfo('trajectory.csv')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
'''


class RuntimeFailure(RuntimeError):
    pass


class OutputLimit(RuntimeFailure):
    pass


def bounded_process(argv, payload=None, limit=MAX_LOG, timeout=10, poll=None):
    """Continuously drain both pipes; never buffer unbounded Docker output."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if payload else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def read(stream, target):
        while chunk := stream.read(8192):
            remaining = max(0, limit - len(target))
            target.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
        stream.close()

    def write():
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    readers = [threading.Thread(target=read, args=(stream, buf), daemon=True)
               for stream, buf in zip((process.stdout, process.stderr), buffers)]
    for reader in readers:
        reader.start()
    writer = threading.Thread(target=write, daemon=True) if payload else None
    if writer:
        writer.start()
    started = time.monotonic()
    failure = None
    try:
        while process.poll() is None:
            if overflow.is_set():
                raise OutputLimit("bounded stream exceeded")
            if time.monotonic() - started >= timeout:
                raise TimeoutError("runtime command deadline")
            if poll:
                poll()
            time.sleep(0.05)
    except BaseException as exc:
        failure = exc
        process.kill()
    finally:
        process.wait()
        for reader in readers:
            reader.join(timeout=2)
        if writer:
            writer.join(timeout=2)
    if failure:
        failure.stdout = bytes(buffers[0])
        failure.stderr = bytes(buffers[1])
        raise failure
    if any(reader.is_alive() for reader in readers) or overflow.is_set():
        raise OutputLimit("bounded stream exceeded")
    return process.returncode, bytes(buffers[0]), bytes(buffers[1])


def parse_artifacts(raw):
    if len(raw) > MAX_ARTIFACTS + 65536:
        raise OutputLimit("archive limit")
    outputs = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for index, member in enumerate(archive):
            if index >= 8:
                raise RuntimeFailure("too many artifact members")
            if member.isdir() and member.name in (".", "./", "output", "output/"):
                continue
            name = member.name.removeprefix("./")
            if not member.isfile() or member.linkname or name != "trajectory.csv":
                raise RuntimeFailure("artifact path or type denied")
            if name in outputs or member.size > MAX_ARTIFACTS - 2 * MAX_LOG:
                raise OutputLimit("artifact size or duplicate denied")
            stream = archive.extractfile(member)
            outputs[name] = stream.read(member.size + 1)
            if len(outputs[name]) != member.size:
                raise RuntimeFailure("truncated artifact")
    return outputs


@dataclass(frozen=True)
class Settings:
    root: Path
    image: str
    bundles: dict[str, bytes]
    scope: str = "dev"
    deadline: float = 30
    disk_reserve: int = 64 * 1024 * 1024

    def __post_init__(self):
        if not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", self.image):
            raise ValueError("pre-pulled digest-pinned image required")
        if not re.fullmatch(r"[a-z0-9-]{1,32}", self.scope):
            raise ValueError("invalid runner scope")
        if not 0 < self.deadline <= 30:
            raise ValueError("deadline must be bounded by 30 seconds")
        for digest, code in self.bundles.items():
            if len(code) > 32768 or digest != "sha256:" + hashlib.sha256(code).hexdigest():
                raise ValueError("invalid immutable bundle")
            code.decode("utf-8")

    def authorize(self, spec):
        if (spec.kind != "simulation" or spec.image_digest != self.image.split("@")[1]
                or spec.bundle_hash not in self.bundles):
            raise ValueError("job is not in the runner's simulation allowlist")


class DockerRuntime:
    def __init__(self, settings):
        self.settings = settings

    def command(self, *args, timeout=10, limit=MAX_LOG):
        code, stdout, _ = bounded_process(["docker", *args], timeout=timeout, limit=limit)
        if code:
            raise RuntimeFailure("Docker operation failed")
        return stdout

    def preflight(self):
        script = Path(__file__).resolve().parents[2] / "scripts" / "doctor"
        import os
        env = dict(os.environ, SIMULATION_IMAGE=self.settings.image)
        # Only trusted fixed probes; subprocess.run buffers these known-small outputs.
        result = subprocess.run(["bash", str(script)], env=env, capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeFailure("runtime enforcement preflight failed")

    def cleanup_all(self):
        ids = self.command("ps", "-aq", "--filter", f"label={LABEL}={self.settings.scope}")
        for container in ids.decode().split():
            self.command("rm", "-f", container)

    def name(self, job_id):
        return f"ed-{self.settings.scope}-{job_id}"

    def remove(self, name):
        # Ignore not-found only; verify no container with this exact name remains.
        bounded_process(["docker", "rm", "-f", name])
        remaining = self.command("ps", "-aq", "--filter", f"name=^/{name}$")
        if remaining.strip():
            raise RuntimeFailure("container cleanup failed")

    def execute(self, job_id, spec, poll):
        name = self.name(job_id)
        poll()
        self.command("create", "--init", "--name", name, "--pull=never", "--label",
                     f"{LABEL}={self.settings.scope}", "--network=none", "--read-only",
                     "--user=65532:65532", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                     "--cpus=1", "--memory=512m", "--memory-swap=512m", "--pids-limit=64",
                     "--log-driver=none", "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m",
                     "--tmpfs=/output:rw,noexec,nosuid,nodev,size=64m",
                     "--entrypoint=/usr/bin/env", self.settings.image, "-i",
                     "PATH=/usr/local/bin:/usr/bin:/bin", "python", "-I", "-c",
                     "import time; time.sleep(86400)")
        poll()
        self.command("start", name)
        poll()
        payload = json.dumps({"code": self.settings.bundles[spec.bundle_hash].decode(),
                              "parameters": spec.parameters.model_dump()}).encode()
        code, stdout, stderr = bounded_process(
            ["docker", "exec", "-i", name, "/usr/bin/env", "-i",
             "PATH=/usr/local/bin:/usr/bin:/bin", "python", "-I", "-c", BOOTSTRAP],
            payload=payload, timeout=self.settings.deadline, poll=poll)
        state = json.loads(self.command("inspect", "--format={{json .State}}", name))
        # OOM of an exec child can leave the keeper alive; inspect cgroup events too.
        _, oom_events, _ = bounded_process([
            "docker", "exec", name, "/usr/bin/env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin",
            "python", "-I", "-c",
            "from pathlib import Path; print(Path('/sys/fs/cgroup/memory.events').read_text())"])
        oom = state.get("OOMKilled") or any(
            line.startswith("oom_kill ") and int(line.split()[1]) > 0
            for line in oom_events.decode().splitlines())
        if not state["Running"]:
            return "FAILED", "OOM" if oom else "RUNTIME_ERROR", code, {
                "stdout.txt": stdout, "stderr.txt": stderr}
        poll()
        archive = self.command("exec", name, "/usr/bin/env", "-i",
                               "PATH=/usr/local/bin:/usr/bin:/bin", "python", "-I", "-c",
                               EXPORTER, timeout=10, limit=MAX_ARTIFACTS + 65536)
        outputs = parse_artifacts(archive)
        outputs.update({"stdout.txt": stdout, "stderr.txt": stderr})
        success = code == 0 and not oom
        return ("SUCCEEDED" if success else "FAILED",
                "SUCCESS" if success else "OOM" if oom else "RUNTIME_ERROR", code, outputs)
