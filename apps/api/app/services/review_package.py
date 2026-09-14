"""Pacote mínimo para o revisor: objetivo, aceite, diff, gates, decisão.

Nunca recria contexto completo; `expand=diff` é o único carregamento lazy
admitido. O tamanho do pacote mínimo entra no ciclo como context_bytes.
"""
import json
from types import SimpleNamespace
from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.review_cycle import ReviewCycle
from app.services.review_cycle import collect_diff_stats
from app.services.test_gate import get_gate_evidence_for_run


def build_package(db: Session, run: AgentRun, expand_diff: bool = False) -> dict:
    plan = db.get(ExecutionPlan, run.plan_id)
    cycle = (db.query(ReviewCycle)
             .filter(ReviewCycle.run_id == run.id)
             .order_by(ReviewCycle.attempt.desc()).first())
    evidence = get_gate_evidence_for_run(db, run)
    gate_sha = evidence.git_commit_sha if evidence else None
    run_sha = getattr(run, 'commit_sha', None)
    bound_sha = gate_sha if gate_sha and (not run_sha or run_sha == gate_sha) else None
    stats = collect_diff_stats(SimpleNamespace(commit_sha=bound_sha))
    if stats is None:
        files, diff_text = [], ''
        diff_unavailable = True
    else:
        files, diff_text = stats
        diff_unavailable = False
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
        'diff_unavailable': diff_unavailable,
        'run_id': str(run.id),
        'commit_sha': bound_sha,
        'gate': {'passed': evidence.passed if evidence else None,
                 'checks': [check.__dict__ for check in evidence.checks] if evidence else []},
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
