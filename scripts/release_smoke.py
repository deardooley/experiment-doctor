"""Real HTTPS repair/healthy/download/ownership smoke; never invents successful outcomes."""
import argparse
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import httpx

from packages.verification.contracts import VerificationResult


def wait(client, experiment_id):
    deadline = time.monotonic() + 200
    while time.monotonic() < deadline:
        response = client.get(f'/api/v1/experiments/{experiment_id}/view')
        response.raise_for_status()
        value = response.json()
        if value['status'] not in ('QUEUED', 'RUNNING'):
            return value
        time.sleep(.5)
    raise TimeoutError('Deployed experiment did not complete')


def run(origin, ca=None):
    import ssl
    if not origin.startswith('https://'):
        raise ValueError('Release smoke requires HTTPS')
    trust = ssl.create_default_context(cafile=str(ca)) if ca else True
    results = []
    with httpx.Client(base_url=origin, timeout=20, verify=trust, trust_env=False) as client, httpx.Client(
            base_url=origin, timeout=20, verify=trust, trust_env=False) as other:
        client.get('/health/ready').raise_for_status()
        release_id = client.get('/health/live').json()['release_id']
        if not release_id:
            raise ValueError('Smoke target is not an installed release')
        bootstrap = client.get('/api/v1/session')
        bootstrap.raise_for_status()
        assert all(flag in bootstrap.headers['set-cookie'].lower() for flag in ('secure', 'httponly', 'samesite=lax'))
        headers = {'Origin': origin, 'X-CSRF-Token': bootstrap.json()['csrf_token']}
        other.get('/api/v1/session').raise_for_status()
        assert client.post('/execution/v1/jobs', json={}).status_code == 404
        for fixture, expected in (('decay-healthy', 'VERIFIED_HEALTHY'), ('decay-coarse-step', 'VERIFIED_REPAIR')):
            response = client.post('/api/v1/experiments', json={'fixture_id': fixture}, headers=headers)
            response.raise_for_status()
            experiment_id = response.json()['experiment_id']
            value = wait(client, experiment_id)
            assert value['status'] == expected, value['status']
            for attempt in value['report']['attempts']:
                VerificationResult.model_validate(attempt['verification'])
                assert all(job['execution']['cleanup'] == 'removed' for job in attempt['jobs'])
            if expected == 'VERIFIED_REPAIR':
                assert value['report']['provenance']['mode'] == 'live'
                assert value['report']['provenance']['model_calls'] >= 1
                assert value['report']['attempts'][0]['verification']['verdict'] == 'FAIL'
            assert other.get(f'/api/v1/experiments/{experiment_id}/view').status_code == 404
            assert other.get(f'/api/v1/experiments/{experiment_id}/evidence').status_code == 404
            evidence = client.get(f'/api/v1/experiments/{experiment_id}/evidence')
            evidence.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(evidence.content)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                for item in manifest['artifacts']:
                    data = archive.read(item['path'])
                    assert len(data) == item['size'] and hashlib.sha256(data).hexdigest() == item['sha256']
            final = value['report']['attempts'][-1]['verification']
            results.append({'fixture': fixture, 'outcome': value['status'], 'mode': value['report']['provenance']['mode'],
                            'final_checks': len(final['checks']), 'model_usage': value['report']['provenance']['model_usage'],
                            'evidence_integrity': True, 'foreign_session_denied': True})
        response = client.post('/api/v1/experiments', json={'fixture_id': 'decay-healthy'}, headers=headers)
        response.raise_for_status()
        experiment_id = response.json()['experiment_id']
        client.post(f'/api/v1/experiments/{experiment_id}/cancel', headers=headers).raise_for_status()
        cancelled = wait(client, experiment_id)
        assert cancelled['status'] == 'CANCELLED', 'Completion won the race; cancellation gate must be rerun'
        token = os.environ.get('API_OPERATOR_TOKEN')
        containment = None
        if token:
            response = client.post('/api/v1/operator/probes/network', headers=headers | {'Authorization': 'Bearer ' + token})
            response.raise_for_status()
            contained = wait(client, response.json()['experiment_id'])
            assert contained['status'] == 'CONTAINED'
            observation = contained['report']['containment']
            assert observation['positive_control'] and observation['messages_received'] == 0
            assert observation['cleanup'] == 'removed' and observation['runner_healthy_after']
            assert all(not c['connected'] for c in observation['connections'])
            containment = observation
        client.get('/health/ready').raise_for_status()
    return {'origin': origin, 'release_id': release_id, 'transport': 'HTTPS with verified certificate', 'workflows': results,
            'cancellation_winner': cancelled['status'], 'containment': containment, 'ready_after': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', required=True)
    parser.add_argument('--ca', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.origin.rstrip('/'), args.ca)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'workflows': len(result['workflows']), 'ready_after': result['ready_after']}))


if __name__ == '__main__':
    main()
