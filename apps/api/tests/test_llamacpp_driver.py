import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import agent_runtimes
from app.services.llamacpp_driver import dispatch
from app.services.ollama_driver import OllamaDispatchError


class FakeResponse:
    def __init__(self, lines, status_code=200):
        self.lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aread(self):
        return b"erro"


class FakeClient:
    last_request = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, method, url, headers=None, json=None):
        FakeClient.last_request = {
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
        }
        return FakeResponse([
            'data: {"choices":[{"delta":{"content":"WORKDEV_"}}]}',
            'data: {"choices":[{"delta":{"content":"LLAMA_OK"}}]}',
            'data: [DONE]',
        ])


def runtime_llamacpp():
    return agent_runtimes.get_runtime("local-code")


def test_dispatch_llamacpp_stream_and_thinking_disabled(monkeypatch):
    runtime = runtime_llamacpp()

    monkeypatch.setattr(
        "app.services.llamacpp_driver.ensure_dispatchable",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        "app.services.llamacpp_driver.httpx.AsyncClient",
        FakeClient,
    )

    result = asyncio.run(dispatch("local-code", "teste"))

    body = FakeClient.last_request["json"]

    assert FakeClient.last_request["url"].endswith("/v1/chat/completions")
    assert body["model"] == "workdev-qwen27b"
    assert body["stream"] is True
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert result["response"] == "WORKDEV_LLAMA_OK"
    assert result["thinking"] == ""


def test_dispatch_llamacpp_rejects_wrong_engine(monkeypatch):
    runtime = SimpleNamespace(
        id="fake",
        label="Fake Ollama",
        engine=agent_runtimes.ENGINE_OLLAMA,
    )

    monkeypatch.setattr(
        "app.services.llamacpp_driver.ensure_dispatchable",
        AsyncMock(return_value=runtime),
    )

    with pytest.raises(OllamaDispatchError) as exc:
        asyncio.run(dispatch("fake", "teste"))

    assert exc.value.code == "wrong_engine"


def test_dispatch_llamacpp_empty_response_is_error(monkeypatch):
    runtime = runtime_llamacpp()

    class EmptyClient(FakeClient):
        def stream(self, method, url, headers=None, json=None):
            return FakeResponse([
                'data: {"choices":[{"delta":{}}]}',
                'data: [DONE]',
            ])

    monkeypatch.setattr(
        "app.services.llamacpp_driver.ensure_dispatchable",
        AsyncMock(return_value=runtime),
    )
    monkeypatch.setattr(
        "app.services.llamacpp_driver.httpx.AsyncClient",
        EmptyClient,
    )

    with pytest.raises(OllamaDispatchError) as exc:
        asyncio.run(dispatch("local-code", "teste"))

    assert exc.value.code == "empty_response"
