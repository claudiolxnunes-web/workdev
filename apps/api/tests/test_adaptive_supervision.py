import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from app.services.supervision_policy import JevDecision, ObserverFinding, decide_supervision
from app.services import adaptive_config, adaptive_ai, jev_decision, run_observer


@pytest.fixture
def adaptive_build(tmp_path, monkeypatch):
    """Real Session/commits; isolate PostgreSQL schema and provider transport.

    Keep queue_build, deterministic classification, Jev parsing, egress guard
    and audit linking real. Only the local dispatch queue is outside this test.
    """
    from decimal import Decimal
    from uuid import uuid4
    from sqlalchemy import Column, JSON, Table, create_engine
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB
    from sqlalchemy.orm import registry, sessionmaker
    from app.models import project
    from app.routers import ai
    from app.services import handoff, ai_cost_guard, local_code_build

    mapping = registry()
    models = {}
    for name, original in (
        ('Run', handoff.AgentRun), ('Event', handoff.AgentRunEvent),
        ('Task', handoff.BacklogItem), ('Project', project.Project),
        ('Log', adaptive_ai.AICallLog),
    ):
        model = type(name, (), {})
        columns = [Column(c.name, JSON() if isinstance(c.type, (JSONB, ARRAY)) else c.type,
                          primary_key=c.primary_key,
                          default=uuid4 if c.name == 'id' else None)
                   for c in original.__table__.columns]
        mapping.map_imperatively(model, Table(original.__tablename__, mapping.metadata, *columns))
        models[name] = model
    monkeypatch.setattr(handoff, 'AgentRun', models['Run'])
    monkeypatch.setattr(handoff, 'AgentRunEvent', models['Event'])
    monkeypatch.setattr(jev_decision, 'AgentRunEvent', models['Event'])
    monkeypatch.setattr(handoff, 'BacklogItem', models['Task'])
    monkeypatch.setattr(project, 'Project', models['Project'])
    monkeypatch.setattr(adaptive_ai, 'AICallLog', models['Log'])
    monkeypatch.setattr(handoff, 'load_subtasks', lambda *_: [])
    enqueue = Mock()
    monkeypatch.setattr(local_code_build, 'enqueue', enqueue)
    config = adaptive_config.AdaptiveConfig(enabled=True)
    monkeypatch.setattr(adaptive_config, 'load', lambda: config)
    client = Mock()
    client.with_options.return_value = client
    answers = {key: {'type': 'choice', 'choice': label, 'confidence': .95,
                    'probabilities': {option: float(option == label)
                                      for option in jev_decision.QUESTIONS[key]['criteria']}}
               for key, label in [('complexity', 'LOW'), ('supervision', 'NONE'), ('human_approval', 'NO')]}
    answers['decompose'] = {'type': 'noul', 'noul': .1}
    client.post.return_value = {'model': 'typesafe/jev-1.13', 'answers': answers}
    get_client = Mock(return_value=client)
    monkeypatch.setattr(ai, 'get_openai', get_client)
    monkeypatch.setattr(ai_cost_guard, 'policy_for', lambda *a: ai_cost_guard.ModelPolicy(
        'openrouter', 'typesafe/jev-1.13', 'economic', Decimal('.042'), Decimal(0)))
    monkeypatch.setattr(ai_cost_guard, 'enforce_budgets', lambda *a, **kw: None)
    monkeypatch.delenv('AI_MAX_COST_PER_CALL_USD', raising=False)
    classify = Mock(wraps=jev_decision.classify)
    monkeypatch.setattr(jev_decision, 'classify', classify)
    engine = create_engine(f'sqlite:///{tmp_path}/adaptive-build.db')
    mapping.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as db:
            project_row = models['Project'](id=uuid4(), context_classification='internal')
            task = models['Task'](id=uuid4(), project_id=project_row.id, title='Ajustar texto')
            db.add_all([project_row, task])
            db.commit()
            plan = SimpleNamespace(id=uuid4(), backlog_id=task.id, status='approved',
                objective='Ajustar texto', scope='Texto de ajuda', constraints=[], acceptance_criteria=[])
            yield SimpleNamespace(db=db, factory=factory, plan=plan, project=project_row,
                config=config, classify=classify, client=client, get_client=get_client,
                enqueue=enqueue, handoff=handoff, **models)
    finally:
        engine.dispose()
        mapping.dispose()


