"""Portable trusted release archives; no candidate archive is inspected or extracted."""
import argparse
import gzip
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROLES = ('control', 'web', 'verifier', 'simulation')
DOCKER = ['docker']


def docker(*args):
    return subprocess.check_output([*DOCKER, *args], text=True, stderr=subprocess.PIPE).strip()


def release(text):
    data = json.loads(text)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', data['release_id']):
        raise ValueError('Invalid release ID')
    for role in ROLES:
        reference = data[role + '_image']
        if role == 'simulation' and not reference.startswith('python@sha256:'):
            raise ValueError('Simulation must use the pinned Python repository digest')
        digest = reference.removeprefix('python@') if role == 'simulation' else reference
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Release images must be immutable digests')
    return data


def tags(data):
    return {role: f'experiment-doctor-transport-{role}:{data["release_id"]}' for role in ROLES}


def metadata(archive, name):
    member = archive.getmember(name)
    if not member.isfile() or member.size > 1024 * 1024:
        raise ValueError('Invalid release archive metadata')
    with archive.extractfile(member) as stream:
        return stream.read()


def verify(archive_path, data, check_ids=True):
    """Bind canonical config digests to named, reachable OCI manifests without extraction."""
    transport = tags(data)
    with tarfile.open(archive_path, 'r:*') as archive:
        entries = json.loads(metadata(archive, 'manifest.json'))
        if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
            raise ValueError('Invalid Docker archive manifest')
        available = {}
        for entry in entries:
            config = metadata(archive, entry['Config'])
            identity = 'sha256:' + hashlib.sha256(config).hexdigest()
            platform = json.loads(config)
            if platform.get('os') != 'linux' or platform.get('architecture') != 'amd64':
                raise ValueError('Release image must use linux/amd64')
            for tag in entry.get('RepoTags') or []:
                if tag in available and available[tag] != identity:
                    raise ValueError('Ambiguous release transport tag')
                available[tag] = identity
        bindings = {}
        for role, tag in transport.items():
            if tag not in available:
                raise ValueError(f'Release archive lacks named {role} image; repack the release')
            if check_ids and role != 'simulation' and available[tag] != data[role + '_image']:
                raise ValueError(f'Release archive {role} identity mismatch')
            bindings[role] = {'config_id': available[tag], 'identities': [available[tag]]}
        try:
            index = json.loads(metadata(archive, 'index.json'))
        except KeyError:
            return bindings
        visited = {}

        def walk(descriptor, depth=0):
            digest = descriptor['digest']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest) or depth > 4 or len(visited) > 64:
                raise ValueError('Invalid OCI image index')
            if digest in visited:
                return visited[digest]
            found = {}
            visited[digest] = found
            raw = metadata(archive, 'blobs/sha256/' + digest[7:])
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('OCI metadata hash mismatch')
            document = json.loads(raw)
            if 'config' in document:
                found[document['config']['digest']] = {digest}
            else:
                for child in document.get('manifests', []):
                    for config, identities in walk(child, depth + 1).items():
                        found.setdefault(config, set()).update(identities | {digest})
            return found

        named = {}
        for descriptor in index.get('manifests', []):
            name = descriptor.get('annotations', {}).get('io.containerd.image.name', '')
            named[name.removeprefix('docker.io/library/')] = walk(descriptor)
        for role, tag in transport.items():
            config = available[tag]
            if config not in named.get(tag, {}):
                raise ValueError(f'OCI index omits named {role} image; repack the release')
            bindings[role]['identities'] += sorted(named[tag][config])
        return bindings


def config_id(reference):
    """Docker .Id differs by store; hash the actual single-platform config instead."""
    process = subprocess.Popen([*DOCKER, 'save', '--platform', 'linux/amd64', reference], stdout=subprocess.PIPE)
    found = set()
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
            for member in archive:
                if not member.isfile() or member.size > 1024 * 1024:
                    continue
                raw = archive.extractfile(member).read()
                try:
                    document = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(document, dict) and document.get('architecture') == 'amd64' and document.get('os') == 'linux' and 'rootfs' in document:
                    found.add('sha256:' + hashlib.sha256(raw).hexdigest())
    finally:
        process.stdout.close()
        result = process.wait()
    if result or len(found) != 1:
        raise ValueError('Cannot resolve a single immutable linux/amd64 image config')
    return found.pop()


