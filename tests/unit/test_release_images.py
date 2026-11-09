"""Synthetic image metadata only; no candidate code or container is executed."""
import hashlib
import io
import json
import tarfile

import pytest

from packages.delivery.images import ROLES, tags, verify


def create_archive(directory, oci=True, named=True, oci_roles=ROLES):
    directory.mkdir(parents=True, exist_ok=True)
    data = {'release_id': 'test-release', 'working_tree_dirty': False,
            'simulation_image': 'python@sha256:' + 'e' * 64}
    files, entries, descriptors = {}, [], []
    for role in ROLES:
        config = json.dumps({'os': 'linux', 'architecture': 'amd64', 'role': role}).encode()
        identity = hashlib.sha256(config).hexdigest()
        if role != 'simulation':
            data[role + '_image'] = 'sha256:' + identity
        config_name = 'blobs/sha256/' + identity
        files[config_name] = config
        tag = tags(data)[role]
        entries.append({'Config': config_name, 'RepoTags': [tag] if named else None, 'Layers': []})
        image = json.dumps({'schemaVersion': 2, 'config': {'digest': 'sha256:' + identity}, 'layers': []}).encode()
        digest = hashlib.sha256(image).hexdigest()
        files['blobs/sha256/' + digest] = image
        if role in oci_roles:
            descriptors.append({'digest': 'sha256:' + digest,
                                'annotations': {'io.containerd.image.name': 'docker.io/library/' + tag}})
    files['manifest.json'] = json.dumps(entries).encode()
    if oci:
        files['index.json'] = json.dumps({'schemaVersion': 2, 'manifests': descriptors}).encode()
    path = directory / 'images.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    (directory / 'release.json').write_text(json.dumps(data))
    return data, path


@pytest.mark.parametrize('oci', [False, True])
def test_named_archive_covers_every_role_for_both_store_formats(tmp_path, oci):
    data, archive = create_archive(tmp_path, oci=oci)
    verify(archive, data)


def test_rejects_complete_legacy_manifest_with_incomplete_oci_index(tmp_path):
    data, archive = create_archive(tmp_path, oci_roles=('simulation',))
    with pytest.raises(ValueError, match='OCI index omits named control'):
        verify(archive, data)


def test_rejects_untagged_export_even_when_all_config_blobs_exist(tmp_path):
    data, archive = create_archive(tmp_path, named=False)
    with pytest.raises(ValueError, match='lacks named control'):
        verify(archive, data)


def test_rejects_manifest_config_identity_mismatch(tmp_path):
    data, archive = create_archive(tmp_path)
    with pytest.raises(ValueError, match='control identity mismatch'):
        verify(archive, data | {'control_image': 'sha256:' + 'f' * 64})


def test_export_passes_named_platform_tags_and_verifies_both_manifests(tmp_path, monkeypatch):
    import gzip
    import packages.delivery.images as images

    data, fixture = create_archive(tmp_path / 'fixture')
    raw = gzip.decompress(fixture.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        entries = json.loads(archive.extractfile('manifest.json').read())
        simulation_id = next('sha256:' + e['Config'].rsplit('/', 1)[1] for e in entries
                             if tags(data)['simulation'] in e['RepoTags'])
    commands = []
    monkeypatch.setattr(images, 'docker', lambda *args: simulation_id if args[-1] == data['simulation_image'] else args[-1])
    monkeypatch.setattr(images.subprocess, 'run', lambda args, **kwargs: commands.append(args))

    class Save:
        stdout = io.BytesIO(raw)

        def __init__(self, args, **kwargs):
            commands.append(args)

        def wait(self):
            return 0

    monkeypatch.setattr(images.subprocess, 'Popen', Save)
    output = tmp_path / 'images.tar.gz'
    images.export(output, data)
    save = next(command for command in commands if command[1] == 'save')
    assert save[:4] == ['docker', 'save', '--platform', 'linux/amd64']
    assert save[4:] == list(tags(data).values())
    verify(output, data)


@pytest.mark.parametrize('store', ['classic', 'containerd'])
def test_resolves_store_native_ids_only_through_verified_archive(tmp_path, monkeypatch, store):
    import packages.delivery.images as images
    data, archive = create_archive(tmp_path)
    bindings = verify(archive, data)
    native = {tags(data)[role]: item['identities'][0 if store == 'classic' else -1]
              for role, item in bindings.items()}
    monkeypatch.setattr(images, 'docker', lambda *args: native[args[-1]])
    resolution = images.resolve(archive, tmp_path / 'release.json')
    assert resolution['images']['control']['config_id'] == data['control_image']
    assert resolution['images']['control']['reference'] == native[tags(data)['control']]
    assert resolution['manifest_sha256'] == hashlib.sha256((tmp_path / 'release.json').read_bytes()).hexdigest()
    monkeypatch.setattr(images, 'docker', lambda *args: 'sha256:' + 'f' * 64)
    with pytest.raises(ValueError, match='does not match'):
        images.resolve(archive, tmp_path / 'release.json')


def test_config_identity_comes_from_actual_config_bytes_not_docker_id(tmp_path, monkeypatch):
    import packages.delivery.images as images
    raw_config = json.dumps({'os': 'linux', 'architecture': 'amd64', 'rootfs': {'diff_ids': []}}).encode()
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode='w') as archive:
        member = tarfile.TarInfo('blobs/sha256/config')
        member.size = len(raw_config)
        archive.addfile(member, io.BytesIO(raw_config))

    class Save:
        stdout = io.BytesIO(raw_tar.getvalue())

        def __init__(self, *args, **kwargs):
            pass

        def wait(self):
            return 0

    monkeypatch.setattr(images.subprocess, 'Popen', Save)
    assert images.config_id('opaque-store-native-reference') == 'sha256:' + hashlib.sha256(raw_config).hexdigest()
