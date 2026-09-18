"""Local discovery and existing tool loop: isolated HTTP transport, no runtime writes."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ai
from app.services import agent_runtimes as runtimes


@pytest.fixture
def inventory(monkeypatch):
    payload = {
        "data": [
            {"id": "installed:v1"},
            {"id": "installed:v1"},
        ]
    }
    client_class = httpx.Client

    def respond(request):
        assert request.url.host == "127.0.0.1"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        runtimes.httpx,
        "Client",
        lambda **kw: client_class(
            transport=httpx.MockTransport(respond),
            **kw,
        ),
    )
    return payload


def test_inventory_dynamic_local_only(inventory):
    assert runtimes.local_chat_models() == [
        {"provider": "ollama", "model": "installed:v1", "label": "installed:v1", "runtime_id": "local-code"}]
    inventory["data"].append({"id": "newly-installed:v2"})
    assert len(runtimes.local_chat_models()) == 2
    inventory["data"] = []
    assert runtimes.local_chat_models() == []


def test_inventory_http_empty_vs_malformed(inventory):
    app = FastAPI()
    app.include_router(ai.router)
    db = MagicMock()
    app.dependency_overrides[ai.get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/ai/models?provider=local").json()[0]["runtime_id"] == "local-code"
        inventory["data"] = []
        assert client.get("/ai/models?provider=local").json() == []
        inventory.pop("data")
        response = client.get("/ai/models?provider=local")
        assert response.status_code == 503
        db.query.assert_not_called()


@pytest.mark.parametrize("provider,runtime,model", [
    ("ollama", "gpu-runpod", "installed:v1"),
    ("ollama", "http://attacker.invalid", "installed:v1"),
    ("openrouter", "local-code", "installed:v1"),
    ("ollama", "local-code", "removed"),
    ("ollama", "local-code", "remote-alias"),
    ("ollama", "local-code", None),
    ("ollama", "", "installed:v1"),
])
def test_invalid_selection_never_calls_database_or_provider(inventory, monkeypatch, provider, runtime, model):
    call = MagicMock()
    monkeypatch.setattr(ai, "get_openai", call)
    db = MagicMock()
    result = ai.ai_chat(ai.ChatRequest(provider=provider, runtime_id=runtime, model=model,
                                      messages=[{"role": "user", "content": "hi"}]), db)
    assert result["error_code"] == "local_model_unavailable"
    db.query.assert_not_called()
    call.assert_not_called()


def test_local_client_has_registry_url_and_no_global_cache(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(ai, "OpenAI", factory)
    monkeypatch.setenv("WORKDEV_LOCAL_CODE_URL", "http://127.0.0.1:8080")
    ai.get_openai("ollama", "local-code")
    ai.get_openai("ollama", "local-code")
    assert factory.call_count == 2
    assert factory.call_args.kwargs["base_url"] == "http://127.0.0.1:8080/v1"
    assert factory.call_args.kwargs["max_retries"] == 0
    assert ai.COMPAT_PROVIDERS["ollama"]["base_url"] == "https://ollama.com/v1/"


def test_existing_tool_loop_preserves_authority_and_backlog(monkeypatch):
    client = MagicMock()
    tool = SimpleNamespace(id="call-1", function=SimpleNamespace(name="get_receipt", arguments='{"id":"x"}'))
    first = MagicMock(tool_calls=[tool])
    first.model_dump.return_value = {"role": "assistant", "tool_calls": [{"id": "call-1"}]}
    last = SimpleNamespace(tool_calls=[], content="authoritative-receipt")
    client.chat.completions.create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=m)], usage=None) for m in (first, last)]
    monkeypatch.setattr(ai, "get_openai", lambda *args: client)
    monkeypatch.setattr(runtimes, "local_chat_context", lambda *args: 10000)
    monkeypatch.setattr(ai, "tools_openai", lambda level: [])
    execute = MagicMock(return_value='{"receipt":"authoritative-receipt"}')
    monkeypatch.setattr(ai, "executar_tool", execute)
    db = MagicMock()
    result = ai.chat_openai([], db, "installed:v1", "ollama", system="test", nivel="plan",
                            runtime_id="local-code", backlog_id="task-id", max_output_tokens=256)
    assert result.text == "authoritative-receipt"
    execute.assert_called_once_with("get_receipt", {"id": "x"}, db, "plan", backlog_id="task-id")
    args = client.chat.completions.create.call_args.kwargs
    assert args["messages"][-1] == {"role": "tool", "tool_call_id": "call-1", "content": execute.return_value}
    assert "reasoning_effort" not in args
    client.close.assert_called_once()


def test_context_guard_includes_tools_and_closes_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai, "get_openai", lambda *args: client)
    monkeypatch.setattr(runtimes, "local_chat_context", lambda *args: 2048)
    monkeypatch.setattr(ai, "tools_openai", lambda level: [{"description": "x" * 9000}])
    with pytest.raises(ai.ai_cost_guard.CostGuardError) as error:
        ai.chat_openai([], MagicMock(), "installed:v1", "ollama", system="short",
                       runtime_id="local-code", max_output_tokens=256)
    assert error.value.code == "local_context_limit"
    client.chat.completions.create.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize("payload,expected", [
    (
        {
            "chat_template_caps": {"supports_tools": True},
            "default_generation_settings": {"n_ctx": 8192},
        },
        8192,
    ),
    (
        {
            "chat_template_caps": {"supports_tools": False},
            "default_generation_settings": {"n_ctx": 8192},
        },
        None,
    ),
    (
        {
            "chat_template_caps": {"supports_tools": True},
            "default_generation_settings": {},
        },
        None,
    ),
])
def test_context_from_actual_model_configuration(monkeypatch, payload, expected):
    client_class = httpx.Client

    def respond(request):
        assert request.url.path == "/props"
        assert request.method == "GET"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        runtimes.httpx,
        "Client",
        lambda **kw: client_class(
            transport=httpx.MockTransport(respond),
            **kw,
        ),
    )

    if expected:
        assert runtimes.local_chat_context("local-code", "installed:v1") == expected
    else:
        with pytest.raises(ValueError):
            runtimes.local_chat_context("local-code", "installed:v1")
