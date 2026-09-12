"""The durable snapshot replaces the retired per-worker RAM cache."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.routers import terminal
from app.services import agent_snapshot as snapshots


@pytest.fixture
def snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / 'status.json'
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(path))
    monkeypatch.setattr(terminal, '_HEALTH_STATE_FILE', path)
    return path


def publish(path, runtime='ONLINE', activity='IDLE'):
    row = snapshots.AgentSnapshot(agent='codex', runtime_state=runtime,
        activity_state=activity, checked_at=snapshots.now())
    snapshots.publish([row], path)
    return row


def client():
    app = FastAPI()
    app.include_router(terminal.router)
    return TestClient(app)


def test_concurrent_http_reads_identical_without_probes(snapshot_file, monkeypatch):
    publish(snapshot_file, activity='WAITING_INPUT')
    def forbidden(*args, **kwargs):
        raise AssertionError('status attempted a live probe')
    monkeypatch.setattr(terminal, '_current_process', forbidden)
    monkeypatch.setattr(terminal, 'SessionLocal', forbidden)
    with client() as api, ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: api.get('/api/agents/status').json(), range(48)))
    assert all(result == results[0] for result in results)
    codex = next(row for row in results[0]['agents'] if row['agent'] == 'codex')
    assert (codex['runtime_state'], codex['activity_state']) == ('ONLINE', 'WAITING_INPUT')
    assert codex['health'] == 'blocked'
    assert codex['awaiting_approval'] is True
    publish(snapshot_file, runtime='STOPPING')
    with client() as api:
        row = next(row for row in api.get('/api/agents/status').json()['agents'] if row['agent'] == 'codex')
    assert row['runtime_state'] == 'STOPPING'


def test_fastapi_process_restart_preserves_snapshot(snapshot_file):
    publish(snapshot_file, activity='BUSY')
    code = '''import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.terminal import router
app=FastAPI(); app.include_router(router)
with TestClient(app) as client:
 print(json.dumps(client.get('/api/agents/status').json(), sort_keys=True))
'''
    first = subprocess.check_output([sys.executable, '-c', code], cwd=str(Path(__file__).parents[1]), text=True, env=os.environ.copy())
    second = subprocess.check_output([sys.executable, '-c', code], cwd=str(Path(__file__).parents[1]), text=True, env=os.environ.copy())
    assert json.loads(first) == json.loads(second)
    assert 'BUSY' in first


@pytest.mark.parametrize('content', ['{bad', 'null', '[]', '{"version": 1, "agents": {}}'])
def test_corruption_never_falls_back_to_online(snapshot_file, content):
    snapshot_file.write_text(content)
    row = snapshots.read_snapshot(['codex'])['agents'][0]
    assert row['runtime_state'] == 'ERROR'
    assert not row['running']


def test_stale_and_missing_snapshots_are_errors(snapshot_file):
    assert snapshots.read_snapshot(['codex'])['agents'][0]['runtime_state'] == 'ERROR'
    row = publish(snapshot_file)
    row.checked_at = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    snapshots.atomic_json(snapshot_file, {'version': 2, 'updated_at': row.checked_at,
        'agents': {'codex': row.model_dump(mode='json')}})
    stale = snapshots.read_snapshot(['codex'])['agents'][0]
    assert stale['runtime_state'] == 'ERROR'
    assert stale['reason'] == 'snapshot_stale'


def test_lifecycle_publication_wins_over_older_probe(snapshot_file):
    old = snapshots.AgentSnapshot(agent='codex', runtime_state='ONLINE', activity_state='BUSY', checked_at=snapshots.now())
    publish(snapshot_file, runtime='STOPPING')
    snapshots.publish([old], snapshot_file)
    assert snapshots.read_snapshot(['codex'])['agents'][0]['runtime_state'] == 'STOPPING'


def test_concurrent_writers_preserve_all_agents(snapshot_file):
    def writer(number):
        snapshots.publish([snapshots.AgentSnapshot(agent=f'agent-{number}', runtime_state='OFFLINE', activity_state='IDLE', checked_at=snapshots.now())])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(24)))
    assert len(json.loads(snapshot_file.read_text())['agents']) == 24
