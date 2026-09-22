"""Publicação canônica → journal durável → banco, com probes/processos isolados."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, JSON, String, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import registry, sessionmaker

from app.services import agent_snapshot as snapshot, runtime_state_audit as audit


@pytest.fixture(autouse=True)
def audit_store(tmp_path, monkeypatch):
    mapping = registry()
    class Event:
        pass
    mapping.map_imperatively(Event, Table('agent_run_events', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('run_id', UUID(as_uuid=True)),
        Column('event_type', String), Column('message', String), Column('payload', JSON),
        Column('created_at', DateTime(timezone=True))))
    engine = create_engine(f'sqlite:///{tmp_path}/audit.db')
    mapping.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(audit, '_session', factory)
    monkeypatch.setattr(audit, 'AgentRunEvent', Event)
    def events():
        with factory() as db:
            return [row.payload for row in db.query(Event).order_by(Event.created_at).all()]
    yield SimpleNamespace(factory=factory, Event=Event, events=events)
    engine.dispose()


def row(state='ONLINE', seconds=0, **kwargs):
    activity = kwargs.pop('activity', 'IDLE')
    return snapshot.AgentSnapshot(agent='codex', runtime_state=state,
        activity_state=activity, checked_at=(datetime(2026, 9, 22, tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat(), **kwargs)


def test_duplicate_state_and_sample_never_audit(tmp_path, audit_store):
    path = tmp_path/'status.json'
    for sample in (row(), row(seconds=1), row(seconds=1), row(seconds=2)):
        snapshot.publish([sample], path)
    assert audit_store.events() == []


def test_store_rejects_equal_states(audit_store):
    state = {'runtime':'ONLINE','activity':'IDLE'}
    with pytest.raises(ValueError, match='requires a transition'):
        audit.persist([{'event_id':str(uuid4()),'payload':{'estado_anterior':state,'novo_estado':state}}])
    assert audit_store.events() == []


def test_cycle_has_exactly_two_sequential_events(tmp_path, audit_store):
    path = tmp_path/'status.json'
    for sample in (row(), row('OFFLINE',1), row('OFFLINE',11), row('OFFLINE',12), row(seconds=13), row(seconds=14)):
        snapshot.publish([sample],path)
    events = audit_store.events()
    assert [(e['estado_anterior']['runtime'], e['novo_estado']['runtime']) for e in events] == [('ONLINE','OFFLINE'),('OFFLINE','ONLINE')]
    assert [e['sequence'] for e in events] == [1,2]
    assert events[0]['timestamp'] < events[1]['timestamp']
    assert all(e['runtime_id']=='codex' for e in events)
    assert all(datetime.fromisoformat(e['timestamp']).tzinfo for e in events)


def test_one_failed_probe_recovers_without_transition(tmp_path, audit_store):
    path = tmp_path/'status.json'
    snapshot.publish([row()],path)
    snapshot.publish([row('ERROR',1,reason='collection_timeout')],path)
    assert json.loads(path.read_text())['agents']['codex']['runtime_state']=='ONLINE'
    snapshot.publish([row(seconds=12)],path)
    assert audit_store.events()==[]
    assert json.loads(path.read_text())['audit_candidates']=={}


def test_repeated_sample_is_not_confirmation(tmp_path, audit_store):
    path = tmp_path/'status.json'
    snapshot.publish([row()],path)
    sample=row('ERROR',1)
    for _ in range(4): snapshot.publish([sample],path)
    snapshot.publish([row('ERROR',9)],path)
    assert audit_store.events()==[]
    snapshot.publish([row('ERROR',11)],path)
    assert len(audit_store.events())==1


def test_lifecycle_immediate_with_run_and_error(tmp_path, audit_store):
    path=tmp_path/'status.json'
    run_id=str(uuid4())
    snapshot.publish([row()],path)
    snapshot.publish([row('ERROR',1,active_run_id=run_id,reason='start_failed')],path,source='lifecycle')
    event=audit_store.events()[0]
    assert event['run_id']==run_id
    assert event['erro']=='start_failed'
    assert event['source']=='lifecycle'
    assert {'runtime_id','estado_anterior','novo_estado','timestamp'} <= event.keys()


@pytest.mark.parametrize('activity',['BUSY','WAITING_INPUT'])
def test_activity_change_audited_once(tmp_path,audit_store,activity):
    path=tmp_path/'status.json'
    snapshot.publish([row()],path)
    snapshot.publish([row(seconds=1,activity=activity)],path)
    snapshot.publish([row(seconds=2,activity=activity)],path)
    assert [e['novo_estado']['activity'] for e in audit_store.events()]==[activity]


def test_database_outage_replays_without_gap(tmp_path,audit_store,monkeypatch):
    path=tmp_path/'status.json'
    persist=audit.persist
    def unavailable(entries): raise OperationalError('isolated',{},Exception('down'))
    monkeypatch.setattr(audit,'persist',unavailable)
    snapshot.publish([row()],path)
    snapshot.publish([row('OFFLINE',1)],path,source='lifecycle')
    snapshot.publish([row(seconds=2)],path)
    assert len(json.loads(path.read_text())['audit_pending'])==2
    monkeypatch.setattr(audit,'persist',persist)
    snapshot.publish([],path)
    assert len(audit_store.events())==2
    assert json.loads(path.read_text())['audit_pending']==[]


def test_crash_after_database_commit_replays_same_uuid(tmp_path,audit_store,monkeypatch):
    path=tmp_path/'status.json'
    snapshot.publish([row()],path)
    write=snapshot.atomic_json
    def crash_on_clear(target,payload):
        if payload.get('audit_sequence') and not payload['audit_pending']:
            raise OSError('crash after database commit')
        write(target,payload)
    monkeypatch.setattr(snapshot,'atomic_json',crash_on_clear)
    with pytest.raises(OSError):
        snapshot.publish([row(seconds=1,activity='BUSY')],path)
    assert len(audit_store.events())==1
    monkeypatch.setattr(snapshot,'atomic_json',write)
    snapshot.publish([],path)
    assert len(audit_store.events())==1
    assert json.loads(path.read_text())['audit_pending']==[]


def test_concurrent_same_transition_is_exactly_once(tmp_path,audit_store):
    path=tmp_path/'status.json'
    snapshot.publish([row()],path)
    def publish(_): snapshot.publish([row(seconds=1,activity='BUSY')],path)
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(publish,range(16)))
    assert len(audit_store.events())==1


def test_old_probe_cannot_undo_lifecycle(tmp_path,audit_store):
    path=tmp_path/'status.json'
    snapshot.publish([row()],path)
    snapshot.publish([row('ERROR',1)],path)
    snapshot.publish([row('STOPPING',20)],path,source='lifecycle')
    snapshot.publish([row('ERROR',11)],path)
    assert [e['novo_estado']['runtime'] for e in audit_store.events()]==['STOPPING']


def test_corrupted_journal_is_not_overwritten(tmp_path):
    path=tmp_path/'status.json'
    path.write_text('{broken')
    with pytest.raises(OSError,match='journal unreadable'): snapshot.publish([row()],path)
    assert path.read_text()=='{broken'


def test_public_event_route_cannot_forge_runtime_audit(monkeypatch):
    from fastapi import BackgroundTasks, HTTPException
    from app.routers import handoffs
    from app.schemas.handoff import RunEventCreate
    from unittest.mock import Mock
    db=Mock()
    monkeypatch.setattr(handoffs,'_get_run',lambda *args: SimpleNamespace(id=uuid4()))
    with pytest.raises(HTTPException) as error:
        handoffs.create_run_event(uuid4(), RunEventCreate(event_type='runtime.state_changed', payload={}), BackgroundTasks(), db)
    assert error.value.status_code==403
    db.commit.assert_not_called()


def test_stop_keeps_previous_run_association(tmp_path,audit_store):
    path=tmp_path/'status.json'
    run_id=str(uuid4())
    snapshot.publish([row(activity='BUSY',active_run_id=run_id)],path)
    snapshot.publish([row('STOPPING',1)],path,source='lifecycle')
    assert audit_store.events()[0]['run_id']==run_id
