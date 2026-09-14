"""Matriz de decisão do motor review_policy — gates primeiro, sensível nunca low."""
from app.services.review_policy import (
    classify_risk, decide, reviewer_tier_for_escalation,
)


CFG = {
    'trusted_agents': ['codex', 'kimi'],
    'tier_reviewers': {'economic': ['qwen'], 'strong': ['codex', 'kimi']},
    'volume_medium_lines': 10,
    'volume_high_lines': 50,
}


def test_sensitive_scope_never_classified_as_low():
    for paths, complexity in (
        (['apps/api/app/auth.py'], None),
        (['apps/api/alembic/versions/x.py'], 'low'),
        (['deploy.sh'], 'low'),
    ):
        assessment = classify_risk(paths, 'diff', complexity, CFG)
        assert assessment.risk == 'high', (paths, assessment)


def test_low_volume_trusted_and_pass_completes_without_reviewer():
    decision = decide('low', 'trusted', 'pass', config=CFG)
    assert decision.decision == 'NO_REVIEW_COMPLETE' and decision.tier == 'none'


def test_gate_fail_returns_to_executor_without_llm_review():
    decision = decide('high', 'trusted', 'fail', config=CFG)
    assert decision.decision == 'NO_REVIEW_GATE_FAIL'
    assert 'executor' in decision.justification.lower()


def test_sensitive_medium_uses_economic_tier():
    decision = decide('medium', 'trusted', 'pass', sensitive=['migration'], config=CFG)
    assert decision.decision == 'REVISAR' and decision.tier == 'economic'


def test_sensitive_high_complexity_uses_strong_tier():
    decision = decide('high', 'trusted', 'pass', sensitive=['auth'],
                      complexity='critical', config=CFG)
    assert decision.tier == 'strong'


def test_high_risk_always_requires_strong_review():
    decision = decide('high', 'trusted', 'pass', config=CFG)
    assert decision.decision == 'REVISAR' and decision.tier == 'strong'


def test_supervised_executor_never_completes_without_review():
    decision = decide('low', 'supervised', 'pass', config=CFG)
    assert decision.decision == 'REVISAR' and decision.tier == 'strong'


def test_executor_is_never_among_reviewer_candidates():
    decision = decide('high', 'supervised', 'pass', executor='qwen', config=CFG)
    assert 'qwen' not in decision.reviewer_candidates


def test_escalation_only_climbs_from_economic_to_strong():
    escalation = reviewer_tier_for_escalation('economic', executor='qwen', config=CFG)
    assert escalation and escalation.tier == 'strong'
    assert reviewer_tier_for_escalation('strong', config=CFG) is None
    assert reviewer_tier_for_escalation('none', config=CFG) is None


def test_gate_indeterminate_is_operational_block():
    decision = decide('low', 'trusted', 'indeterminado', config=CFG)
    assert decision.decision == 'BLOCKED_OPERATIONAL'