@pytest.mark.parametrize('agent', ['local-code', 'codex'])
def test_build_calls_jev_for_internal_project_and_links_persisted_event(adaptive_build, agent):
    env = adaptive_build
    run, _ = env.handoff.queue_build(env.db, env.plan, agent, reviewer='gemini')
    env.classify.assert_called_once()
    env.client.post.assert_called_once()
    assert run.agent != run.reviewer_agent
    assert env.classify.call_args.kwargs['deterministic_complexity'] == 'low'
    with env.factory() as db:
        event = db.query(env.Event).filter_by(event_type='routing.jev_decision').one()
        assert event.run_id == run.id
        assert event.payload['run_id'] == str(run.id)
        assert not event.payload['policy']['conservative_fallback']
        assert db.get(env.Run, run.id).status == 'queued'
        assert db.query(env.Log).one().success
    if agent == 'local-code':
        env.enqueue.assert_called_once_with(env.db, run)


@pytest.mark.parametrize('agent', ['local-code', 'codex'])
def test_build_disabled_never_calls_jev(adaptive_build, agent):
    env = adaptive_build
    env.config.enabled = False
    run, _ = env.handoff.queue_build(env.db, env.plan, agent, reviewer='gemini')
    assert run.status == 'queued'
    env.classify.assert_not_called()
    env.get_client.assert_not_called()
    assert env.db.query(env.Event).filter_by(event_type='routing.jev_decision').count() == 0


@pytest.mark.parametrize('failure', ['restricted', 'timeout', 'provider_error'])
def test_local_build_falls_back_and_audits_without_blocking_creation(adaptive_build, failure):
    env = adaptive_build
    if failure == 'restricted':
        env.project.context_classification = 'restricted'
        env.db.commit()
    else:
        env.client.post.side_effect = TimeoutError() if failure == 'timeout' else RuntimeError()
    run, _ = env.handoff.queue_build(env.db, env.plan, 'local-code', reviewer='gemini')
    assert run.status == 'queued' and run.complexity == 'high'
    assert run.agent != run.reviewer_agent
    with env.factory() as db:
        event = db.query(env.Event).filter_by(event_type='routing.jev_decision').one()
        assert event.run_id == run.id and event.payload['run_id'] == str(run.id)
        assert event.payload['policy']['conservative_fallback']
        assert event.payload['policy']['review_required']
        log = db.query(env.Log).one()
        assert not log.success
        assert log.error_type == event.payload['error']
        assert log.error_type == {'restricted': 'ValueError', 'timeout': 'TimeoutError',
                                  'provider_error': 'RuntimeError'}[failure]
    if failure == 'restricted':
        env.get_client.assert_not_called()
        env.client.post.assert_not_called()


def test_build_still_rejects_executor_as_reviewer_before_jev(adaptive_build):
    env = adaptive_build
    with pytest.raises(env.handoff.HandoffError):
        env.handoff.queue_build(env.db, env.plan, 'codex', reviewer='codex')
    env.classify.assert_not_called()
    assert env.db.query(env.Run).count() == 0


def test_local_build_jev_cannot_lower_explicit_deterministic_floor(adaptive_build):
    env = adaptive_build
    run, _ = env.handoff.queue_build(env.db, env.plan, 'local-code', reviewer='gemini',
                                    complexity='critical')
    assert run.complexity == 'critical'
    assert env.classify.call_args.kwargs['mandatory_human']


def decision(level='MEDIUM', confidence=.95, supervision='NONE', **kw):
    return JevDecision(complexity=level, complexity_confidence=confidence,
        supervision=supervision, supervision_confidence=confidence,
        decompose_score=kw.get('decompose', .2), human_approval=kw.get('human','NO'),
        human_approval_confidence=confidence, probabilities={})


@pytest.mark.parametrize('level,observer,review', [('LOW',False,False),('MEDIUM',True,False),('HIGH',True,True),('CRITICAL',True,True)])
def test_policy_matrix(level, observer, review):
    policy=decide_supervision(decision(level), level)
    assert (policy.observer_required, policy.review_required)==(observer, review)


@pytest.mark.parametrize('confidence', [0,.5,.749])
def test_uncertainty_cannot_waive_review(confidence):
    policy=decide_supervision(decision('LOW',confidence), 'LOW')
    assert policy.review_required and policy.conservative_fallback


def test_configurable_threshold_and_multidimensional_policy():
    d=decision('LOW',.7, 'OBSERVER_AND_REVIEWER', human='YES', decompose=.9)
    p=decide_supervision(d, 'LOW', threshold=.65, human_approval_threshold=.65, mandatory_human=True)
    assert p.observer_required and p.review_required and p.human_approval_required
    assert p.human_approval_recommended and p.decompose_recommended
    assert not p.conservative_fallback


