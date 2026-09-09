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

import os
import time

import httpx

from app.services import agent_runtimes
from app.services.agent_runtimes import OllamaRuntime


DEFAULT_DISPATCH_TIMEOUT_SECONDS = 300.0
MAX_RESPONSE_CHARS = 60_000


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
) -> dict:
    """Envia o prompt ao endpoint e devolve a resposta em texto.

    Nada é executado a partir do retorno: quem decide o que fazer com o texto
    é o operador/revisor, dentro do WorkDev.
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

    try:
        async with httpx.AsyncClient(
            timeout=dispatch_timeout_seconds()
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": chosen_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
    except httpx.TimeoutException as error:
        raise OllamaDispatchError(
            "dispatch_timeout",
            (
                f"{runtime.label} não respondeu em "
                f"{dispatch_timeout_seconds():g}s"
            ),
            {"runtime_id": runtime.id},
        ) from error
    except Exception as error:
        raise OllamaDispatchError(
            "dispatch_failed",
            f"Falha ao falar com {runtime.label}: {type(error).__name__}",
            {"runtime_id": runtime.id},
        ) from error

    if response.status_code != 200:
        raise OllamaDispatchError(
            "dispatch_rejected",
            f"{runtime.label} respondeu HTTP {response.status_code}",
            {
                "runtime_id": runtime.id,
                "status_code": response.status_code,
            },
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise OllamaDispatchError(
            "invalid_response",
            f"{runtime.label} devolveu corpo que não é JSON",
            {"runtime_id": runtime.id},
        ) from error

    text = str(payload.get("response") or "")
    truncated = len(text) > MAX_RESPONSE_CHARS

    return {
        "runtime_id": runtime.id,
        "model": chosen_model,
        "response": text[:MAX_RESPONSE_CHARS],
        "truncated": truncated,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
