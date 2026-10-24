"""Inbox de eventos committado, isolamento de rollback, proteção de replay e gates de política."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
import json
import pytest
from sqlalchemy import Column, DateTime, String, JSON, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry, sessionmaker
from app.services import adaptive_config, adaptive_review, observer_events, run_observer, run_pause, observer_selection, observer_workspace
from app.services import adaptive_ai
from app.services.review_policy import decide
from tests.test_adaptive_supervision import decision
from app.services.supervision_policy import decide_supervision


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    mapping=registry()
    class Run: pass
    class Event: pass
    class Plan: pass
    class Task: pass
    mapping.map_imperatively(Run,Table('agent_runs',mapping.metadata,
        Column('id',UUID(as_uuid=True),primary_key=True),Column('plan_id',UUID(as_uuid=True)),
        Column('backlog_id',UUID(as_uuid=True)),Column('agent',String),Column('reviewer_agent',String),
        Column('complexity',String),Column('status',String),Column('commit_sha',String),Column('result',String),
        Column('error',String),Column('updated_at',DateTime)))
    mapping.map_imperatively(Event,Table('agent_run_events',mapping.metadata,
        Column('id',UUID(as_uuid=True),primary_key=True,default=uuid4),Column('run_id',UUID(as_uuid=True)),
        Column('event_type',String),Column('message',String),Column('payload',JSON),
        Column('created_at',DateTime,default=lambda:datetime.now(timezone.utc))))
    mapping.map_imperatively(Plan,Table('execution_plans',mapping.metadata,
        Column('id',UUID(as_uuid=True),primary_key=True),Column('objective',String),Column('scope',String),
        Column('acceptance_criteria',String),Column('status',String),Column('approved_at',DateTime)))
    mapping.map_imperatively(Task,Table('backlog',mapping.metadata,
        Column('id',UUID(as_uuid=True),primary_key=True),Column('project_id',UUID(as_uuid=True)),
        Column('status',String),Column('updated_at',DateTime)))
    engine=create_engine(f'sqlite:///{tmp_path}/inbox.db')
    mapping.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    for module in (observer_events,adaptive_review):
        monkeypatch.setattr(module,'AgentRunEvent',Event)
        monkeypatch.setattr(module,'ExecutionPlan',Plan)
    monkeypatch.setattr(observer_events,'AgentRun',Run)
    monkeypatch.setattr(observer_events,'BacklogItem',Task)
    monkeypatch.setattr(run_pause,'AgentRun',Run)
    monkeypatch.setattr(run_pause,'AgentRunEvent',Event)
    monkeypatch.setattr(run_pause,'BacklogItem',Task)
    monkeypatch.setattr(observer_selection,'AgentRunEvent',Event)
    monkeypatch.setattr(observer_workspace,'AgentRun',Run)
    monkeypatch.setattr(observer_workspace,'AgentRunEvent',Event)
    monkeypatch.setattr('app.services.agent_lifecycle.GROUPS_FILE',tmp_path/'groups.json')
    monkeypatch.setattr(adaptive_config,'load',lambda:adaptive_config.AdaptiveConfig(enabled=True))
    def update(db, run, payload):
        if 'status' in payload: run.status=payload['status']
        return run,None
    monkeypatch.setattr('app.services.handoff.update_run', update)
    gate=SimpleNamespace(passed=True,git_commit_sha='a'*40)
    monkeypatch.setattr('app.services.test_gate.get_gate_evidence_for_run',lambda *args:gate)
    with factory() as db:
        task=Task(id=uuid4(),project_id=uuid4()); plan=Plan(id=uuid4(),objective='Update isolated endpoint',scope='app/endpoint.py',acceptance_criteria='Tests pass',status='approved',approved_at=datetime.now(timezone.utc))
        run=Run(id=uuid4(),plan_id=plan.id,backlog_id=task.id,agent='codex',reviewer_agent='claude',complexity='medium',status='running',commit_sha='a'*40)
        db.add_all([task,plan,run]); db.commit()
        policy=decide_supervision(decision('MEDIUM'),'medium')
        db.add(Event(run_id=run.id,event_type='routing.jev_decision',payload={'policy':policy.model_dump(mode='json')}));db.commit()
        run_id=run.id
    def emit(kind, payload=None, commit=True):
        with factory() as db:
            row=Event(run_id=run_id,event_type=kind,payload=payload or {})
            db.add(row);db.flush(); key=row.id
            db.commit() if commit else db.rollback()
            return key
    yield SimpleNamespace(factory=factory,Run=Run,Event=Event,Plan=Plan,run_id=run_id,emit=emit,gate=gate)
    engine.dispose()


OK={'status':'ok','severity':'none','scope':'within','evidence_quality':'good','escalate':False}


def test_only_committed_relevant_events_are_observed_once(inbox,monkeypatch):
    inbox.emit('file_changed',commit=False)
    inbox.emit('terminal.cursor')
    call=Mock(return_value=({'text':json.dumps(OK),'model':'actual'},'correlation'))
    monkeypatch.setattr(adaptive_ai,'call',call)
    with inbox.factory() as db:
        assert not observer_events.consume_one(db)
    key=inbox.emit('file_changed',{'file':'app/endpoint.py'})
    with inbox.factory() as db: assert observer_events.consume_one(db)
    with inbox.factory() as db:
        assert not observer_events.consume_one(db)
        receipt=db.query(inbox.Event).filter_by(event_type='observer.analyzed').one()
        assert receipt.run_id==inbox.run_id
        assert receipt.payload['source_event_id']==key.hex
        assert not receipt.payload['finding']['escalate']
    call.assert_called_once()


def test_per_run_observer_off_and_on_without_change_use_no_llm(inbox,monkeypatch):
    monkeypatch.setattr(adaptive_config,'load',lambda:adaptive_config.AdaptiveConfig(enabled=False))
    call=Mock(return_value=({'text':json.dumps(OK),'model':'test-model'},'correlation'))
    monkeypatch.setattr(adaptive_ai,'call',call)
    inbox.emit('observer.configured',{'enabled':False})
    inbox.emit('file_changed',{'file':'app/endpoint.py'})
    with inbox.factory() as db:
        assert not observer_events.consume_one(db)
    call.assert_not_called()
    inbox.emit('observer.configured',{'enabled':True,'provider':'openai','model':'test-model'})
    with inbox.factory() as db:
        assert not observer_events.consume_one(db)
    call.assert_not_called()
    inbox.emit('file_changed',{'file':'app/endpoint.py'})
    with inbox.factory() as db:
        assert observer_events.consume_one(db)
        assert not observer_events.consume_one(db)
    call.assert_called_once()


def test_observer_off_does_not_pause_on_failure_event(inbox, monkeypatch):
    call = Mock(side_effect=AssertionError('AI forbidden'))
    monkeypatch.setattr(adaptive_ai, 'call', call)
    inbox.emit('observer.configured', {'enabled': False})
    inbox.emit('build.tests_failed', {'git_commit_sha': 'a'*40})
    with inbox.factory() as db:
        assert observer_events.consume_one(db)
        assert db.query(inbox.Event).filter_by(event_type='observer.pause').count() == 0
        receipt = db.query(inbox.Event).filter_by(event_type='observer.analyzed').one()
        assert receipt.payload['call']['skipped_by_user']
    call.assert_not_called()


def test_30_second_workspace_check_emits_only_on_relevant_change(inbox,monkeypatch):
    inbox.emit('observer.configured',{'enabled':True,'provider':'openai','model':'test-model'})
    inbox.emit('observer.workspace_snapshot',{'fingerprint':'same'})
    values=iter([{'fingerprint':'same','paths':[]},
                 {'fingerprint':'changed','paths':['app/endpoint.py']}])
    monkeypatch.setattr(observer_workspace,'snapshot',lambda:next(values))
    with inbox.factory() as db:
        observer_workspace.poll(db)
        assert db.query(inbox.Event).filter_by(event_type='file_changed').count()==0
        observer_workspace.poll(db)
        event=db.query(inbox.Event).filter_by(event_type='file_changed').one()
        assert event.payload['paths']==['app/endpoint.py']


def test_failure_bypasses_model_and_remains_auditable(inbox,monkeypatch):
    inbox.emit('build.tests_failed',{'git_commit_sha':'a'*40})
    inbox.emit('file_changed')
    call=Mock(side_effect=AssertionError('AI forbidden'))
    monkeypatch.setattr(adaptive_ai,'call',call)
    with inbox.factory() as db:
        assert observer_events.consume_one(db)
        assert observer_events.consume_one(db)
        assert db.query(inbox.Event).filter_by(event_type='observer.escalation_requested').count()==2
        assert db.get(inbox.Run,inbox.run_id).status=='blocked'
        pause=db.query(inbox.Event).filter_by(event_type='observer.pause').one()
        assert pause.payload['action']=='PAUSE'
        assert pause.payload['evidence']['category']=='gate_failure'
        assert run_pause.is_paused(db,inbox.run_id)
    call.assert_not_called()


def test_pause_requires_explicit_resume_and_restores_previous_status(inbox):
    with inbox.factory() as db:
        run_pause.request_pause(db,inbox.run_id,reason='Risco simulado',
                                evidence={'source_event_id':'test'})
        with pytest.raises(run_pause.RunPaused):
            run_pause.assert_run_can_continue(db,inbox.run_id)
        assert db.get(inbox.Run,inbox.run_id).status=='blocked'
        assert db.query(inbox.Event).filter_by(event_type='observer.resumed').count()==0
    with inbox.factory() as db:
        run_pause.resume_paused_run(db,inbox.run_id,actor='operator',reason='Revisado')
        assert run_pause.assert_run_can_continue(db,inbox.run_id).status=='running'
        assert not run_pause.is_paused(db,inbox.run_id)
        assert db.query(inbox.Event).filter_by(event_type='observer.resumed').count()==1


def test_paused_run_refuses_next_controlled_send(inbox, monkeypatch):
    monkeypatch.setattr('app.database.SessionLocal', inbox.factory)
    with inbox.factory() as db:
        run_pause.request_pause(db, inbox.run_id, reason='Risco simulado', evidence={'test': True})
    sent = []
    with pytest.raises(run_pause.RunPaused):
        with run_pause.checked_work_unit(inbox.run_id):
            sent.append('next prompt')
    assert sent == []
    with inbox.factory() as db:
        run_pause.resume_paused_run(db, inbox.run_id, actor='operator', reason='Revisado')
    with run_pause.checked_work_unit(inbox.run_id):
        sent.append('next prompt')
    assert sent == ['next prompt']


def test_pause_persists_while_current_long_stage_finishes(inbox, monkeypatch):
    monkeypatch.setattr('app.database.SessionLocal', inbox.factory)
    with run_pause.run_checkpoint(inbox.run_id):
        with inbox.factory() as db:
            run_pause.request_pause(db, inbox.run_id, reason='Risco durante o gate',
                                    evidence={'stage': 'gate'})
        # The stage already started and may finish; the next one is refused.
    with pytest.raises(run_pause.RunPaused):
        with run_pause.run_checkpoint(inbox.run_id):
            pytest.fail('New stage started after PAUSE')


def test_worker_restart_after_attempt_never_replays_paid_inference(inbox,monkeypatch):
    source=inbox.emit('file_changed')
    inbox.emit('observer.attempt',{'source_event_id':source.hex})
    call=Mock(side_effect=AssertionError('Replay'))
    monkeypatch.setattr(adaptive_ai,'call',call)
    with inbox.factory() as db:
        assert observer_events.consume_one(db)
        row=db.query(inbox.Event).filter_by(event_type='observer.analyzed').one()
        assert row.payload['finding']['category']=='missing_evidence'
    call.assert_not_called()


@pytest.mark.parametrize('level,expected',[('LOW','NO_REVIEW_COMPLETE'),('MEDIUM','NO_REVIEW_COMPLETE'),('HIGH','REVISAR'),('CRITICAL','REVISAR')])
def test_final_policy_matrix_uses_persisted_decision(inbox,level,expected):
    with inbox.factory() as db:
        run=db.get(inbox.Run,inbox.run_id);run.complexity=level.lower()
        policy=decide_supervision(decision(level),level)
        event=db.query(inbox.Event).filter_by(event_type='routing.jev_decision').one()
        event.payload={'policy':policy.model_dump(mode='json')};db.commit()
        legacy=decide('low' if level in ('LOW','MEDIUM') else 'high','trusted','pass',executor='codex')
        result=adaptive_review.apply(db,run,legacy,finding=OK)
        assert result.decision==expected
        assert 'codex' not in result.reviewer_candidates


def test_medium_pending_or_alert_cannot_complete(inbox):
    with inbox.factory() as db:
        run=db.get(inbox.Run,inbox.run_id)
        legacy=decide('low','trusted','pass')
        assert adaptive_review.apply(db,run,legacy,pending=True).decision=='REVISAR'
        assert adaptive_review.apply(db,run,legacy,finding={'escalate':True,'severity':'high'}).decision=='REVISAR'
        failed=decide('low','trusted','fail')
        assert adaptive_review.apply(db,run,failed,finding=OK).decision=='NO_REVIEW_GATE_FAIL'


def test_human_approval_is_sovereign(inbox):
    with inbox.factory() as db:
        run=db.get(inbox.Run,inbox.run_id)
        policy=decide_supervision(decision('LOW',human='YES'),'LOW',mandatory_human=True)
        event=db.query(inbox.Event).filter_by(event_type='routing.jev_decision').one()
        event.payload={'policy':policy.model_dump(mode='json')}
        plan=db.get(inbox.Plan,run.plan_id);plan.approved_at=None;db.commit()
        result=adaptive_review.apply(db,run,decide('low','trusted','pass'),finding=OK)
        assert result.decision=='BLOCKED_OPERATIONAL'


def test_prior_finding_cannot_be_erased_by_later_ok(inbox):
    first=inbox.emit('file_changed')
    final=inbox.emit('observer.review_requested')
    inbox.emit('observer.analyzed',{'source_event_id':first.hex,'finding':{'escalate':True}})
    last=inbox.emit('observer.analyzed',{'source_event_id':final.hex,'finding':OK})
    with inbox.factory() as db:
        result=observer_events.aggregate(db,db.get(inbox.Run,inbox.run_id),db.get(inbox.Event,last))
        assert result['escalate']


@pytest.mark.parametrize('level',['HIGH','CRITICAL'])
def test_operator_decline_wins_over_adaptive_review_after_observer(inbox,level):
    """Revisão é recomendação: o "Não" do operador vale em qualquer risco."""
    with inbox.factory() as db:
        run=db.get(inbox.Run,inbox.run_id);run.complexity=level.lower()
        policy=decide_supervision(decision(level),level)
        event=db.query(inbox.Event).filter_by(event_type='routing.jev_decision').one()
        event.payload={'policy':policy.model_dump(mode='json')}
        db.add(inbox.Event(run_id=run.id,event_type='build.review_preference',payload={'requested':False}))
        db.commit()
        legacy=decide('high','trusted','pass',executor='codex')
        # Observer ligado e pendente: ainda espera a observação.
        assert adaptive_review.apply(db,run,legacy,pending=True).decision=='REVISAR'
        result=adaptive_review.apply(db,run,legacy,finding={'escalate':True,'severity':'high'})
        assert result.decision=='NO_REVIEW_COMPLETE'
        assert 'dispensada pelo operador' in result.justification
        assert 'high' in result.justification
        # Gate reprovado nunca é dispensado.
        assert adaptive_review.apply(db,run,decide('high','trusted','fail'),finding=OK).decision=='NO_REVIEW_GATE_FAIL'
