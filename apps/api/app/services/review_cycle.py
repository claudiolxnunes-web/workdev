"""Ciclo de revisão: avaliação de decisão persistida + métricas.

Gates executam ANTES — este módulo só lê a evidência persistida
(get_gate_evidence_for_run). Classificação de risco usa o diff real da run.
Nada aqui executa LLM: a decisão é determinística e auditável.
"""
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent
from app.models.review_cycle import ReviewCycle
from app.services.review_policy import PolicyDecision, classify_risk, decide, load_config

REPO_ROOT = Path('/opt/workdev')
_TOKEN_BYTES_PER_TOKEN = 4


def collect_diff_stats(run: AgentRun, root: Path = REPO_ROOT) -> tuple[list[str], str] | None:
    """Diff vinculado ao SHA imutável da Run — o mesmo que o gate validou.

    Sem commit_sha persistido não há evidência: branch móvel não comparada ao
    gate e HEAD compartilhado nunca servem de fallback. Coleta parcial (arquivos
    ok, conteúdo falho) também é indisponibilidade, não "diff vazio".
    """
    target = getattr(run, 'commit_sha', None)
    if not target or not re.fullmatch(r'[0-9a-fA-F]{40}', target):
        return None
    base = 'origin/develop'
    try:
        files = subprocess.run(
            ['git', 'diff', '--name-only', f'{base}...{target}'],
            cwd=root, capture_output=True, text=True, timeout=30, check=False,
        )
        if files.returncode != 0:
            base = 'develop'
            files = subprocess.run(
                ['git', 'diff', '--name-only', f'{base}...{target}'],
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
        if files.returncode != 0:
            return None
        text = subprocess.run(
            ['git', 'diff', f'{base}...{target}'],
            cwd=root, capture_output=True, text=True, timeout=60, check=False,
        )
        if text.returncode != 0:
            return None
        names = [line.strip() for line in files.stdout.splitlines() if line.strip()]
        return names, text.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def trust_of(run: AgentRun, config: dict) -> str:
    return 'trusted' if run.agent in config.get('trusted_agents', []) else 'supervised'


class _DiffView:
    def __init__(self, files: list[str], text: str):
        self.files = files
        self.text = text


def evaluate_for_run(run: AgentRun, gate_result: str,
                     config: dict | None = None, *, gate_sha: str | None = None) -> tuple[PolicyDecision, _DiffView]:
    """Decisão determinística da run: risco (diff) + trust (config) + gate."""
    config = config or load_config()
    if gate_result != 'pass':
        return decide('high', trust_of(run, config), gate_result, config=config), _DiffView([], '')
    if gate_sha is not None:
        revision = getattr(run, 'commit_sha', None)
        if (not re.fullmatch(r'[0-9a-fA-F]{40}', gate_sha)
                or (revision and revision != gate_sha)):
            return decide('high', trust_of(run, config), 'revision_mismatch', config=config), _DiffView([], '')
        run.commit_sha = gate_sha
    stats = collect_diff_stats(run)
    if stats is None:
        decision = decide('high', trust_of(run, config), 'diff_unavailable', config=config)
        return decision, _DiffView([], '')
    files, diff_text = stats
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
