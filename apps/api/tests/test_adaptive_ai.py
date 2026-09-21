from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from uuid import uuid4
from app.services import adaptive_ai, adaptive_config, ai_cost_guard


@pytest.fixture
def transport(monkeypatch):
    from app.routers import ai
    client=Mock()
    client.with_options.return_value=client
    monkeypatch.setattr(ai,'get_openai',Mock(return_value=client))
    monkeypatch.setattr(ai_cost_guard,'policy_for',lambda *args: ai_cost_guard.ModelPolicy('openrouter','test','economic',Decimal('.042'),Decimal(0)))
    monkeypatch.setattr(ai_cost_guard,'enforce_budgets',lambda *args,**kw:None)
    monkeypatch.delenv('AI_MAX_COST_PER_CALL_USD',raising=False)
    db=Mock()
    db.get.return_value=SimpleNamespace(context_classification='internal')
    return client, db


def test_jev_uses_existing_client_decisions_endpoint_and_audits_actual_model(transport):
    client,db=transport
    client.post.return_value={'model':'typesafe/jev-1.13-20260917','usage':{'input_tokens':476,'output_tokens':70,'cost':.00002}}
    result,correlation=adaptive_ai.call(db,config=adaptive_config.AdaptiveConfig(),
        selection=adaptive_config.ObserverModel(provider='openrouter',model='typesafe/jev-1.13'),
        task_type='jev_decision',project_id=uuid4(),body={'questions':{},'state':{}},decisions=True,
        audit_context={'run_id':'run-1','task_id':'task-1','plan_id':'plan-1'})
    assert client.post.call_args.args[0]=='https://openrouter.ai/api/alpha/decisions'
    log=db.add.call_args.args[0]
    assert log.selected_model==result['model'] and log.input_tokens==476 and log.actual_cost_usd==.00002
    assert 'run-1' in log.selection_reason and str(log.correlation_id)==correlation


def test_observer_has_no_tools_or_action_dispatch(transport):
    client,db=transport
    client.chat.completions.create.return_value=SimpleNamespace(model='actual',usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))])
    adaptive_ai.call(db,config=adaptive_config.AdaptiveConfig(),
        selection=adaptive_config.ObserverModel(provider='gemini',model='flash'),
        task_type='run_observer',project_id=uuid4(),body={'system':'read-only','context':'event'})
    args=client.chat.completions.create.call_args.kwargs
    assert 'tools' not in args and 'functions' not in args
    assert args['response_format']=={'type':'json_object'}


def test_unknown_price_blocks_before_network_and_is_audited(transport,monkeypatch):
    client,db=transport
    monkeypatch.setattr(ai_cost_guard,'policy_for',lambda *a:ai_cost_guard.ModelPolicy('openai','unknown','economic',None,None))
    # match por exc.value.code, não pelo texto da mensagem (agora em
    # português): o código é o contrato estável entre guarda e chamador.
    with pytest.raises(ai_cost_guard.CostGuardError) as exc_info:
        adaptive_ai.call(db,config=adaptive_config.AdaptiveConfig(),selection=adaptive_config.ObserverModel(provider='openai',model='unknown'),task_type='run_observer',project_id=uuid4(),body={})
    assert exc_info.value.code=='unknown_price'
    client.chat.completions.create.assert_not_called()
    assert not db.add.call_args.args[0].success


def test_cumulative_budget_denial_has_no_model_call(transport):
    client,db=transport
    with pytest.raises(ai_cost_guard.CostGuardError) as exc_info:
        adaptive_ai.call(db,config=adaptive_config.AdaptiveConfig(),selection=adaptive_config.ObserverModel(provider='openrouter',model='test'),task_type='run_observer',project_id=uuid4(),body={},run_cost=Decimal('1'))
    assert exc_info.value.code=='adaptive_budget_exceeded'
    client.post.assert_not_called()
    client.chat.completions.create.assert_not_called()


def test_lint_failure_is_mandatory(monkeypatch):
    from app.services import test_gate
    monkeypatch.setattr('shutil.which',lambda _: '/usr/bin/pnpm')
    monkeypatch.setattr(test_gate,'_run_command',lambda *a,**kw:(1,'6 errors','',10))
    result=test_gate._check_lint()
    assert not result.passed and result.mandatory


def test_real_sdk_decodes_decisions_json(transport,monkeypatch):
    import httpx
    from openai import OpenAI
    from app.routers import ai
    _,db=transport
    seen=[]
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200,json={'model':'typesafe/jev-1.13-20260917','answers':{},'usage':{'input_tokens':123}})
    client=OpenAI(api_key='test-only',base_url='https://openrouter.ai/api/v1',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(ai,'get_openai',lambda *a:client)
    try:
        result,_=adaptive_ai.call(db,config=adaptive_config.AdaptiveConfig(),selection=adaptive_config.ObserverModel(provider='openrouter',model='typesafe/jev-1.13'),task_type='jev_decision',project_id=uuid4(),body={'questions':{},'state':{}},decisions=True)
        assert result['model']=='typesafe/jev-1.13-20260917'
        assert seen==['https://openrouter.ai/api/alpha/decisions']
    finally: client.close()
