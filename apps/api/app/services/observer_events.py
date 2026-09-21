"""AgentRunEvent já existente como inbox/recibos duráveis, consumido pelo Build worker.

Nenhum event bus, watcher, fila/tabela paralela ou processo executor é introduzido.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import String, cast, exists, func
from sqlalchemy.orm import aliased
from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.backlog import BacklogItem
from app.services import adaptive_config, adaptive_review, run_observer


def pending_query(db):
    receipt = aliased(AgentRunEvent)
    received = exists().where(receipt.run_id == AgentRunEvent.run_id,
        receipt.event_type == 'observer.analyzed',
        receipt.payload['source_event_id'].as_string() == func.replace(cast(AgentRunEvent.id, String), '-', ''))
    configured = aliased(AgentRunEvent)
    has_policy = exists().where(configured.run_id == AgentRunEvent.run_id,
        configured.event_type == 'routing.jev_decision')
    return db.query(AgentRunEvent).filter(AgentRunEvent.event_type.in_(run_observer.RELEVANT),
        ~received, has_policy).order_by(AgentRunEvent.created_at, AgentRunEvent.id)


def aggregate(db, run, source):
    """Achado não pode ser apagado por um OK posterior. Evidência pendente bloqueia dispensa."""
    if pending_query(db).filter(AgentRunEvent.run_id == run.id).first():
        return None
    rows = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.analyzed').all()
    if any(row.payload.get('finding', {}).get('escalate') for row in rows):
        return {'escalate': True, 'severity': 'high'}
    return source.payload['finding']


def _consume(db, config):
    source = pending_query(db).with_for_update(skip_locked=True).first()
    if source is None:
        return recover_review(db)
    run = db.get(AgentRun, source.run_id)
    policy = adaptive_review.policy_for_run(db, run)
    if not policy:
        db.rollback()
        return False
    plan = db.get(ExecutionPlan, run.plan_id)
    task = db.get(BacklogItem, run.backlog_id)
    from app.services.test_gate import get_gate_evidence_for_run
    gate = get_gate_evidence_for_run(db, run)
    # Lê a última falha física diretamente também: ausência de um *pass válido*
    # não é permissão para perguntar à IA sobre uma falha, nem com evidência de SHA velho.
    latest_gate = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run.id,
        AgentRunEvent.event_type.in_(['build.tests_passed','build.tests_failed'])).order_by(AgentRunEvent.created_at.desc()).first()
    snapshot = {'run_id':str(run.id), 'task_id':str(run.backlog_id), 'plan_id':str(run.plan_id),
        'source_event_id':source.id.hex, 'event':source.event_type,
        'objective':plan.objective, 'scope':plan.scope, 'acceptance':plan.acceptance_criteria,
        'message':source.message, 'payload':source.payload,
        'gate_passed':bool(gate and gate.passed),
        'gate_failed':bool(latest_gate and latest_gate.event_type == 'build.tests_failed')}
    if snapshot['gate_failed'] and run.status in {'running', 'review'}:
        from app.services.handoff import update_run
        update_run(db, run, {'status': 'blocked', 'error': 'Gate físico reprovado; devolvido ao executor sem IA',
                            'message': 'Falha de gate determinístico bloqueia conclusão adaptativa'})
        db.commit()
    if (source.payload or {}).get('diff_truncated'):
        finding, metadata = run_observer.alert('missing_evidence', 'Diff excede o contexto limitado do observer; revisão obrigatória.'), {'deterministic':True}
    elif source.event_type in run_observer.FAILURES or snapshot['gate_failed']:
        finding, metadata = run_observer.alert('gate_failure', 'Falha física; sem chamada de IA.'), {'deterministic':True}
    elif source.event_type in run_observer.PASSIVE:
        finding, metadata = run_observer.ObserverFinding(status='ok', severity='none', scope='within', evidence_quality='good', escalate=False), {'deterministic':True}
    elif not policy.observer_required:
        finding, metadata = run_observer.ObserverFinding(status='ok', severity='none', scope='within', evidence_quality='good', escalate=False), {'skipped_by_policy':True}
    else:
        # Inclui todos os custos de forma conservadora, mesmo cobranças
        # desconhecidas/de erro, sem repetir inferência paga depois de um
        # restart sem marcador de tentativa persistido.
        attempts = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.attempt').count()
        marker = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.attempt').filter(
            AgentRunEvent.payload['source_event_id'].as_string() == source.id.hex).first()
        if marker:
            finding, metadata = run_observer.alert('missing_evidence', 'Observação interrompida; sem replay pago automático.'), {'deterministic':True}
        else:
            # Persiste a intenção antes da inferência. O file lock exclusivo cobre este commit.
            db.add(AgentRunEvent(run_id=run.id, event_type='observer.attempt',
                payload={'source_event_id':source.id.hex, 'timestamp':datetime.now(timezone.utc).isoformat()}))
            db.commit()
            finding, metadata = run_observer.analyze(db, config=config, event_type=source.event_type,
                snapshot=snapshot, project_id=task.project_id,
                run_cost=Decimal(attempts) * config.max_cost_usd * 2)
    receipt = AgentRunEvent(run_id=run.id, event_type='observer.analyzed',
        message='Observação somente leitura; backend mantém a autoridade de transição',
        payload={'source_event_id':source.id.hex, 'commit_sha':run.commit_sha,
                 'finding':finding.model_dump(mode='json'), 'call':metadata,
                 'timestamp':datetime.now(timezone.utc).isoformat()})
    db.add(receipt)
    db.commit()
    # Um achado pede revisão; nunca aprova uma run nem dispensa gates.
    if finding.escalate:
        db.add(AgentRunEvent(run_id=run.id, event_type='observer.escalation_requested',
            payload={'source_event_id':source.id.hex, 'category':finding.category, 'severity':finding.severity}))
        db.commit()
    request = db.query(AgentRunEvent).filter_by(run_id=run.id, event_type='observer.review_requested').order_by(AgentRunEvent.created_at.desc()).first()
    if request:
        combined = aggregate(db, run, receipt)
        if combined is not None:
            adaptive_review.settle(db, run, request, combined)
    return True


def recover_review(db):
    requests = db.query(AgentRunEvent).join(AgentRun, AgentRun.id == AgentRunEvent.run_id).filter(
        AgentRun.status == 'review', AgentRunEvent.event_type == 'observer.review_requested').order_by(AgentRunEvent.created_at.desc()).limit(100).all()
    for source in requests:
        settled = db.query(AgentRunEvent).filter_by(run_id=source.run_id, event_type='observer.settled').filter(
            AgentRunEvent.payload['source_event_id'].as_string() == source.id.hex).first()
        if settled:
            continue
        receipt = db.query(AgentRunEvent).filter_by(run_id=source.run_id, event_type='observer.analyzed').filter(
            AgentRunEvent.payload['source_event_id'].as_string() == source.id.hex).first()
        if receipt:
            run = db.get(AgentRun, source.run_id)
            combined = aggregate(db, run, receipt)
            if combined is not None:
                adaptive_review.settle(db, run, source, combined)
                return True
    db.rollback()
    return False


def consume_one(db):
    config = adaptive_config.load()
    if not config.enabled:
        return False
    from app.services.agent_snapshot import file_lock
    from app.services.agent_lifecycle import GROUPS_FILE
    # Separado dos locks de run/agente do lifecycle: inferência não pode travar ação de CLI.
    try:
        with file_lock(GROUPS_FILE.parent / 'observer-inference.lock', blocking=False):
            return _consume(db, config)
    except BlockingIOError:
        db.rollback()
        return False
