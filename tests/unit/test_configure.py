"""Synthetic credentials only: no .env, real SSH connection or /etc write is used."""
import json
import os
import shlex
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.delivery import configure as config


@pytest.fixture
def values():
    return {'PUBLIC_ORIGIN': 'https://doctor.example.com', 'ACME_EMAIL': 'operator@example.com',
            'INFERENCE_MODEL': 'test-model', 'INFERENCE_API_KEY': 'synthetic-inference-key'}


def read(directory, name):
    return config.parse_dotenv((directory / name).read_text())


def test_dotenv_is_data_filtered_by_role_and_environment_takes_precedence(tmp_path, values):
    marker = tmp_path / 'must-not-exist'
    path = tmp_path / '.env'
    path.write_text('export INFERENCE_MODEL="file model" # note\n'
                    f'INFERENCE_API_KEY="$(touch {marker})"\n'
                    'VULTR_API_KEY=never-transfer-cloud-key\nUNRELATED="ignored\n'
                    'PUBLIC_ORIGIN=https://doctor.example.com\nACME_EMAIL=operator@example.com\n')
    loaded = config.load_values(str(path), {'INFERENCE_MODEL': 'exported-model'})
    assert loaded['INFERENCE_MODEL'] == 'exported-model'
    assert not marker.exists() and 'VULTR_API_KEY' not in loaded
    files = config.configuration(loaded)
    assert set(files) == {'api.env', 'inference.env', 'web.env'}
    assert set(files['inference.env']) == config.FILE_KEYS['inference.env']
    assert 'INFERENCE_API_KEY' not in files['api.env']
    assert files['api.env']['API_ENABLE_OPERATOR_PROBES'] == '0'
    assert config.load_values('-', values) == values
    with pytest.raises(config.ConfigurationError, match='does not exist'):
        config.load_values(str(tmp_path / 'missing'), values)


def test_environment_file_quotes_preserve_literal_secret_characters(values):
    secret = 'synthetic "quoted" \\ $literal `literal` # hash and spaces'
    files = config.configuration(values | {'API_SESSION_KEY': secret, 'INFERENCE_API_KEY': secret})
    for name, fields in files.items():
        assert config.parse_dotenv(config.render(fields).decode()) == fields
    # The installer's readiness check can consume the generated quoted origin.
    line = next(line for line in config.render(files['api.env']).decode().splitlines() if line.startswith('PUBLIC_ORIGIN='))
    assert shlex.split(line.split('=', 1)[1]) == ['https://doctor.example.com']


def test_remote_files_are_private_and_session_key_survives_redeployment(tmp_path, values):
    directory = tmp_path / 'config'
    config.install_files(config.configuration(values), directory)
    first_key = read(directory, 'api.env')['API_SESSION_KEY']
    assert len(first_key) == 64
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in config.FILE_KEYS:
        info = (directory / name).stat()
        assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.geteuid()
    config.install_files(config.configuration(values | {'INFERENCE_API_KEY': 'rotated-inference-key'}), directory)
    assert read(directory, 'api.env')['API_SESSION_KEY'] == first_key
    assert read(directory, 'inference.env')['INFERENCE_API_KEY'] == 'rotated-inference-key'
    replacement = 'explicit-new-session-key-' + 'x' * 32
    config.install_files(config.configuration(values | {'API_SESSION_KEY': replacement}), directory)
    assert read(directory, 'api.env')['API_SESSION_KEY'] == replacement


def test_operator_probes_require_explicit_enable_and_strong_separate_token(values):
    token = 'synthetic-operator-token-' + 'x' * 32
    assert 'API_OPERATOR_TOKEN' not in config.configuration(values | {'API_OPERATOR_TOKEN': token})['api.env']
    with pytest.raises(config.ConfigurationError, match='separate strong'):
        config.configuration(values | {'API_ENABLE_OPERATOR_PROBES': '1'})
    api = config.configuration(values | {'API_ENABLE_OPERATOR_PROBES': '1', 'API_OPERATOR_TOKEN': token})['api.env']
    assert api['API_OPERATOR_TOKEN'] == token and api['API_ENABLE_OPERATOR_PROBES'] == '1'


@pytest.mark.parametrize('patch', [
    {'PUBLIC_ORIGIN': 'http://doctor.example.com'},
    {'PUBLIC_ORIGIN': 'https://doctor.example.com/path'},
    {'PUBLIC_HOST': 'different.example.com'},
    {'PUBLIC_ORIGIN': 'https://experiment-doctor.local'},
    {'INFERENCE_BASE_URL': 'https://untrusted.invalid/v1'},
    {'API_SESSION_KEY': 'short'},
    {'INFERENCE_API_KEY': 'secret\nINJECTED=value'},
    {'ACME_EMAIL': ''},
    {'API_ENABLE_OPERATOR_PROBES': 'true'},
])
def test_invalid_configuration_fails_before_transfer(values, patch):
    with pytest.raises(config.ConfigurationError):
        config.configuration(values | patch)


def test_hostname_derives_origin_when_only_public_host_is_supplied(values):
    values.pop('PUBLIC_ORIGIN')
    files = config.configuration(values | {'PUBLIC_HOST': 'doctor.example.com'})
    assert files['api.env']['PUBLIC_ORIGIN'] == 'https://doctor.example.com'


