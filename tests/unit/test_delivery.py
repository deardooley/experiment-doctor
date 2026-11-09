import json
import sqlite3

import pytest

from packages.delivery.backup import create, restore, validate


def test_consistent_backup_restores_database_and_hash_bound_blobs(tmp_path):
    root = tmp_path / 'data'
    control = root / 'control'
    (control / 'blobs').mkdir(parents=True)
    (control / 'blobs/opaque').write_bytes(b'numeric evidence')
    with sqlite3.connect(control / 'api.sqlite3') as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE evidence (value TEXT)')
        db.execute('INSERT INTO evidence VALUES (?)', ('original',))
        db.commit()
        destination = root / 'backups/test'
        create(root, destination)
    manifest = validate(destination)
    assert set(manifest) == {'control/api.sqlite3', 'control/blobs/opaque'}
    (control / 'blobs/opaque').write_bytes(b'changed')
    restore(root, destination)
    assert (control / 'blobs/opaque').read_bytes() == b'numeric evidence'
    assert (root / 'control.before-restore/blobs/opaque').read_bytes() == b'changed'
    with sqlite3.connect(control / 'api.sqlite3') as db:
        assert db.execute('SELECT value FROM evidence').fetchone()[0] == 'original'
    with pytest.raises(ValueError, match='displaced state'):
        restore(root, destination)


def test_backup_rejects_symlinks_tampering_and_extra_files(tmp_path):
    root = tmp_path / 'data'
    (root / 'control').mkdir(parents=True)
    link = root / 'control/link'
    link.symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='Symlinks'):
        create(root, tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()
    link.unlink()
    (root / 'control/file').write_bytes(b'one')
    backup = tmp_path / 'backup'
    create(root, backup)
    (backup / 'control/file').write_bytes(b'two')
    with pytest.raises(ValueError, match='integrity'):
        validate(backup)
    (backup / 'control/file').write_bytes(b'one')
    (backup / 'unexpected').write_text('extra')
    with pytest.raises(ValueError, match='integrity'):
        validate(backup)
    assert 'control/file' in json.loads((backup / 'manifest.json').read_text())


def test_installed_release_provenance_does_not_require_git(tmp_path):
    from packages.delivery.provenance import revision
    (tmp_path / 'release.json').write_text(json.dumps({'git_sha': 'a' * 40, 'working_tree_dirty': True}))
    assert revision(tmp_path) == ('a' * 40, True)
    (tmp_path / 'release.json').write_text(json.dumps({'git_sha': 'invalid', 'working_tree_dirty': False}))
    with pytest.raises(ValueError, match='provenance'):
        revision(tmp_path)


def test_backup_cannot_recurse_into_live_data(tmp_path):
    (tmp_path / 'control').mkdir()
    with pytest.raises(ValueError, match='inside live data'):
        create(tmp_path, tmp_path / 'control/recursive')


def test_registry_transport_plans_are_portable_and_immutable():
    from packages.delivery.registry import plan, release
    data = {'release_id': 'v1', 'working_tree_dirty': False,
            'control_image': 'sha256:' + 'a' * 64, 'web_image': 'sha256:' + 'b' * 64,
            'verifier_image': 'sha256:' + 'c' * 64, 'simulation_image': 'python@sha256:' + 'd' * 64}
    assert release(json.dumps(data)) == data
    assert plan(data, 'docker.io/example/experiment-doctor')['web'] == 'docker.io/example/experiment-doctor-web:v1'
    assert plan(data, 'registry.gitlab.com/group/project')['control'] == 'registry.gitlab.com/group/project/control:v1'
    for prefix in ('bad prefix', '../escape', 'registry.gitlab.com/group/../other'):
        with pytest.raises(ValueError):
            plan(data, prefix)
    with pytest.raises(ValueError, match='immutable'):
        release(json.dumps(data | {'web_image': 'web:latest'}))


def test_named_local_preview_still_requires_explicit_development_mode(tmp_path):
    from apps.api.app import APISettings
    base = dict(root=tmp_path, session_key=b'a' * 32)
    with pytest.raises(ValueError, match='HTTPS'):
        APISettings(**base, origin='http://experiment-doctor.local:8080')
    APISettings(**base, origin='http://experiment-doctor.local:8080', allow_http_local=True)
    with pytest.raises(ValueError, match='HTTPS'):
        APISettings(**base, origin='http://experiment-doctor.local.evil:8080', allow_http_local=True)


def test_registry_push_records_immutable_dockerhub_references(tmp_path, monkeypatch):
    import packages.delivery.registry as registry
    data = {'release_id': 'v1', 'working_tree_dirty': False,
            **{role + '_image': 'sha256:' + str(index) * 64 for index, role in enumerate(registry.ROLES, 1)}}
    data['simulation_image'] = 'python@' + data['simulation_image']
    manifest = tmp_path / 'release.json'
    manifest.write_text(json.dumps(data))
    commands = []
    monkeypatch.setattr(registry.subprocess, 'run', lambda command, **kwargs: commands.append(command))

    def fake_docker(*args):
        source = args[-1]
        if '{{.Id}}' in args:
            return source.removeprefix('python@')
        name = source.rsplit(':', 1)[0].removeprefix('docker.io/')
        return json.dumps([name + '@sha256:' + 'a' * 64])

    monkeypatch.setattr(registry, 'docker', fake_docker)
    result = registry.push(manifest, 'docker.io/example/doctor')
    assert result['publication'] is True
    assert len([c for c in commands if c[:2] == ['docker', 'push']]) == 4
    transport = json.loads((tmp_path / 'registry.json').read_text())
    assert transport['images']['web']['reference'] == 'docker.io/example/doctor-web@sha256:' + 'a' * 64
    assert transport['release_json'] == manifest.read_text()


def test_registry_pull_refuses_unreviewed_manifest_before_network(tmp_path, monkeypatch):
    import packages.delivery.registry as registry
    transport = tmp_path / 'registry.json'
    transport.write_text(json.dumps({'release_json': '{}', 'manifest_sha256': '0' * 64}))
    monkeypatch.setattr(registry.subprocess, 'run', lambda *args, **kwargs: pytest.fail('network on rejected transport'))
    with pytest.raises(ValueError, match='hash mismatch'):
        registry.pull(transport, '0' * 64, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_backup_preserves_empty_initial_service_directories(tmp_path):
    root = tmp_path / 'data'
    for name in ('control/blobs', 'control/diagnoses', 'runner'):
        (root / name).mkdir(parents=True, exist_ok=True)
    backup = tmp_path / 'initial-backup'
    create(root, backup)
    restore(root, backup)
    for name in ('control/blobs', 'control/diagnoses', 'runner'):
        assert (root / name).is_dir()
