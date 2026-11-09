import hashlib
import io
import json
import zipfile

import pytest

from apps.api.app import APISettings, create_app
from tests.security.test_authorization import ORIGIN, client_session, complete, submit


@pytest.fixture
def browser_app(tmp_path):
    result = create_app(APISettings(root=tmp_path, origin=ORIGIN, session_key=b'test-browser-key' * 4))
    result.state.store.heartbeat('unit-worker')
    return result


def test_browser_views_and_zip_are_owned_and_bound(browser_app):
    app = browser_app
    owner, headers = client_session(app)
    other, _ = client_session(app)
    experiment_id = submit(owner, headers).json()['experiment_id']
    prefix = f'/api/v1/experiments/{experiment_id}'
    assert owner.get(prefix + '/evidence').status_code == 409
    complete(app, experiment_id, {'revision-0.py': b'print("safe text")', 'trajectory.csv': b't,x\n0,1\n5,0\n'})
    assert other.get(prefix + '/view').status_code == 404
    assert other.get(prefix + '/evidence').status_code == 404
    assert other.get('/api/v1/experiments').json() == []
    assert owner.get('/api/v1/experiments').json()[0]['experiment_id'] == experiment_id
    view = owner.get(prefix + '/view')
    assert view.status_code == 200
    assert view.json()['report']['outcome'] == 'VERIFIED_HEALTHY'
    response = owner.get(prefix + '/evidence')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert response.headers['content-disposition'].startswith('attachment;')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['experiment_id'] == experiment_id
        for item in manifest['artifacts']:
            assert '..' not in item['path'] and not item['path'].startswith('/')
            data = archive.read(item['path'])
            assert len(data) == item['size']
            assert hashlib.sha256(data).hexdigest() == item['sha256']
        assert json.loads(archive.read('report.json'))['outcome'] == 'VERIFIED_HEALTHY'


def test_zip_fails_closed_on_corrupt_or_expired_evidence(browser_app):
    app = browser_app
    owner, headers = client_session(app)
    experiment_id = submit(owner, headers).json()['experiment_id']
    complete(app, experiment_id, {'trajectory.csv': b't,x\n0,1\n5,0\n'})
    item = app.state.store.artifacts(experiment_id, app.state.store.get(experiment_id)['session_id'])[0]
    (app.state.store.blobs / item['id']).write_bytes(b'corrupt')
    assert owner.get(f'/api/v1/experiments/{experiment_id}/evidence').status_code == 500
    with app.state.store.connect() as db:
        db.execute('DELETE FROM artifacts WHERE experiment_id=?', (experiment_id,))
        db.execute('UPDATE experiments SET report=? WHERE id=?', (json.dumps({'outcome':'INCOMPLETE','evidence_expired':True}), experiment_id))
    assert owner.get(f'/api/v1/experiments/{experiment_id}/evidence').status_code == 410
    assert owner.get(f'/api/v1/experiments/{experiment_id}/view').json()['report']['evidence_expired'] is True
