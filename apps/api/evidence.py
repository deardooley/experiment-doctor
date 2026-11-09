"""Bounded owned evidence ZIPs; no archive from a sandbox is ever extracted."""
import hashlib
import json
import re
import tempfile
import threading
import zipfile

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

EXPORTS = threading.BoundedSemaphore(2)


def bundle(store, row, reserve):
    import shutil
    items = store.artifacts(row['id'], row['session_id'])
    if not items:
        expired = bool(row['report'] and json.loads(row['report']).get('evidence_expired'))
        raise HTTPException(410 if expired else 409, 'Evidence expired' if expired else 'Evidence is not available yet')
    total = sum(item['size'] for item in items)
    if len(items) > 64 or total > 32 * 1024 * 1024 or shutil.disk_usage(store.root).free < total + reserve:
        raise HTTPException(503, 'Evidence export unavailable')
    if not EXPORTS.acquire(blocking=False):
        raise HTTPException(429, 'Evidence exports are busy')
    try:
        stream = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, dir=store.root, mode='w+b')
    except OSError:
        EXPORTS.release()
        raise HTTPException(503, 'Evidence export unavailable') from None
    released = False

    def close():
        nonlocal released
        if not released:
            released = True
            stream.close()
            EXPORTS.release()

    try:
        names = {}
        raw = json.loads(row['report']) if row['report'] else {}
        diagnostic = raw.get('following_healthy', raw)
        for index, attempt in enumerate(diagnostic.get('attempts', [])[:3]):
            names[f'revision-{index}.py'] = f'source/revision-{index}.py'
            for job in attempt.get('jobs', [])[:4]:
                role = job.get('role')
                if role not in ('primary', 'refinement', 'held_out', 'verification'):
                    continue
                for artifact in job.get('artifacts', []):
                    if artifact['name'] in ('trajectory.csv', 'verification.json', 'stdout.txt', 'stderr.txt'):
                        names[f'{job["job_id"]}-{artifact["id"]}'] = f'runs/revision-{index}/{role}/{artifact["name"]}'
        manifest = []
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            def generated(name, data):
                archive.writestr(name, data)
                manifest.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})

            for index, attempt in enumerate(diagnostic.get('attempts', [])[:3]):
                generated(f'parameters/revision-{index}.json', json.dumps(attempt['parameters'], indent=2).encode())
                for job in attempt.get('jobs', [])[:4]:
                    role = job.get('role')
                    if role in ('primary', 'refinement', 'held_out', 'verification') and job.get('spec'):
                        generated(f'runs/revision-{index}/{role}/parameters.json',
                                  json.dumps(job['spec']['parameters'], indent=2).encode())
            if diagnostic.get('patch'):
                generated('repair.patch', diagnostic['patch'].encode())
            generated('README.txt', (
                'Experiment Doctor evidence\n\n'
                'Read report.json for model mode, timestamps, image digests, Git SHA and limitations.\n'
                'The manifest binds exported bytes; hashes do not establish scientific correctness.\n'
                'Numeric verdicts are recorded in verification.json and report.json.\n'
                'Replay requires a Linux rootless runner, pinned images and the matching repository revision.\n'
                'See docs/scientific-doctor.md and docs/execution.md in that revision.\n'
                'Use make diagnose FIXTURE=' + row['fixture'] + ' RUNNER_SOCKET=<private-runner-socket>\n'
                'to repeat the fixture; model prose and repair choices may differ. Never run candidate code on the host.\n'
            ).encode())
            for item in items:
                if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', item['name']) or item['size'] > 10 * 1024 * 1024:
                    raise ValueError('invalid artifact metadata')
                path = store.blobs / item['id']
                if path.is_symlink() or not path.is_file() or path.stat().st_size != item['size']:
                    raise ValueError('artifact integrity failure')
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('artifact integrity failure')
                name = 'report.json' if item['name'] == 'report.json' else names.get(
                    item['name'], f'artifacts/{item["id"]}-{item["name"]}')
                archive.writestr(name, data)
                manifest.append({'path': name, 'size': len(data), 'sha256': item['sha256']})
            archive.writestr('manifest.json', json.dumps({'experiment_id': row['id'], 'artifacts': manifest}, indent=2))
        stream.seek(0)
    except Exception:
        close()
        raise HTTPException(500, 'Evidence integrity check failed') from None

    async def chunks():
        try:
            while data := stream.read(65536):
                yield data
        finally:
            close()

    return StreamingResponse(chunks(), media_type='application/zip', background=BackgroundTask(close),
                             headers={'Content-Disposition': f'attachment; filename="experiment-{row["id"]}-evidence.zip"'})