def test_staging_failure_restores_previous_file_set(tmp_path, values, monkeypatch):
    directory = tmp_path / 'config'
    config.install_files(config.configuration(values), directory)
    original = {name: (directory / name).read_bytes() for name in config.FILE_KEYS}
    real_replace = os.replace
    count = 0

    def failed_second_replace(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError('synthetic write failure')
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(config.os, 'replace', failed_second_replace)
    with pytest.raises(OSError):
        config.install_files(config.configuration(values | {'API_SESSION_KEY': 'new-key-' + 'x' * 40}), directory)
    assert {name: (directory / name).read_bytes() for name in config.FILE_KEYS} == original
    assert not list(directory.glob('.stage-*'))


def test_staging_refuses_symlinks_and_unknown_role_fields(tmp_path, values):
    directory = tmp_path / 'config'
    directory.mkdir()
    outside = tmp_path / 'outside'
    outside.write_text('must remain unchanged')
    (directory / 'api.env').symlink_to(outside)
    with pytest.raises(OSError):
        config.install_files(config.configuration(values), directory)
    assert outside.read_text() == 'must remain unchanged'
    files = config.configuration(values)
    files['web.env']['INFERENCE_API_KEY'] = 'not-for-web'
    with pytest.raises(config.ConfigurationError, match='role-scoped'):
        config.install_files(files, directory)


def test_ssh_transfers_only_filtered_json_stdin_and_does_not_log_remote_output(tmp_path, values, monkeypatch):
    files = config.configuration(values)
    calls = []

    def ssh(command, **kwargs):
        calls.append((command, kwargs))
        assert 'StrictHostKeyChecking=yes' in command
        assert values['INFERENCE_API_KEY'] not in ' '.join(command)
        assert 'VULTR_API_KEY' not in kwargs['input']
        assert 'INFERENCE_API_KEY' not in kwargs['env'] and 'VULTR_API_KEY' not in kwargs['env']
        config.install_files(json.loads(kwargs['input']), tmp_path / 'remote-config')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(config.subprocess, 'run', ssh)
    config.stage('root@doctor.example.com', Path('/private/key'), files, Path('/private/known_hosts'))
    assert read(tmp_path / 'remote-config', 'inference.env')['INFERENCE_API_KEY'] == values['INFERENCE_API_KEY']
    assert len(calls) == 1
    monkeypatch.setattr(config.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=values['INFERENCE_API_KEY']))
    with pytest.raises(config.ConfigurationError) as failure:
        config.stage('root@doctor.example.com', Path('/private/key'), files)
    assert values['INFERENCE_API_KEY'] not in str(failure.value)


def test_cli_validation_errors_do_not_echo_secret_values(values, monkeypatch, capsys):
    secret = 'SENSITIVE-MARKER\nnot-valid'
    for key in config.KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in (values | {'INFERENCE_API_KEY': secret}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr('sys.argv', ['configure', '--env-file', '-', '--check'])
    with pytest.raises(SystemExit):
        config.main()
    output = capsys.readouterr()
    assert 'SENSITIVE-MARKER' not in output.err and secret not in output.out
    assert 'INFERENCE_API_KEY' in output.err


def test_deploy_stages_configuration_before_release_transfer(tmp_path, values):
    import hashlib
    import subprocess

    root = Path(__file__).resolve().parents[2]
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    events = tmp_path / 'events'
    payload = tmp_path / 'payload.json'
    ssh = binaries / 'ssh'
    ssh.write_text('#!/usr/bin/env bash\nTEST_PAYLOAD=' + shlex.quote(str(payload)) + '\nTEST_EVENTS=' + shlex.quote(str(events)) + '''
set -euo pipefail
case "$*" in
  *--receive*) cat > "$TEST_PAYLOAD"; printf 'configure\\n' >> "$TEST_EVENTS" ;;
  *mktemp*) printf 'mkdir\\n' >> "$TEST_EVENTS"; printf '/var/tmp/doctor-release.test123\\n' ;;
  *'bash -s'*) cat >/dev/null; printf 'install\\n' >> "$TEST_EVENTS" ;;
esac
''')
    ssh.chmod(0o755)
    scp = binaries / 'scp'
    scp.write_text('#!/usr/bin/env bash\nprintf "copy\\n" >> ' + shlex.quote(str(events)) + '\n')
    scp.chmod(0o755)
    release = tmp_path / 'release'
    from tests.unit.test_release_images import create_archive
    create_archive(release)
    (release / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256((release / name).read_bytes()).hexdigest()}  {name}\n'
        for name in ('release.json', 'images.tar.gz')))
    source = tmp_path / 'deployment.env'
    source.write_text(''.join(f'{key}={value}\n' for key, value in values.items()) + 'VULTR_API_KEY=cloud-marker\n')
    environment = {key: value for key, value in os.environ.items() if key not in config.KEYS}
    environment.update(PATH=str(binaries) + os.pathsep + environment['PATH'],
                       TEST_PAYLOAD=str(payload), TEST_EVENTS=str(events))
    result = subprocess.run(['bash', 'scripts/deploy', 'root@doctor.example.com', str(release), '/private/key', str(source)],
                            cwd=root, env=environment, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert events.read_text().splitlines() == ['configure', 'mkdir', 'copy', 'copy', 'copy', 'install']
    assert 'cloud-marker' not in payload.read_text()
    assert values['INFERENCE_API_KEY'] not in result.stdout + result.stderr
    assert json.loads(payload.read_text())['inference.env']['INFERENCE_API_KEY'] == values['INFERENCE_API_KEY']


def test_preserves_legacy_systemd_key_with_literal_hash_and_internal_spaces(tmp_path, values):
    directory = tmp_path / 'config'
    directory.mkdir()
    key = 'legacy-key-' + 'x' * 32 + '  # literal suffix'
    (directory / 'api.env').write_text('API_SESSION_KEY=' + key + '\n')
    config.install_files(config.configuration(values), directory)
    assert read(directory, 'api.env')['API_SESSION_KEY'] == key
