"""Autoridade do backend sobre os achados do Observer; reaproveita review policy e transições."""
from dataclasses import replace
from app.models.handoff import AgentRunEvent, ExecutionPlan
from app.services.supervision_policy import SupervisionPolicy


def policy_for_run(db, run):
    event = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='routing.jev_decision').order_by(AgentRunEvent.created_at.desc()).first()
    if event is None:
        return None
    return SupervisionPolicy.model_validate(event.payload['policy'])


def apply(db, run, decision, *, finding=None, pending=False):
    """Roda depois da política legada/preferência do usuário. Não pode enfraquecer regra soberana."""
    policy = policy_for_run(db, run)
    if not policy or decision.gate_result != 'pass' or decision.decision not in {'REVISAR','NO_REVIEW_COMPLETE'}:
        return decision
    if policy.human_approval_required:
        plan = db.get(ExecutionPlan, run.plan_id)
        if not plan or plan.status != 'approved' or not plan.approved_at:
            return replace(decision, decision='BLOCKED_OPERATIONAL', justification='Aprovação humana soberana do plano ausente')
    required = (policy.review_required or str(run.complexity).lower() in ('high','critical')
                or bool(decision.sensitive) or decision.agent_trust != 'trusted')
    preference = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='build.review_preference').order_by(AgentRunEvent.created_at.desc()).first()
    required |= bool(preference and preference.payload.get('requested') is True)
    if policy.observer_required and (pending or finding is None):
        return replace(decision, decision='REVISAR', justification='Observer pendente; sem dispensa de revisão',
                       tier=decision.tier if decision.tier != 'none' else 'economic')
    if required or (finding and finding.get('escalate')):
        from app.services.review_policy import decide
        return decide('high' if required or finding.get('severity') in ('high','critical') else 'medium',
            'supervised', 'pass', sensitive=decision.sensitive,
            complexity=run.complexity, executor=run.agent)
    return replace(decision, decision='NO_REVIEW_COMPLETE', tier='none', reviewer_candidates=[],
                   justification='LOW/MEDIUM autorizado: gates físicos verdes e evidência do Observer limpa')


def request_observation(db, run, decision, diff):
    if decision.gate_result != 'pass' or decision.decision not in {'REVISAR', 'NO_REVIEW_COMPLETE'}:
        return decision
    policy = policy_for_run(db, run)
    if not policy:
        return decision
    if not policy.observer_required:
        return apply(db, run, decision)
    from app.services.handoff import add_run_event
    from app.services.adaptive_ai import bounded_text
    # O chamador já coletou o diff imutável pelo caminho canônico de revisão.
    # O Observer só recebe dados; não tem capacidade de repositório ou shell.
    add_run_event(db, run, 'observer.review_requested', 'Snapshot final do evento aguardando observação somente leitura',
        {'commit_sha': run.commit_sha, 'base_sha': getattr(run, 'review_base_sha', None),
         'files': diff.files, 'diff': bounded_text(diff.text, 12000),
         'diff_truncated': len(diff.text) > 12000})
    return apply(db, run, decision, pending=True)


def exemption_current(db, run):
    """Revalida na conclusão: decisões antigas não podem esconder eventos pendentes novos."""
    if str(run.complexity).lower() in ('high', 'critical'):
        return False
    policy = policy_for_run(db, run)
    if policy is None:
        return True
    if policy.review_required:
        return False
    if policy.human_approval_required:
        plan = db.get(ExecutionPlan, run.plan_id)
        if not plan or plan.status != 'approved' or not plan.approved_at:
            return False
    if not policy.observer_required:
        return True
    from app.services.observer_events import pending_query
    if pending_query(db).filter(AgentRunEvent.run_id == run.id).first():
        return False
    receipts = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.analyzed').all()
    if any(row.payload.get('finding', {}).get('escalate') for row in receipts):
        return False
    requests = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.review_requested').all()
    return any(request.payload.get('commit_sha') == run.commit_sha and
               any(row.payload.get('source_event_id') == request.id.hex and
                   row.payload.get('finding', {}).get('status') == 'ok' for row in receipts)
               for request in requests)


def settle(db, run, source, finding):
    """O backend, não o Observer, aplica a máquina de estados de revisão já existente."""
    db.refresh(run, with_for_update=True)
    if run.status != 'review' or source.payload.get('commit_sha') != run.commit_sha:
        return
    from app.services.test_gate import get_gate_evidence_for_run
    evidence = get_gate_evidence_for_run(db, run)
    if not evidence or not evidence.passed or evidence.git_commit_sha != run.commit_sha:
        return
    from app.services.review_scope import load_base
    from app.services.review_cycle import evaluate_for_run, persist_decision
    from app.services.review_policy import changed_lines
    from app.services.handoff import update_run, swap_reviewer
    run.review_base_sha = load_base(db, run.id)
    decision, diff = evaluate_for_run(run, 'pass', gate_sha=evidence.git_commit_sha)
    decision = apply(db, run, decision, finding=finding)
    persist_decision(db, run, decision, len(diff.files), changed_lines(diff.text))
    if decision.decision == 'NO_REVIEW_COMPLETE':
        update_run(db, run, {'status':'completed', 'result':run.result or decision.justification,
                            'message':decision.justification})
    elif decision.decision == 'REVISAR':
        if decision.reviewer_candidates and run.reviewer_agent not in decision.reviewer_candidates:
            swap_reviewer(db, run, decision.reviewer_candidates[0], 'Escalonamento da supervisão adaptativa')
    elif decision.decision == 'BLOCKED_OPERATIONAL':
        update_run(db, run, {'status':'blocked', 'error':decision.justification})
    db.add(AgentRunEvent(run_id=run.id, event_type='observer.settled',
        payload={'source_event_id': source.id.hex, 'commit_sha': run.commit_sha, 'decision': decision.decision}))
    db.commit()


def can_waive(db, run):
    """Última guarda da máquina de estados: delega a exemption_current.

    Chegou a existir uma reimplementação independente aqui, que checava só o
    'observer.review_requested' mais recente e qualquer 'observer.analyzed'
    sem correlação — diferente de exemption_current, que exige que o recibo
    analisado tenha source_event_id apontando para o pedido específico daquele
    commit_sha. As duas podiam divergir para o mesmo estado do banco: um
    recibo de um pedido antigo (commit_sha desatualizado) fazia esta função
    devolver True mesmo sem observação real do commit atual. Delegar elimina
    a divergência por construção — uma só fonte de verdade para a correlação.
    """
    return exemption_current(db, run)
