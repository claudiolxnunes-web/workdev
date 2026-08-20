from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import ai
from app.routers.ai import ChatRequest


def _db_with_session():
    session = SimpleNamespace(
        id="session-1", project_id=None, authority="plan",
        updated_at=None,
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = session
    return db


def test_premium_preflight_does_not_call_provider():
    db = _db_with_session()
    request = ChatRequest(
        messages=[{"role": "user", "content": "revise a arquitetura"}],
        session_id="session-1", provider="openrouter",
        model="moonshotai/kimi-k3", max_output_tokens=1000,
    )

    with patch.object(ai, "build_system", return_value="system"), \
         patch.object(ai, "chat_openai") as provider_call:
        response = ai.ai_chat(request, db)

    assert response["error_code"] == "premium_confirmation_required"
    assert response["confirmation_required"] is True
    provider_call.assert_not_called()


def test_unknown_provider_never_falls_back_to_anthropic():
    db = _db_with_session()
    request = ChatRequest(
        messages=[{"role": "user", "content": "oi"}],
        session_id="session-1", provider="provider-inexistente",
    )

    with patch.object(ai, "build_system", return_value="system"), \
         patch.object(ai, "chat_anthropic") as anthropic_call:
        response = ai.ai_chat(request, db)

    assert response["error_code"] == "unknown_provider"
    anthropic_call.assert_not_called()
