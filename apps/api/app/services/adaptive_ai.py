"""Inferência somente leitura sobre clientes/catálogo/budgets do AI Hub. Sem execução de ferramentas."""
import json
import time
from decimal import Decimal
from uuid import uuid4
from typing import Any
from app.models.ai_routing import AICallLog
from app.services import ai_cost_guard
from app.services.context_redaction import redact


def bounded_text(value, limit=16000):
    return redact(str(value)).text[:limit]


def _as_content(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def call(db, *, config, selection, task_type, project_id, body, run_cost=Decimal(0), decisions=False, audit_context=None):
    from app.routers.ai import get_openai, get_anthropic
    provider, model = selection.provider, selection.model
    correlation = uuid4()
    started = time.monotonic()
    # policy/estimate entram no try: uma falha em policy_for (ex.: modelo
    # desativado no catálogo) precisa cair no finally e ser auditada em
    # AICallLog igual a qualquer outra recusa de guarda — antes ficavam de
    # fora do try/finally e a falha nunca era registrada.
    actual_model, usage, error, policy, estimate = model, {}, None, None, None
    try:
        policy = ai_cost_guard.policy_for(provider, model, db)
        # Mesma convenção de estimate_tokens(messages, system) do caminho
        # interativo (routers/ai.py): system separado do conteúdo, em vez de
        # json.dumps(body) inteiro virando um "message" sintético — isso
        # inflava a contagem com aspas/chaves e misturava metodologias entre
        # os dois caminhos que alimentam o mesmo AICallLog.
        system = _as_content(body.get('system', ''))
        messages = [{'content': _as_content(v)} for k, v in body.items() if k != 'system']
        estimate = ai_cost_guard.estimate_cost(
            policy, ai_cost_guard.estimate_tokens(messages, system), config.max_output_tokens)
        from app.models.project import Project
        project = db.get(Project, project_id) if project_id else None
        local = False
        if selection.runtime_id:
            from app.services import agent_runtimes
            runtime = agent_runtimes.get_runtime(selection.runtime_id)
            local = bool(runtime and runtime.kind != agent_runtimes.KIND_GPU)
        if not local and (project is None or project.context_classification != 'internal'):
            raise ValueError('Contexto remoto proibido para projeto restrito ou não identificado')
        if selection.runtime_id and not local:
            # Consentimento de runtime remoto é por run; usa a guarda canônica de egress.
            from app.models.handoff import AgentRun
            from app.services.context_egress import prepare
            from uuid import UUID
            run = db.get(AgentRun, UUID((audit_context or {})['run_id']))
            if run is None:
                raise ValueError('Runtime remoto exige uma run identificada')
            prepare(db, run, selection.runtime_id, json.dumps(body))
        if estimate is None:
            raise ai_cost_guard.CostGuardError('unknown_price', 'Preço do modelo obrigatório para observer limitado')
        if estimate > config.max_cost_usd or run_cost + estimate > config.max_run_cost_usd:
            raise ai_cost_guard.CostGuardError('adaptive_budget_exceeded', 'Orçamento da supervisão adaptativa esgotado')
        ai_cost_guard.require_premium_confirmation(policy, config.premium_confirmed, estimate)
        ai_cost_guard.enforce_per_call_limit(estimate)
        ai_cost_guard.enforce_budgets(db, provider=provider, project_id=project_id, estimated_cost=estimate)
        if decisions:
            # Mesmo provider/client/auth. Endpoint alpha é especificado pelo OpenAPI do OpenRouter.
            client = get_openai('openrouter').with_options(timeout=config.timeout_seconds, max_retries=0)
            response = client.post('https://openrouter.ai/api/alpha/decisions', cast_to=dict[str, Any],
                                   body={'model': model, **body})
        elif provider == 'anthropic':
            raw = get_anthropic().with_options(timeout=config.timeout_seconds, max_retries=0).messages.create(
                model=model, max_tokens=config.max_output_tokens,
                system=body['system'], messages=[{'role': 'user', 'content': body['context']}])
            response = {'model': raw.model, 'text': ''.join(c.text for c in raw.content if c.type == 'text'),
                        'usage': raw.usage.model_dump()}
        else:
            client = get_openai(provider, selection.runtime_id).with_options(timeout=config.timeout_seconds, max_retries=0)
            raw = client.chat.completions.create(model=model,
                **({'max_completion_tokens': config.max_output_tokens} if provider == 'openai' else {'max_tokens': config.max_output_tokens}),
                messages=[{'role': 'system', 'content': body['system']}, {'role': 'user', 'content': body['context']}],
                response_format={'type': 'json_object'})
            response = {'model': raw.model, 'text': raw.choices[0].message.content,
                        'usage': raw.usage.model_dump() if raw.usage else {}}
        actual_model = response.get('model') or model
        usage = response.get('usage') or {}
        return response, str(correlation)
    except Exception as exc:
        error = type(exc).__name__  # Sem corpo de resposta, headers de provider ou segredos na auditoria.
        raise
    finally:
        db.add(AICallLog(correlation_id=correlation, project_id=project_id,
            user_id='workdev-adaptive-policy', task_type=task_type,
            requested_mode='decisions' if decisions else 'observer',
            requested_model=model, selected_model=actual_model, provider=provider,
            selection_reason=json.dumps({'purpose': 'read-only adaptive supervision', **(audit_context or {})}),
            input_tokens=usage.get('input_tokens', usage.get('prompt_tokens')),
            output_tokens=usage.get('output_tokens', usage.get('completion_tokens')),
            actual_cost_usd=usage.get('cost'), estimated_cost_usd=estimate,
            duration_ms=int((time.monotonic()-started)*1000), success=error is None,
            # policy pode continuar None se policy_for() foi o que falhou —
            # is_free vira False (conservador) em vez de estourar AttributeError
            # e mascarar a falha original que o finally deveria estar auditando.
            error_type=error, is_free=(policy.is_free if policy else False),
            fallback_occurred=False))
        db.flush()