def test_jev_cannot_lower_deterministic_critical():
    assert decide_supervision(decision('LOW'), 'critical').complexity == 'CRITICAL'


def test_none_model_falls_back_conservatively():
    assert decide_supervision(None, 'low').review_required


def test_observer_rejects_action_fields_and_inconsistent_ok():
    with pytest.raises(ValidationError):
        ObserverFinding(status='ok', severity='none', scope='within', evidence_quality='good', escalate=False, command='rm')
    with pytest.raises(ValidationError):
        ObserverFinding(status='ok', severity='high', escalate=False)


@pytest.mark.parametrize('event', sorted(run_observer.FAILURES))
def test_physical_failure_never_calls_ai(event, monkeypatch):
    inference=Mock(side_effect=AssertionError('AI after failed gate'))
    monkeypatch.setattr(adaptive_ai,'call',inference)
    finding, metadata=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),
        event_type=event, snapshot={},project_id=None)
    assert finding.escalate and metadata['deterministic']
    inference.assert_not_called()


@pytest.mark.parametrize('event', ['file_changed','executor_waiting','scope_changed','observer.review_requested'])
def test_existing_failed_gate_suppresses_ai_on_other_events(event,monkeypatch):
    inference=Mock()
    monkeypatch.setattr(adaptive_ai,'call',inference)
    result,_=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),event_type=event,
        snapshot={'gate_failed':True},project_id=None)
    assert result.escalate
    inference.assert_not_called()


def test_irrelevant_event_ignored(monkeypatch):
    inference=Mock()
    monkeypatch.setattr(adaptive_ai,'call',inference)
    result,meta=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),event_type='terminal.cursor',snapshot={},project_id=None)
    assert result is None and meta['ignored']
    inference.assert_not_called()


def test_unsupported_completion_deterministic():
    result,_=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),event_type='run_completed',snapshot={},project_id=None)
    assert result.category=='unsupported_success_claim'


@pytest.mark.parametrize('category',['scope_violation','unexpected_architecture_change','security_risk'])
def test_findings_escalate_without_executing_actions(category,monkeypatch):
    response={'status':'alert','severity':'high','category':category,'finding':'Outside approved behavior','evidence':'app/auth.py','escalate':True}
    monkeypatch.setattr(adaptive_ai,'call',Mock(return_value=({'model':'real-version','text':json.dumps(response),'usage':{'cost':.001}},'id')))
    result,meta=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),event_type='file_changed',snapshot={},project_id=None)
    assert result.escalate and meta['actual_model']=='real-version'


def test_fallback_is_configured_and_normal_execution_can_be_clear(monkeypatch):
    ok={'status':'ok','severity':'none','scope':'within','evidence_quality':'good','escalate':False}
    inference=Mock(side_effect=[TimeoutError(),({'model':'fallback-real','text':json.dumps(ok)},'id')])
    monkeypatch.setattr(adaptive_ai,'call',inference)
    config=adaptive_config.AdaptiveConfig(primary={'provider':'openrouter','model':'primary'},fallback={'provider':'gemini','model':'configured-fallback'})
    result,meta=run_observer.analyze(Mock(),config=config,event_type='file_changed',snapshot={},project_id=None)
    assert not result.escalate and meta['fallback']
    assert inference.call_args.kwargs['selection'].model=='configured-fallback'


def test_invalid_model_output_fails_closed(monkeypatch):
    monkeypatch.setattr(adaptive_ai,'call',Mock(return_value=({'text':'{"command":"write_file"}'},'id')))
    result,_=run_observer.analyze(Mock(),config=adaptive_config.AdaptiveConfig(),event_type='scope_changed',snapshot={},project_id=None)
    assert result.escalate and result.category=='missing_evidence'


def test_jev_parses_actual_model_contract():
    answers={}
    for key,label in [('complexity','HIGH'),('supervision','REVIEWER'),('human_approval','NO')]:
        answers[key]={'type':'choice','choice':label,'confidence':.9,'probabilities':{option:float(option==label) for option in jev_decision.QUESTIONS[key]['criteria']}}
    answers['decompose']={'type':'noul','noul':.78}
    result=jev_decision.parse({'answers':answers})
    assert result.complexity=='HIGH' and result.decompose_score==.78
    answers['complexity']['probabilities']['LOW']=-1
    with pytest.raises(ValueError): jev_decision.parse({'answers':answers})
