"""Loopback browser acceptance server: real API + explicitly offline numeric/model fixtures.

Never runs candidate code. This test-only module is not a production worker mode.
"""
import asyncio
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

from apps.api.app import APISettings, create_app
from packages.agent.doctor import Doctor
from services.control.worker import ControlWorker
from tests.unit.test_agent import OfflineClient, OfflineModel


class BrowserModel(OfflineModel):
    model, mode = 'deterministic-browser-fixture', 'offline-e2e fixture'


root = Path(tempfile.mkdtemp(prefix='ed-browser-'))
os.chmod(root, 0o700)
app = create_app(APISettings(root=root, origin='http://127.0.0.1:5173',
                            session_key=os.urandom(48), allow_http_local=True))


async def work():
    store = app.state.store
    while True:
        store.heartbeat('browser-fixture')
        row = store.claim('browser-fixture')
        if row:
            model = BrowserModel()
            doctor = Doctor(OfflineClient(), model, root / 'diagnoses',
                            on_event=lambda kind, data: store.event(row['id'], kind, data))
            report = await doctor.run(row['fixture'], experiment_id=row['id'], task=row['task'])
            report.pop('report_path', None)
            publisher = ControlWorker(root, None, model)
            store.finish(row['id'], 'browser-fixture', report, publisher.files(row['id'], report))
        await asyncio.sleep(.15)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(work())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        shutil.rmtree(root)


app.router.lifespan_context = lifespan
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000, access_log=False)
