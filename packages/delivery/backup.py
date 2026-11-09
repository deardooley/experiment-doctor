"""Consistent SQLite + hash-bound data backup; services must be stopped by the operator."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path


def stopped():
    for service in ('api', 'control', 'runner'):
        result = subprocess.run(['systemctl', 'is-active', f'experiment-doctor-{service}'], capture_output=True)
        if result.stdout.strip() in (b'active', b'activating', b'deactivating'):
            raise ValueError('Stop API, control and runner services before backup/restore')


def inventory(root):
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks are not valid backup data')
        if path.is_file():
            files[str(path.relative_to(root))] = {
                'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return files


def create(root, destination):
    root, destination = root.resolve(), destination.resolve()
    if any(destination.is_relative_to(root / name) for name in ('control', 'runner')):
        raise ValueError('Backup destination cannot be inside live data')
    if destination.exists():
        raise ValueError('Backup destination already exists')
    destination.mkdir(parents=True, mode=0o700)
    try:
        for name in ('control', 'runner'):
            source = root / name
            if not source.exists():
                continue
            (destination / name).mkdir(mode=0o700)
            for path in source.rglob('*'):
                relative = path.relative_to(root)
                if path.is_symlink():
                    raise ValueError('Symlinks are not valid backup data')
                if path.is_dir():
                    (destination / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                if not path.is_file() or path.name.endswith(('-wal', '-shm', '.lock')):
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if path.suffix == '.sqlite3':
                    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as copy:
                        original.backup(copy)
                        assert copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                        copy.execute('PRAGMA journal_mode=DELETE')
                else:
                    shutil.copy2(path, target)
                target.chmod(0o600)
        (destination / 'manifest.json').write_text(json.dumps(inventory(destination), indent=2) + '\n')
        (destination / 'manifest.json').chmod(0o600)
    except BaseException:
        shutil.rmtree(destination)
        raise


def validate(backup):
    manifest = json.loads((backup / 'manifest.json').read_text())
    actual = inventory(backup)
    actual.pop('manifest.json', None)
    if actual != manifest:
        raise ValueError('Backup integrity mismatch')
    if any(not (name.startswith('control/') or name.startswith('runner/')) for name in actual):
        raise ValueError('Unexpected backup root')
    return manifest


def restore(root, backup):
    validate(backup)
    for name in ('control', 'runner'):
        if (root / (name + '.before-restore')).exists():
            raise ValueError('A previous displaced state must be reviewed first')
    # Keep displaced state for review/recovery; never overwrite it silently.
    for name in ('control', 'runner'):
        target = root / name
        displaced = root / (name + '.before-restore')
        if displaced.exists():
            raise ValueError('A previous displaced state must be reviewed first')
        if target.exists():
            target.rename(displaced)
        if (backup / name).exists():
            shutil.copytree(backup / name, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['create', 'validate', 'restore'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'validate':
        validate(args.destination)
    else:
        if os.geteuid() != 0:
            raise SystemExit('Run as root with services stopped')
        stopped()
        if args.action == 'create':
            create(args.root, args.destination)
        else:
            restore(args.root, args.destination)
            subprocess.run(['chown', '-R', 'doctor-worker:doctor-control', str(args.root / 'control')], check=True)
            private = args.root / 'control/diagnoses'
            if private.exists():
                subprocess.run(['chown', '-R', 'doctor-worker:doctor-worker', str(private)], check=True)
                private.chmod(0o700)
            subprocess.run(['chown', '-R', 'doctor-runner:doctor-runner', str(args.root / 'runner')], check=True)
            for name in ('control', 'control/blobs'):
                (args.root / name).chmod(0o2770)
            for path in (args.root / 'control').glob('api.sqlite3*'):
                path.chmod(0o660)
            for path in (args.root / 'control/blobs').iterdir():
                if path.is_file():
                    path.chmod(0o660)
            (args.root / 'runner').chmod(0o700)
    print(json.dumps({'action': args.action, 'status': 'ok'}))


if __name__ == '__main__':
    main()
