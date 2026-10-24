from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import ai_cost_guard as guard


def test_qwen_cost_is_calculated_from_central_policy():
    policy = guard.policy_for("openrouter", "qwen/qwen3-coder")

    cost = guard.estimate_cost(policy, 1_000_000, 1_000_000)

    assert cost == Decimal("1.30")
    assert policy.category == "economic"
    assert policy.requires_confirmation is False


def test_free_nemotron_is_identified_as_free():
    policy = guard.policy_for(
        "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"
    )

    assert policy.is_free is True
    assert guard.estimate_cost(policy, 900_000, 100_000) == Decimal("0")


def test_premium_without_confirmation_is_rejected_before_call():
    policy = guard.policy_for("openrouter", "moonshotai/kimi-k3")
    estimate = guard.estimate_cost(policy, 1000, 1000)

    with pytest.raises(guard.CostGuardError) as error:
        guard.require_premium_confirmation(policy, False, estimate)

    assert error.value.code == "premium_confirmation_required"


def test_premium_with_unknown_price_is_blocked_even_if_confirmed():
    policy = guard.policy_for("openai", "gpt-5.6-sol")

    with pytest.raises(guard.CostGuardError) as error:
        guard.require_premium_confirmation(policy, True, None)

    assert error.value.code == "premium_price_unknown"


def test_unknown_premium_family_cannot_bypass_confirmation():
    policy = guard.policy_for("anthropic", "claude-opus-future")

    assert policy.category == "premium"
    assert policy.requires_confirmation is True


def test_output_token_limit(monkeypatch):
    monkeypatch.setenv("AI_MAX_OUTPUT_TOKENS", "1000")

    with pytest.raises(guard.CostGuardError) as error:
        guard.output_limit(1001)

    assert error.value.code == "output_token_limit"


def test_daily_budget_blocks_projected_paid_call():
    budget = SimpleNamespace(
        active=True, scope_type="global", scope_key="", period="daily",
        limit_usd=Decimal("10"),
    )
    budgets_query = Mock()
    budgets_query.filter.return_value.all.return_value = [budget]
    spent_query = Mock()
    spent_query.filter.return_value = spent_query
    spent_query.scalar.return_value = Decimal("9.80")
    db = Mock()
    db.query.side_effect = [budgets_query, spent_query]

    with pytest.raises(guard.CostGuardError) as error:
        guard.enforce_budgets(
            db, provider="openrouter", project_id=None,
            estimated_cost=Decimal("0.25"),
        )

    assert error.value.code == "budget_exceeded"


def test_correlation_id_rejects_invalid_value():
    with pytest.raises(guard.CostGuardError) as error:
        guard.correlation_id("not-a-uuid")

    assert error.value.code == "invalid_correlation_id"
