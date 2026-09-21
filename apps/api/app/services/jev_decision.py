"""Adaptador das Decisions do Jev; roteamento do executor continua no agent router existente."""
from datetime import datetime, timezone
from app.models.handoff import AgentRunEvent
from app.services import adaptive_ai, adaptive_config
from app.services.supervision_policy import JevDecision, decide_supervision

# Instructions/criteria em inglês de propósito: viram prompt literal enviado
# ao endpoint alpha/decisions do OpenRouter, não texto de interface.
QUESTIONS = {
    'complexity': {'type': 'choice', 'instructions': 'Classify engineering risk and complexity, not wording length.',
        'criteria': {'LOW': 'Small isolated copy/docs change, no execution/security effect.',
                     'MEDIUM': 'Isolated backend/frontend behavior with tests.',
                     'HIGH': 'Cross-module, concurrency, persistence or architecture.',
                     'CRITICAL': 'Security, destructive migrations, production or critical operation.'}},
    'supervision': {'type': 'choice', 'instructions': 'Which supervision is warranted?',
        'criteria': {'NONE': 'Objective gates sufficient for isolated low risk.',
                     'OBSERVER': 'Event analysis sufficient unless anomalies arise.',
                     'REVIEWER': 'Independent reviewer required.',
                     'OBSERVER_AND_REVIEWER': 'Both event observation and independent review required.'}},
    'decompose': {'type': 'noul', 'instructions': 'Does this work need decomposition before execution?',
        'criteria': {'false': 'One cohesive bounded change.', 'true': 'Multiple independently verifiable phases or broad dependencies.'}},
    'human_approval': {'type': 'choice', 'instructions': 'Recommend human approval for irreversible/high-impact actions.',
        'criteria': {'YES': 'Destructive, financial, credential, production or irreversible action.',
                     'NO': 'Reversible isolated code changes without operational action.'}},
}


def parse(response):
    answers = response['answers']
    for key in ('complexity', 'supervision', 'human_approval'):
        item = answers[key]
        if item.get('type') != 'choice' or set(item['probabilities']) != set(QUESTIONS[key]['criteria']):
            raise ValueError('Escolhas do Jev inválidas')
        values = list(item['probabilities'].values())
        if any(not isinstance(v, (int,float)) or not 0 <= v <= 1 for v in values) or abs(sum(values)-1) > .05:
            raise ValueError('Probabilidades do Jev inválidas')
    return JevDecision(complexity=answers['complexity']['choice'],
        complexity_confidence=answers['complexity']['confidence'],
        supervision=answers['supervision']['choice'], supervision_confidence=answers['supervision']['confidence'],
        decompose_score=answers['decompose']['noul'], human_approval=answers['human_approval']['choice'],
        human_approval_confidence=answers['human_approval']['confidence'],
        probabilities={k: answers[k]['probabilities'] for k in ('complexity','supervision','human_approval')})


def classify(db, task, plan, *, deterministic_complexity, run_id=None, mandatory_review=False,
             mandatory_human=False, config=None):
    config = config or adaptive_config.load()
    identifiers = {'task_id': str(task.id), 'plan_id': str(plan.id), 'run_id': str(run_id) if run_id else None}
    # Sem repositório, dump de ADR, histórico de chat, env ou contexto de prompt irrestrito.
    state = {key: adaptive_ai.bounded_text(value, 3500) for key, value in {
        'title': task.title, 'objective': plan.objective, 'scope': plan.scope,
        'acceptance': plan.acceptance_criteria, 'constraints': plan.constraints}.items()}
    decision, response, error, correlation = None, {}, None, None
    try:
        response, correlation = adaptive_ai.call(db, config=config,
            selection=adaptive_config.ObserverModel(provider='openrouter', model=config.jev_model),
            task_type='jev_decision', project_id=task.project_id,
            body={'questions': QUESTIONS, 'state': state}, decisions=True,
            audit_context=identifiers)
        decision = parse(response)
    except Exception as exc:
        error = type(exc).__name__
    policy = decide_supervision(decision, deterministic_complexity,
        threshold=config.confidence_threshold, mandatory_review=mandatory_review, mandatory_human=mandatory_human)
    payload = {**identifiers, 'requested_model': config.jev_model, 'actual_model': response.get('model'),
        'decision': decision.model_dump(mode='json') if decision else None,
        'policy': policy.model_dump(mode='json'), 'usage': response.get('usage', {}),
        'correlation_id': correlation, 'error': error, 'timestamp': datetime.now(timezone.utc).isoformat()}
    event = AgentRunEvent(run_id=run_id, event_type='routing.jev_decision',
                          message=policy.reason, payload=payload)
    db.add(event)
    db.flush()
    return policy, event
