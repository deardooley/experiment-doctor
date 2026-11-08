"""Root-only dev/test proof using the real Linux service identities; no secret data printed."""
import argparse
import json
import subprocess
from pathlib import Path


def run_as(user, *args):
    return subprocess.run(["runuser", "-u", user, "--", *args], capture_output=True, timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-socket", required=True)
    parser.add_argument("--docker-socket", required=True)
    parser.add_argument("--credential-canary", required=True)
    parser.add_argument("--runner-db", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-pid", type=int, required=True)
    parser.add_argument("--worker-pid", type=int, required=True)
    parser.add_argument("--runner-pid", type=int, required=True)
    args = parser.parse_args()
    assert Path(args.credential_canary).is_file() and Path(args.runner_db).is_file()
    public = run_as("doctor-api", "curl", "-fsS", "--max-time", "3", "--unix-socket", args.runner_socket, "http://runner/health/ready")
    worker = run_as("doctor-worker", "curl", "-fsS", "--max-time", "3", "--unix-socket", args.runner_socket, "http://runner/health/ready")
    api_docker = run_as("doctor-api", "env", "DOCKER_HOST=unix://" + args.docker_socket, "docker", "info")
    worker_docker = run_as("doctor-worker", "env", "DOCKER_HOST=unix://" + args.docker_socket, "docker", "info")
    runner_docker = run_as("doctor-runner", "env", "DOCKER_HOST=unix://" + args.docker_socket,
                           "docker", "info", "--format", "{{json .SecurityOptions}}")
    api_credential = run_as("doctor-api", "test", "-r", args.credential_canary)
    runner_credential = run_as("doctor-runner", "test", "-r", args.credential_canary)
    api_db = run_as("doctor-api", "test", "-r", args.runner_db)
    def environment_names(pid):
        assert pid > 0
        return {item.split(b"=",1)[0].decode() for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if item}
    api_env, worker_env, runner_env = map(environment_names, (args.api_pid, args.worker_pid, args.runner_pid))
    report = {"api_runner_socket_denied": public.returncode != 0,
              "worker_runner_socket_allowed": worker.returncode == 0 and json.loads(worker.stdout)["status"] == "ready",
              "api_docker_socket_denied": api_docker.returncode != 0,
              "worker_docker_socket_denied": worker_docker.returncode != 0,
              "runner_docker_socket_allowed": runner_docker.returncode == 0 and b"rootless" in runner_docker.stdout,
              "api_worker_credential_denied": api_credential.returncode != 0,
              "runner_worker_credential_denied": runner_credential.returncode != 0,
              "api_runner_database_denied": api_db.returncode != 0,
              "api_model_and_cloud_environment_absent": not {"INFERENCE_API_KEY","VULTR_API_KEY"}.intersection(api_env),
              "worker_api_and_cloud_environment_absent": not {"API_SESSION_KEY","API_OPERATOR_TOKEN","VULTR_API_KEY"}.intersection(worker_env),
              "runner_all_project_credentials_absent": not {"API_SESSION_KEY","API_OPERATOR_TOKEN","INFERENCE_API_KEY","VULTR_API_KEY"}.intersection(runner_env),
              "credential_probe": "synthetic file only; no real model/cloud credential supplied"}
    assert all(value is True for key, value in report.items() if key != "credential_probe")
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
