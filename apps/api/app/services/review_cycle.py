"""Ciclo de revisão: avaliação de decisão persistida + métricas.

Gates executam ANTES — este módulo só lê a evidência persistida
(get_gate_evidence_for_run). Classificação de risco usa o diff real da run.
Nada aqui executa LLM: a decisão é determinística e auditável.
"""
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent
from app.models.review_cycle import ReviewCycle
from app.services.review_policy import PolicyDecision, classify_risk, decide, load_config

REPO_ROOT = Path('/opt/workdev')
_TOKEN_BYTES_PER_TOKEN = 4


def collect_diff_stats(run: AgentRun, root: Path = REPO_ROOT) -> tuple[list[str], str]:
    """Diff real da branch da run contra a base do projeto. Falha retorna vazio —
    risco sobe por volume zero? Não: volume vazio rebaixa; escopo sensível vem
    de paths persistidos no PLAN quando diff indisponível."""
    base = 'origin/develop'
    try:
        files = subprocess.run(
            ['git', 'diff', '--name-only', f'{base}...HEAD'],
            cwd=root, capture_output=True, text=True, timeout=30, check=False,
        )
        if files.returncode != 0:
            files = subprocess.run(
                ['git', 'diff', '--name-only', 'develop...HEAD'],
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
        text = subprocess.run(
            ['git', 'diff', f'{base}...HEAD'],
            cwd=root, capture_output=True, text=True, timeout=60, check=False,
        )
        names = [line.strip() for line in files.stdout.splitlines() if line.strip()]
        return names, text.stdout if text.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return [], ''


def trust_of(run: AgentRun, config: dict) -> str:
    return 'trusted' if run.agent in config.get('trusted_agents', []) else 'supervised'


class _DiffView:
    def __init__(self, files: list[str], text: str):
        self.files = files
        self.text = text


def evaluate_for_run(run: AgentRun, gate_result: str,
                     config: dict | None = None) -> tuple[PolicyDecision, _DiffView]:
    """Decisão determinística da run: risco (diff) + trust (config) + gate."""
    config = config or load_config()
    files, diff_text = collect_diff_stats(run)
    assessment = classify_risk(files, diff_text, getattr(run, 'complexity', None), config)
    decision = decide(
        assessment.risk, trust_of(run, config), gate_result,
        sensitive=assessment.sensitive,
        complexity=getattr(run, 'complexity', None),
        executor=run.agent, config=config,
    )
    return decision, _DiffView(files, diff_text)


def persist_decision(db: Session, run: AgentRun, decision: PolicyDecision,
                     diff_files: int, diff_lines: int, context_bytes: int = 0) -> ReviewCycle:
    """Persiste o ciclo (métricas) e o evento auditável da decisão."""
    attempt = (run.review_attempts or 0) + 1
    cycle = ReviewCycle(
        run_id=run.id, attempt=attempt,
        decision=decision.decision, tier=decision.tier,
        task_risk=decision.task_risk, agent_trust=decision.agent_trust,
        gate_result=decision.gate_result, sensitive=decision.sensitive,
        justification=decision.justification,
        diff_files=diff_files, diff_lines=diff_lines,
        context_bytes=context_bytes,
        tokens_estimate=context_bytes // _TOKEN_BYTES_PER_TOKEN,
    )
    db.add(cycle)
    event = AgentRunEvent(
        run_id=run.id, event_type='build.review_decision',
        message=decision.justification,
        payload={
            'decision': decision.decision, 'tier': decision.tier,
            'task_risk': decision.task_risk, 'agent_trust': decision.agent_trust,
            'gate_result': decision.gate_result, 'sensitive': decision.sensitive,
            'diff_files': diff_files, 'diff_lines': diff_lines,
            'reviewer_candidates': decision.reviewer_candidates,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(cycle)
    return cycle


def close_cycle_with_verdict(db: Session, run: AgentRun, reviewer: str, verdict: str,
                             escalated: bool = False) -> ReviewCycle | None:
    """Fecha o ciclo aberto da tentativa atual; naïvete de SQLite é tolerada."""
    cycle = (db.query(ReviewCycle)
             .filter(ReviewCycle.run_id == run.id)
             .order_by(ReviewCycle.attempt.desc()).first())
    if cycle is None or cycle.verdict is not None:
        return None
    now = datetime.now(timezone.utc)
    cycle.reviewer_agent = reviewer
    cycle.verdict = verdict
    cycle.escalated = escalated
    cycle.closed_at = now
    if cycle.created_at:
        created = cycle.created_at if cycle.created_at.tzinfo else cycle.created_at.replace(tzinfo=timezone.utc)
        cycle.duration_ms = int((now - created).total_seconds() * 1000)
    db.commit()
    return cycle
