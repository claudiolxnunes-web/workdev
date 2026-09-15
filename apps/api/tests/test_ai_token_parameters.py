from unittest.mock import MagicMock, patch

from app.routers import ai


def _response():
    response = MagicMock()
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.choices[0].message.content = "OK"
    response.choices[0].message.tool_calls = None
    return response


def test_openai_uses_max_completion_tokens():
    client = MagicMock()
    client.chat.completions.create.return_value = _response()

    with patch.object(ai, "get_openai", return_value=client):
        result = ai.chat_openai(
            [{"role": "user", "content": "teste"}],
            MagicMock(),
            provider="openai",
            model="gpt-4o-mini",
            max_output_tokens=123,
        )

    kwargs = client.chat.completions.create.call_args.kwargs

    assert result.text == "OK"
    assert kwargs["max_completion_tokens"] == 123
    assert "max_tokens" not in kwargs


def test_compatible_provider_keeps_max_tokens():
    client = MagicMock()
    client.chat.completions.create.return_value = _response()

    with patch.object(ai, "get_openai", return_value=client):
        result = ai.chat_openai(
            [{"role": "user", "content": "teste"}],
            MagicMock(),
            provider="openrouter",
            model="modelo-teste",
            max_output_tokens=123,
        )

    kwargs = client.chat.completions.create.call_args.kwargs

    assert result.text == "OK"
    assert kwargs["max_tokens"] == 123
    assert "max_completion_tokens" not in kwargs
