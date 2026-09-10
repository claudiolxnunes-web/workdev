"""Driver de despacho para runtimes Ollama (local e GPU).

Fronteira de segurança deste módulo:

- O que sai daqui é **texto**: um prompt estruturado montado pela VPS.
- O que volta é **texto**: a resposta do modelo, registrada como evento da run.
- O WorkDev **não executa** nada do que o modelo devolve. Repositório, git,
  shell, testes e deploy continuam sendo do orquestrador na VPS principal; o
  endpoint Ollama nunca recebe acesso ao servidor.
- Endpoint indisponível não é exceção não tratada: vira erro de domínio com
  código, e o despacho é recusado antes de qualquer efeito colateral.
"""

import json
import os
import time

import httpx

from collections.abc import Awaitable, Callable

from app.services import agent_runtimes
from app.services.agent_runtimes import OllamaRuntime


# Medido em 2026-09-09 na VPS1: uma pergunta de uma linha ao
# qwen2.5-coder:14b em CPU levou 171s. Prompt de Build é bem maior, então o
# padrão precisa de folga — ajustável por WORKDEV_OLLAMA_DISPATCH_TIMEOUT_SECONDS.
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 900.0
MAX_RESPONSE_CHARS = 60_000

# O Ollama NÃO usa a janela do modelo por padrão: sem `num_ctx` explícito ele
# aplica ~4096 e trunca o resto do prompt em silêncio. Foi o que aconteceu em
# 2026-09-09 — o log do despacho ao qwen2.5-coder:14b (ctx declarado 32768)
# encerrou com `n_tokens = 3997, truncated = 1`, ou seja, o modelo passou 15
# minutos raciocinando sobre um prompt cortado. O prompt de Build carrega ADRs,
# knowledge e o plano inteiro; 4096 não serve.
DEFAULT_NUM_CTX = 16384


def num_ctx() -> int:
    raw = os.getenv("WORKDEV_OLLAMA_NUM_CTX")

    try:
        value = int(raw) if raw else DEFAULT_NUM_CTX
    except ValueError:
        value = DEFAULT_NUM_CTX

    # Teto: janela grande demais estoura a RAM da VPS no cache de KV.
    return max(2048, min(65536, value))


class OllamaDispatchError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def dispatch_timeout_seconds() -> float:
    raw = os.getenv("WORKDEV_OLLAMA_DISPATCH_TIMEOUT_SECONDS")

    try:
        value = float(raw) if raw else DEFAULT_DISPATCH_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_DISPATCH_TIMEOUT_SECONDS

    return max(5.0, min(3600.0, value))


async def ensure_dispatchable(runtime_id: str) -> OllamaRuntime:
    """Recusa o despacho quando o endpoint não está utilizável agora."""
    runtime = agent_runtimes.get_runtime(runtime_id)

    if runtime is None:
        raise OllamaDispatchError(
            "unknown_runtime",
            f"{runtime_id} não é um runtime Ollama conhecido",
        )

    health = await agent_runtimes.check_runtime_cached(runtime, refresh=True)

    if health.status not in agent_runtimes.DISPATCHABLE_STATUSES:
        raise OllamaDispatchError(
            "runtime_unavailable",
            (
                f"{runtime.label} está {health.status}"
                + (f": {health.reason}" if health.reason else "")
            ),
            {
                "runtime_id": runtime.id,
                "status": health.status,
                "reason": health.reason,
            },
        )

    return runtime


def ensure_dispatchable_blocking(runtime_id: str) -> OllamaRuntime:
    """Mesma checagem de `ensure_dispatchable`, para rotas síncronas."""
    runtime = agent_runtimes.get_runtime(runtime_id)

    if runtime is None:
        raise OllamaDispatchError(
            "unknown_runtime",
            f"{runtime_id} não é um runtime Ollama conhecido",
        )

    health = agent_runtimes.check_runtime_blocking(runtime)

    if health.status not in agent_runtimes.DISPATCHABLE_STATUSES:
        raise OllamaDispatchError(
            "runtime_unavailable",
            (
                f"{runtime.label} está {health.status}"
                + (f": {health.reason}" if health.reason else "")
            ),
            {
                "runtime_id": runtime.id,
                "status": health.status,
                "reason": health.reason,
            },
        )

    return runtime


