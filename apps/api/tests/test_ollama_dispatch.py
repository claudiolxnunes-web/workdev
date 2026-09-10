"""Despacho controlado para runtimes Ollama.

Fatia 7 — driver de conexão e bloqueio de despacho para endpoint indisponível.
"""

import asyncio
import json
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
    """Resposta de streaming: o payload vira uma linha NDJSON com done=true.

    Os testes continuam declarando o resultado como um dicionário só; quem
    traduz para o formato de stream é este dublê, para o caso de uma linha
    única (o mais comum) não poluir cada teste.
    """

    def __init__(self, status_code=200, payload=None, linhas=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._linhas = linhas

    def json(self):
        return self._payload

    async def aread(self):
        return b""

    async def aiter_lines(self):
        if self._linhas is not None:
            for linha in self._linhas:
                yield json.dumps(linha)
            return
        yield json.dumps({**self._payload, "done": True})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


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

    def stream(self, method, url, headers=None, json=None):
        _FakeClient.last_request.update(
            {"url": url, "headers": headers, "json": json, "method": method}
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

    def test_resposta_vazia_nao_e_sucesso(self):
        """Job `done` sem conteúdo é pior que job `failed`: afirma que deu certo.

        Aconteceu em 2026-09-09 com qwen3.5:9b — 186s de geração, ~1.500
        tokens, e `response` vazio porque o modelo gastou tudo no campo
        `thinking`. O driver guardava string vazia e o job era marcado `done`.
        """
        class _Vazio(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(
                    200, {"response": "", "thinking": "pensei muito"},
                )

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen3.5:9b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _Vazio),
            self.assertRaises(OllamaDispatchError) as ctx,
        ):
            asyncio.run(dispatch("local-code", "faça X"))

        self.assertEqual(ctx.exception.code, "empty_response")
        # A mensagem tem que dizer POR QUE veio vazio, senão o operador troca
        # de modelo no escuro.
        self.assertIn("thinking", ctx.exception.message)
        self.assertEqual(ctx.exception.details["thinking_chars"], len("pensei muito"))

    def test_resposta_so_com_espaco_tambem_falha(self):
        class _Branco(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(200, {"response": "   \n  "})

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _Branco),
            self.assertRaises(OllamaDispatchError) as ctx,
        ):
            asyncio.run(dispatch("local-code", "faça X"))

        self.assertEqual(ctx.exception.code, "empty_response")

    def test_thinking_e_preservado_quando_ha_resposta(self):
        """O raciocínio é auditoria, não lixo: guardado junto da resposta."""
        class _ComRaciocinio(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(
                    200,
                    {"response": "a resposta", "thinking": "o raciocínio"},
                )

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen3.5:9b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _ComRaciocinio),
        ):
            result = asyncio.run(dispatch("local-code", "faça X"))

        self.assertEqual(result["response"], "a resposta")
        self.assertEqual(result["thinking"], "o raciocínio")

    def test_modelo_sem_thinking_devolve_campo_vazio(self):
        result = self._dispatch("faça X")

        self.assertEqual(result["response"], "plano de ataque")
        self.assertEqual(result["thinking"], "")

    def test_sends_prompt_as_text_in_streaming(self):
        """Streaming é obrigatório: sem ele, geração interrompida não deixa nada.

        Este teste já afirmou `stream: False`. Mudou de propósito em
        2026-09-10, depois de uma geração de 15 minutos e 2.040 tokens ser
        perdida inteira num timeout.
        """
        result = self._dispatch("implemente a fatia 7")

        body = _FakeClient.last_request["json"]
        self.assertEqual(body["prompt"], "implemente a fatia 7")
        self.assertEqual(body["model"], "qwen2.5-coder:7b")
        self.assertTrue(body["stream"])
        self.assertEqual(result["response"], "plano de ataque")
        self.assertEqual(result["runtime_id"], "local-code")

    def test_janela_de_contexto_e_explicita(self):
        """Sem num_ctx o Ollama trunca o prompt em ~4096 e não avisa."""
        self._dispatch()

        body = _FakeClient.last_request["json"]
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)

    def test_payload_carries_no_shell_or_repository_access(self):
        self._dispatch()

        body = _FakeClient.last_request["json"]
        # O contrato do despacho é texto: nada de comando, caminho de repo,
        # ferramenta ou credencial atravessa a fronteira.
        self.assertEqual(set(body), {"model", "prompt", "stream", "options"})
        # `options` existe só para a janela de contexto. Se um dia couber
        # `tools` ou caminho aqui dentro, é este teste que tem que barrar.
        self.assertEqual(set(body["options"]), {"num_ctx"})

    def test_parcial_chega_ao_chamador_durante_a_geracao(self):
        """O parcial é o que sobra quando a geração morre no meio."""
        class _EmPedacos(_FakeClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(200, linhas=[
                    {"response": "primeiro "},
                    {"response": "segundo "},
                    {"response": "terceiro", "done": True},
                ])

        vistos = []

        async def _anotar(texto, _raciocinio):
            vistos.append(texto)

        with (
            patch.dict(
                "os.environ",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
                clear=True,
            ),
            patch("httpx.AsyncClient", _EmPedacos),
        ):
            result = asyncio.run(
                dispatch("local-code", "faça X", on_chunk=_anotar)
            )

        self.assertEqual(
            vistos,
            ["primeiro ", "primeiro segundo ", "primeiro segundo terceiro"],
        )
        self.assertEqual(result["response"], "primeiro segundo terceiro")

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
