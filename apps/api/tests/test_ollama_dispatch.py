"""Despacho controlado para runtimes Ollama.

Fatia 7 — driver de conexão e bloqueio de despacho para endpoint indisponível.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from app.services import agent_runtimes
from app.services.ollama_driver import (
    OllamaDispatchError,
    dispatch,
    ensure_dispatchable,
    ensure_dispatchable_blocking,
)


def _health(status, reason=None):
    return agent_runtimes.RuntimeHealth(
        runtime_id="local-code",
        status=status,
        reason=reason,
        models=("qwen2.5-coder:7b",),
        checked_at="2026-09-09T00:00:00+00:00",
        latency_ms=12,
    )


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeClient:
    """AsyncClient mínimo, para provar o que sai e o que volta do driver."""

    last_request: dict = {}

    def __init__(self, **kwargs):
        _FakeClient.last_request = {"client_kwargs": kwargs}
        self.response = _FakeResponse(200, {"response": "plano de ataque"})
        self.error: Exception | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.last_request.update(
            {"url": url, "headers": headers, "json": json}
        )
        if self.error:
            raise self.error
        return self.response


class DispatchGuardTest(unittest.TestCase):
    def setUp(self):
        agent_runtimes.reset_health_cache()

    def test_offline_runtime_is_refused(self):
        with patch(
            "app.services.agent_runtimes.check_runtime_cached",
            new=AsyncMock(return_value=_health("offline", "sem resposta")),
        ):
            with self.assertRaises(OllamaDispatchError) as ctx:
                asyncio.run(ensure_dispatchable("local-code"))

        self.assertEqual(ctx.exception.code, "runtime_unavailable")

    def test_unconfigured_gpu_is_refused(self):
        with patch(
            "app.services.agent_runtimes.check_runtime_cached",
            new=AsyncMock(return_value=_health("unconfigured", "sem URL")),
        ):
            with self.assertRaises(OllamaDispatchError) as ctx:
                asyncio.run(ensure_dispatchable("gpu-hostinger"))

        self.assertEqual(ctx.exception.code, "runtime_unavailable")

    def test_unknown_runtime_is_refused(self):
        with self.assertRaises(OllamaDispatchError) as ctx:
            asyncio.run(ensure_dispatchable("gpu-do-vizinho"))
        self.assertEqual(ctx.exception.code, "unknown_runtime")

    def test_online_runtime_is_accepted(self):
        with patch(
            "app.services.agent_runtimes.check_runtime_cached",
            new=AsyncMock(return_value=_health("online")),
        ):
            runtime = asyncio.run(ensure_dispatchable("local-code"))

        self.assertEqual(runtime.id, "local-code")

    def test_blocking_guard_mirrors_the_async_one(self):
        with patch(
            "app.services.agent_runtimes.check_runtime_blocking",
            return_value=_health("offline", "GPU desligada"),
        ):
            with self.assertRaises(OllamaDispatchError) as ctx:
                ensure_dispatchable_blocking("gpu-runpod")

        self.assertEqual(ctx.exception.code, "runtime_unavailable")


class DispatchTest(unittest.TestCase):
    def setUp(self):
        agent_runtimes.reset_health_cache()
        self.health = patch(
            "app.services.agent_runtimes.check_runtime_cached",
            new=AsyncMock(return_value=_health("online")),
        )
        self.health.start()
        self.addCleanup(self.health.stop)

    def _dispatch(self, prompt="faça X", model=None, env=None):
        env = env or {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("httpx.AsyncClient", _FakeClient),
        ):
            return asyncio.run(dispatch("local-code", prompt, model=model))

    def test_sends_prompt_as_text_without_streaming(self):
        result = self._dispatch("implemente a fatia 7")

        body = _FakeClient.last_request["json"]
        self.assertEqual(body["prompt"], "implemente a fatia 7")
        self.assertEqual(body["model"], "qwen2.5-coder:7b")
        self.assertFalse(body["stream"])
        self.assertEqual(result["response"], "plano de ataque")
        self.assertEqual(result["runtime_id"], "local-code")

    def test_payload_carries_no_shell_or_repository_access(self):
        self._dispatch()

        body = _FakeClient.last_request["json"]
        # O contrato do despacho é texto: nada de comando, caminho de repo,
        # ferramenta ou credencial atravessa a fronteira.
        self.assertEqual(set(body), {"model", "prompt", "stream"})

    def test_missing_model_is_refused_before_the_call(self):
        with self.assertRaises(OllamaDispatchError) as ctx:
            self._dispatch(env={"WORKDEV_OLLAMA_LOCAL_MODEL": " "})
        self.assertEqual(ctx.exception.code, "model_not_configured")

    def test_http_error_becomes_domain_error(self):
        class _Rejecting(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(500, {})

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _Rejecting),
            self.assertRaises(OllamaDispatchError) as ctx,
        ):
            asyncio.run(dispatch("local-code", "oi"))

        self.assertEqual(ctx.exception.code, "dispatch_rejected")

    def test_timeout_becomes_domain_error(self):
        class _Timing(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.error = httpx.TimeoutException("estourou")

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _Timing),
            self.assertRaises(OllamaDispatchError) as ctx,
        ):
            asyncio.run(dispatch("local-code", "oi"))

        self.assertEqual(ctx.exception.code, "dispatch_timeout")

    def test_oversized_response_is_truncated(self):
        class _Verbose(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(200, {"response": "x" * 70_000})

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _Verbose),
        ):
            result = asyncio.run(dispatch("local-code", "oi"))

        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["response"]), 60_000)


class BuildGuardTest(unittest.TestCase):
    """Enviar Build a um runtime indisponível não cria run pendurada."""

    def test_send_to_build_refuses_unavailable_runtime(self):
        from fastapi import HTTPException

        from app.routers.handoffs import send_to_build
        from app.schemas.handoff import BuildRequest

        plan = Mock(status="approved")

        with (
            patch("app.routers.handoffs._get_plan", return_value=plan),
            patch(
                "app.routers.handoffs.ensure_dispatchable_blocking",
                side_effect=OllamaDispatchError(
                    "runtime_unavailable",
                    "GPU Hostinger está offline",
                    {"runtime_id": "gpu-hostinger"},
                ),
            ),
            patch("app.routers.handoffs.queue_build") as queue_mock,
            self.assertRaises(HTTPException) as ctx,
        ):
            send_to_build(
                plan_id="plan-1",
                payload=BuildRequest(
                    routing_mode="manual",
                    agent="gpu-hostinger",
                    reviewer="claude",
                ),
                background=Mock(),
                db=Mock(),
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(
            ctx.exception.detail["code"],
            "runtime_unavailable",
        )
        queue_mock.assert_not_called()

    def test_cli_agents_do_not_go_through_the_ollama_guard(self):
        from app.routers.handoffs import send_to_build
        from app.schemas.handoff import BuildRequest

        run = Mock(routing_mode="manual", agent="claude", id="run-1")

        with (
            patch(
                "app.routers.handoffs._get_plan",
                return_value=Mock(status="approved"),
            ),
            patch(
                "app.routers.handoffs.ensure_dispatchable_blocking",
            ) as guard,
            patch(
                "app.routers.handoffs.queue_build",
                return_value=(run, Mock()),
            ),
            patch("app.routers.handoffs._sync_run"),
            patch(
                "app.routers.handoffs._run_out",
                return_value={"id": "run-1"},
            ),
        ):
            send_to_build(
                plan_id="plan-1",
                payload=BuildRequest(
                    routing_mode="manual",
                    agent="claude",
                    reviewer="codex",
                ),
                background=Mock(),
                db=Mock(),
            )

        guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
