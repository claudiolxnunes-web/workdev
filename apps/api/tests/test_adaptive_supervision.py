import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from app.services.supervision_policy import JevDecision, ObserverFinding, decide_supervision
from app.services import adaptive_config, adaptive_ai, jev_decision, run_observer


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
    p=decide_supervision(d, 'LOW', threshold=.65, mandatory_human=True)
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
