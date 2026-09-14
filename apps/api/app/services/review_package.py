"""Pacote mínimo para o revisor: objetivo, aceite, diff, gates, decisão.

Nunca recria contexto completo; `expand=diff` é o único carregamento lazy
admitido. O tamanho do pacote mínimo entra no ciclo como context_bytes.
"""
import json
from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.review_cycle import ReviewCycle
from app.services.review_cycle import collect_diff_stats


def build_package(db: Session, run: AgentRun, expand_diff: bool = False) -> dict:
    plan = db.get(ExecutionPlan, run.plan_id)
    cycle = (db.query(ReviewCycle)
             .filter(ReviewCycle.run_id == run.id)
             .order_by(ReviewCycle.attempt.desc()).first())
    gate_event = (db.query(AgentRunEvent)
                  .filter(AgentRunEvent.run_id == run.id,
                          AgentRunEvent.event_type.in_(('build.tests_passed', 'build.tests_failed')))
                  .order_by(AgentRunEvent.created_at.desc()).first())
    files, diff_text = collect_diff_stats(run)
    package = {
        'objective': plan.objective if plan else None,
        'title': plan.title if plan else None,
        'acceptance_criteria': plan.acceptance_criteria if plan else [],
        'constraints': plan.constraints if plan else [],
        'executor_agent': run.agent,
        'executor_summary': run.summary,
        'files_changed': files,
        'diff_files': len(files),
        'diff_lines': diff_text.count('\n'),
        'gate': {'passed': gate_event.payload.get('passed') if gate_event else None,
                 'checks': gate_event.payload.get('checks') if gate_event else []},
        'decision': (cycle.decision if cycle else None),
        'tier': (cycle.tier if cycle else None),
        'sensitive': (cycle.sensitive if cycle else []),
        'expand_options': ['diff'],
    }
    if expand_diff:
        package['diff'] = diff_text
    return package


def package_bytes(package: dict) -> int:
    return len(json.dumps(package, ensure_ascii=False, default=str).encode())