def local_reference(data, role):
    for candidate in (data[role + '_image'], tags(data)[role]):
        try:
            return docker('image', 'inspect', '--format', '{{.Id}}', candidate)
        except subprocess.CalledProcessError:
            pass
    raise ValueError(f'Local {role} image missing; use the Docker daemon that built/pulled this release')


def export(archive_path, data, canonicalize=False):
    references = tags(data)
    for role in ROLES:
        source = local_reference(data, role)
        subprocess.run([*DOCKER, 'tag', source, references[role]], check=True)
    with archive_path.open('wb') as stream:
        save = subprocess.Popen([*DOCKER, 'save', '--platform', 'linux/amd64', *references.values()], stdout=subprocess.PIPE)
        try:
            with gzip.GzipFile(fileobj=stream, mode='wb', compresslevel=1, mtime=0) as compressed:
                shutil.copyfileobj(save.stdout, compressed, 1024 * 1024)
        finally:
            save.stdout.close()
            result = save.wait()
        if result:
            raise ValueError('Docker release export failed')
    bindings = verify(archive_path, data, check_ids=not canonicalize)
    if canonicalize:
        for role in ROLES:
            if role != 'simulation':
                data[role + '_image'] = bindings[role]['config_id']
    return bindings


def resolve(archive_path, manifest):
    data = release(manifest.read_text())
    bindings = verify(archive_path, data)
    for role in ROLES:
        reference = docker('image', 'inspect', '--format', '{{.Id}}', tags(data)[role])
        if reference not in bindings[role]['identities']:
            raise ValueError(f'Loaded {role} image does not match the reviewed archive')
        bindings[role] = {'reference': reference, 'config_id': bindings[role]['config_id']}
    return {'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(), 'images': bindings}


def checksums(directory):
    entries = []
    for name in ('release.json', 'images.tar.gz'):
        with (directory / name).open('rb') as stream:
            entries.append(f'{hashlib.file_digest(stream, "sha256").hexdigest()}  {name}\n')
    (directory / 'SHA256SUMS').write_text(''.join(entries))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['export', 'verify', 'repack', 'resolve', 'config-id'])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reference')
    parser.add_argument('--canonicalize', action='store_true')
    parser.add_argument('--rootless', action='store_true')
    args = parser.parse_args()
    if args.rootless:
        if os.geteuid() != 0:
            raise SystemExit('Rootless deployment image resolution requires the root operator')
        uid = pwd.getpwnam('doctor-runner').pw_uid
        DOCKER[:] = ['runuser', '-u', 'doctor-runner', '--', 'env', f'DOCKER_HOST=unix:///run/user/{uid}/docker.sock', 'docker']
    if args.action == 'config-id':
        if not args.reference:
            parser.error('--reference is required')
        print(config_id(args.reference))
        return
    if args.manifest is None:
        parser.error('--manifest is required')
    data = release(args.manifest.read_text())
    if args.action == 'resolve':
        print(json.dumps(resolve(args.archive or args.manifest.with_name('images.tar.gz'), args.manifest)))
        return
    if args.action == 'verify':
        verify(args.archive or args.manifest.with_name('images.tar.gz'), data)
    elif args.action == 'export':
        export(args.archive or args.manifest.with_name('images.tar.gz'), data, args.canonicalize)
        if args.canonicalize:
            args.manifest.write_text(json.dumps(data, indent=2) + '\n')
    else:
        if args.output is None or args.output.exists():
            raise SystemExit('Repack requires a new --output directory')
        args.output.mkdir(parents=True, mode=0o700)
        try:
            shutil.copyfile(args.manifest, args.output / 'release.json')
            export(args.output / 'images.tar.gz', data)
            checksums(args.output)
        except BaseException:
            shutil.rmtree(args.output)
            raise
    print(json.dumps({'status': 'ok', 'action': args.action}))


if __name__ == '__main__':
    main()
