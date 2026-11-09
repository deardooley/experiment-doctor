"""Explicit registry transport. Build never publishes; pushes require this operator command."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROLES = ('control', 'web', 'verifier', 'simulation')
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.PIPE).strip()


def release(text):
    data = json.loads(text)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', data['release_id']):
        raise ValueError('Invalid release ID')
    for role in ROLES:
        ref = data[role + '_image']
        if role == 'simulation' and not ref.startswith('python@sha256:'):
            raise ValueError('Simulation must use the pinned Python repository digest')
        digest = ref.removeprefix('python@') if role == 'simulation' else ref
        if not DIGEST.fullmatch(digest):
            raise ValueError('Release images must be immutable digests')
    return data


def plan(data, prefix):
    prefix = prefix.rstrip('/')
    if (not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]{2,200}', prefix)
            or '/' not in prefix or any(p in ('', '.', '..') for p in prefix.split('/'))):
        raise ValueError('Use a registry hostname and repository namespace')
    hub = prefix.startswith('docker.io/')
    if hub and len(prefix.split('/')) != 3:
        raise ValueError('Docker Hub prefix must be docker.io/namespace/repository')
    separator = '-' if hub else '/'
    return {role: f'{prefix}{separator}{role}:{data["release_id"]}' for role in ROLES}


def push(manifest, prefix, dry_run=False, allow_dirty=False):
    text = manifest.read_text()
    data = release(text)
    tags = plan(data, prefix)
    if data['working_tree_dirty'] and not allow_dirty:
        raise ValueError('Dirty dev snapshots are not publishable without --allow-dirty')
    if dry_run:
        return {'publication': False, 'tags': tags}
    locations = {}
    from packages.delivery.images import config_id, tags as transport_tags
    for role, tag in tags.items():
        source = data[role + '_image']
        for candidate in (source, transport_tags(data)[role]):
            try:
                source = docker('image', 'inspect', '--format', '{{.Id}}', candidate)
                break
            except subprocess.CalledProcessError:
                continue
        else:
            raise ValueError(f'Local {role} image missing')
        image_id = config_id(source)
        if role != 'simulation' and image_id != data[role + '_image']:
            raise ValueError('Registry push image config mismatch')
        subprocess.run(['docker', 'tag', source, tag], check=True)
        subprocess.run(['docker', 'push', tag], check=True)
        refs = json.loads(docker('image', 'inspect', '--format', '{{json .RepoDigests}}', tag))
        repository = tag.rsplit(':', 1)[0]
        normalized = repository.removeprefix('docker.io/')
        ref = next((r for r in refs if r.split('@')[0].removeprefix('docker.io/') == normalized), None)
        if not ref or not DIGEST.fullmatch(ref.rsplit('@', 1)[1]):
            raise ValueError('Registry did not supply an immutable digest')
        locations[role] = {'reference': repository + '@' + ref.rsplit('@', 1)[1], 'image_id': image_id}
    result = {'schema': 1, 'release_json': text, 'manifest_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'images': locations}
    (manifest.parent / 'registry.json').write_text(json.dumps(result, indent=2) + '\n')
    return {'publication': True, 'images': locations}


def pull(transport, expected_hash, output):
    info = json.loads(transport.read_text())
    text = info['release_json']
    if (not re.fullmatch(r'[a-f0-9]{64}', expected_hash)
            or hashlib.sha256(text.encode()).hexdigest() != expected_hash or info['manifest_sha256'] != expected_hash):
        raise ValueError('Reviewed manifest hash mismatch')
    data = release(text)
    if output.exists():
        raise ValueError('Use a new output directory')
    output.mkdir(parents=True, mode=0o700)
    try:
        # Original pinned Python digest independently binds any mirrored simulation image.
        subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', data['simulation_image']], check=True)
        from packages.delivery.images import config_id, tags as transport_tags
        original_simulation = config_id(data['simulation_image'])
        for role in ROLES:
            item = info['images'][role]
            ref = item['reference']
            if not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]+@sha256:[a-f0-9]{64}', ref):
                raise ValueError('Registry reference must use an immutable digest')
            expected = original_simulation if role == 'simulation' else data[role + '_image']
            if item['image_id'] != expected:
                raise ValueError('Registry transport image identity mismatch')
            subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', ref], check=True)
            if config_id(ref) != expected:
                raise ValueError('Downloaded image identity mismatch')
            subprocess.run(['docker', 'tag', ref, transport_tags(data)[role]], check=True)
        (output / 'release.json').write_text(text)
        from packages.delivery.images import export
        export(output / 'images.tar.gz', data)
        hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ('release.json', 'images.tar.gz')}
        (output / 'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in hashes.items()))
    except BaseException:
        shutil.rmtree(output)
        raise
    return {'downloaded': True, 'manifest_sha256': expected_hash}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    publish = commands.add_parser('push')
    publish.add_argument('--manifest', type=Path, required=True)
    publish.add_argument('--prefix', required=True)
    publish.add_argument('--dry-run', action='store_true')
    publish.add_argument('--allow-dirty', action='store_true')
    download = commands.add_parser('pull')
    download.add_argument('--transport', type=Path, required=True)
    download.add_argument('--manifest-sha256', required=True)
    download.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = push(args.manifest, args.prefix, args.dry_run, args.allow_dirty) if args.command == 'push' else pull(
        args.transport, args.manifest_sha256, args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