async def dispatch(
    runtime_id: str,
    prompt: str,
    *,
    model: str | None = None,
    on_chunk: "Callable[[str, str], Awaitable[None]] | None" = None,
) -> dict:
    """Envia o prompt ao endpoint e devolve a resposta em texto.

    Nada é executado a partir do retorno: quem decide o que fazer com o texto
    é o operador/revisor, dentro do WorkDev.

    A geração é lida em streaming e `on_chunk(texto_acumulado, raciocínio)` é
    chamado durante o percurso. Com `stream: False`, uma geração que morresse
    aos 899s de 900 não deixava nada — nem no banco, nem em memória. Foi o que
    aconteceu com o qwen2.5-coder:14b em 2026-09-09: 2.040 tokens gerados em 15
    minutos, todos perdidos, e o Ollama ainda cancelou a task ao ver o cliente
    sumir. Quem persiste o parcial é o chamador; aqui só entregamos o pedaço.
    """
    runtime = await ensure_dispatchable(runtime_id)

    chosen_model = model or agent_runtimes.model_for(runtime)

    if not chosen_model:
        raise OllamaDispatchError(
            "model_not_configured",
            (
                f"Nenhum modelo configurado para {runtime.label}; defina "
                f"{runtime.model_env}"
            ),
            {"runtime_id": runtime.id},
        )

    url = f"{agent_runtimes.base_url(runtime)}/api/generate"
    headers = agent_runtimes.auth_headers(runtime)
    started = time.monotonic()

    corpo = {
        "model": chosen_model,
        "prompt": prompt,
        "stream": True,
        # Sem isto o Ollama trunca o prompt em ~4096 tokens sem avisar.
        "options": {"num_ctx": num_ctx()},
    }

    partes: list[str] = []
    raciocinio: list[str] = []
    final: dict = {}

    async def _emitir() -> None:
        if on_chunk is not None:
            await on_chunk("".join(partes), "".join(raciocinio))

    try:
        async with httpx.AsyncClient(
            timeout=dispatch_timeout_seconds()
        ) as client:
            async with client.stream(
                "POST", url, headers=headers, json=corpo
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise OllamaDispatchError(
                        "dispatch_rejected",
                        (
                            f"{runtime.label} respondeu HTTP "
                            f"{response.status_code}"
                        ),
                        {
                            "runtime_id": runtime.id,
                            "status_code": response.status_code,
                        },
                    )

                async for linha in response.aiter_lines():
                    if not linha.strip():
                        continue

                    try:
                        evento = json.loads(linha)
                    except ValueError as error:
                        raise OllamaDispatchError(
                            "invalid_response",
                            f"{runtime.label} devolveu linha que não é JSON",
                            {"runtime_id": runtime.id},
                        ) from error

                    if evento.get("error"):
                        raise OllamaDispatchError(
                            "dispatch_rejected",
                            f"{runtime.label}: {evento['error']}",
                            {"runtime_id": runtime.id},
                        )

                    if evento.get("response"):
                        partes.append(str(evento["response"]))
                    if evento.get("thinking"):
                        raciocinio.append(str(evento["thinking"]))

                    await _emitir()

                    if evento.get("done"):
                        final = evento
    except OllamaDispatchError:
        raise
    except httpx.TimeoutException as error:
        # O parcial já foi entregue ao chamador pelos on_chunk anteriores: o
        # que se perdia antes desta mudança agora está gravado.
        raise OllamaDispatchError(
            "dispatch_timeout",
            (
                f"{runtime.label} não respondeu em "
                f"{dispatch_timeout_seconds():g}s"
            ),
            {
                "runtime_id": runtime.id,
                "partial_chars": len("".join(partes)),
            },
        ) from error
    except Exception as error:
        raise OllamaDispatchError(
            "dispatch_failed",
            f"Falha ao falar com {runtime.label}: {type(error).__name__}",
            {
                "runtime_id": runtime.id,
                "partial_chars": len("".join(partes)),
            },
        ) from error

    payload = final

    text = "".join(partes)

    # Modelos com `thinking` (qwen3.5, por exemplo) devolvem o raciocínio num
    # campo separado. Ler só `response` fazia o driver jogar fora a única coisa
    # que o modelo produziu: em 2026-09-09 um despacho ao qwen3.5:9b rodou 186s,
    # gerou ~1.500 tokens, e chegou aqui com `response` vazio.
    thinking = "".join(raciocinio)

    if not text.strip():
        # Resposta vazia NÃO é sucesso. Antes disto o job era marcado `done`
        # sem conteúdo nenhum — pior que falhar, porque afirma que deu certo.
        raise OllamaDispatchError(
            "empty_response",
            (
                f"{runtime.label} concluiu sem devolver resposta"
                + (
                    " (o modelo gastou a geração no campo 'thinking'; "
                    "use um modelo sem raciocínio explícito ou peça saída "
                    "direta)"
                    if thinking.strip()
                    else ""
                )
            ),
            {
                "runtime_id": runtime.id,
                "model": chosen_model,
                "thinking_chars": len(thinking),
                "eval_count": payload.get("eval_count"),
            },
        )

    truncated = len(text) > MAX_RESPONSE_CHARS

    return {
        "runtime_id": runtime.id,
        "model": chosen_model,
        "response": text[:MAX_RESPONSE_CHARS],
        "thinking": thinking[:MAX_RESPONSE_CHARS],
        "truncated": truncated,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
