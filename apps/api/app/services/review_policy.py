"""Objetiva classificação de risco e decisão de revisão, sem opinião.

Determinísticas e honestas: só entram sinais computáveis da run (complexidade
persistida no PLAN, diff real do worktree, paths/content críticos) e um mapa de
confiança externo em `config/review-policy.json`. Nenhum agente/modelo é
hardcoded — roteamento da Fase 5 assina essa configuração.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

RISK_LEVELS = ('low', 'medium', 'high')
TRUST_LEVELS = ('trusted', 'supervised')
TIER_LEVELS = ('none', 'economic', 'strong')
DECISIONS = ('NO_REVIEW_COMPLETE', 'REVISAR', 'NO_REVIEW_GATE_FAIL', 'BLOCKED_OPERATIONAL')

_CONFIG_PATH = Path(__file__).resolve().parents[4] / 'config' / 'review-policy.json'
_DEFAULT_CONFIG = {
    'trusted_agents': ['codex', 'claude', 'kimi', 'qwen'],
    'tier_reviewers': {
        'economic': ['qwen'],
        'strong': ['codex', 'claude', 'kimi'],
    },
    'volume_medium_lines': 200,
    'volume_high_lines': 500,
}

SENSITIVE_PATH_RULES = {
    'auth': re.compile(r'(^|[/])auth[^/]*\.py$|auth[/]', re.I),
    'migration': re.compile(r'alembic|migrations/', re.I),
    'deploy': re.compile(r'deploy|sudoers|workdev-deploy', re.I),
    'security': re.compile(r'auth|secret|credential|token|crypto|session', re.I),
}
SENSITIVE_DIFF_KEYWORDS = {
    'concurrency': re.compile(r'\b(threading|Lock|asyncio|concurrent|race|tmux)\b'),
    'architecture': re.compile(r'\b(architecture|arquitetura)\b', re.I),
}


def load_config(path: Path | None = None) -> dict:
    target = path or _CONFIG_PATH
    if target.exists():
        data = json.loads(target.read_text())
    else:
        data = {}
    merged = {**_DEFAULT_CONFIG, **data}
    merged['tier_reviewers'] = {**_DEFAULT_CONFIG['tier_reviewers'], **data.get('tier_reviewers', {})}
    return merged


@dataclass
class RiskAssessment:
    risk: str
    sensitive: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def classify_risk(files: list[str], diff_text: str, complexity: str | None = None,
                  config: dict | None = None) -> RiskAssessment:
    """Escopo sensível NUNCA cai em low; volume só sobe risco."""
    config = config or load_config()
    sensitive: set[str] = set()
    for rel in files:
        for label, rule in SENSITIVE_PATH_RULES.items():
            if rule.search(rel):
                sensitive.add(label)
    for label, rule in SENSITIVE_DIFF_KEYWORDS.items():
        if rule.search(diff_text):
            sensitive.add(label)
    lines = diff_text.count('\n')
    reasons = []
    if sensitive:
        reasons.append(f'escopo sensível: {", ".join(sensitive)}')
    if complexity in ('high', 'critical'):
        reasons.append(f'complexidade {complexity}')
        if 'architecture' not in sensitive:
            sensitive.add('architecture')
        return RiskAssessment('high', sorted(sensitive), reasons)
    if sensitive:
        return RiskAssessment('high', sorted(sensitive), reasons)
    if lines >= config['volume_high_lines']:
        return RiskAssessment('high', sorted(sensitive), [f'volume {lines} linhas'])
    if lines >= config['volume_medium_lines']:
        return RiskAssessment('medium', sorted(sensitive), [f'volume {lines} linhas'])
    return RiskAssessment('low', sorted(sensitive), reasons or ['sem sinais sensíveis'])


@dataclass
class PolicyDecision:
    decision: str
    tier: str
    task_risk: str
    agent_trust: str
    gate_result: str
    sensitive: list[str]
    justification: str
    reviewer_candidates: list[str] = field(default_factory=list)


def decide(task_risk: str, agent_trust: str, gate_result: str, sensitive: list[str] | None = None,
           complexity: str | None = None, executor: str | None = None,
           config: dict | None = None) -> PolicyDecision:
    """Matriz de decisão: gates primeiro; low+trusted completa sem LLM revisor;
    high/sensitive/supervised exigem revisão independente com tier proporcional."""
    config = config or load_config()
    sensitive = sensitive or []
    if gate_result == 'fail':
        return PolicyDecision('NO_REVIEW_GATE_FAIL', 'none', task_risk, agent_trust,
                              'fail', sensitive,
                              'Gate objetivo reprovado; retorna ao executor sem revisor LLM')
    if gate_result != 'pass':
        return PolicyDecision('BLOCKED_OPERATIONAL', 'none', task_risk, agent_trust,
                              gate_result, sensitive, f'Gate indisponível ({gate_result})')
    if task_risk == 'low' and agent_trust == 'trusted':
        return PolicyDecision('NO_REVIEW_COMPLETE', 'none', 'low', 'trusted', 'pass',
                              sensitive, 'Risco baixo, executor confiável e gates PASS')
    if sensitive:
        tier = 'strong' if complexity in ('high', 'critical') else 'economic'
        reason = 'Escopo sensível; tier proporcional à complexidade'
    else:
        tier = 'strong'
        reason = 'Risco alto ou executor supervisionado exige revisão forte'
    candidates = [reviewer for reviewer in config['tier_reviewers'].get(tier, []) if reviewer != executor]
    return PolicyDecision('REVISAR', tier, task_risk, agent_trust, 'pass', sensitive,
                          reason, candidates)


def reviewer_tier_for_escalation(current_tier: str, executor: str | None = None,
                                 config: dict | None = None) -> PolicyDecision | None:
    """Escalonamento só sobe: economic → strong; incerteza em strong não desce."""
    if current_tier != 'economic':
        return None
    config = config or load_config()
    candidates = [r for r in config['tier_reviewers']['strong'] if r != executor]
    return PolicyDecision('REVISAR', 'strong', 'high', 'supervised', 'pass', [],
                          'Escalonamento por incerteza do revisor econômico', candidates)
