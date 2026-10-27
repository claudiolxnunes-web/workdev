"""Driver de Build para runtimes servidos por llama.cpp.

O llama.cpp expõe API OpenAI-compatible. Este módulo só faz inferência:
não executa shell, não lê repositório e não aplica alterações.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable

import httpx

from app.services import agent_runtimes
from app.services.ollama_driver import (
    MAX_RESPONSE_CHARS,
    OllamaDispatchError,
    dispatch_timeout_seconds,
    ensure_dispatchable,
)


FIDELITY_SYSTEM_PROMPT = (
    "Você é um agente técnico do WorkDev. Priorize fidelidade contratual e epistemológica.\n"
    "Regras permanentes:\n"
    "- Não invente fatos, logs, arquivos, estados, mecanismos, PIDs, commits, gates ou resultados.\n"
    "- Diferencie claramente fato, evidência, inferência e informação ausente.\n"
    "- Ausência de evidência não prova ausência do evento.\n"
    "- Não transforme convenções plausíveis em fatos do WorkDev.\n"
    "- Use exatamente nomes de estados, campos e contratos fornecidos no contexto.\n"
    "- Se o contrato não foi fornecido, não invente nomes de estados ou workflows.\n"
    "- Mudanças devem ser mínimas, auditáveis e restritas ao problema comprovado.\n"
    "- Não amplie permissividade ou escopo sem evidência que justifique.\n"
    "- Formular comando/plano não prova execução; sucesso exige evidência observável.\n"
    "- Executor não aprova o próprio trabalho quando revisão independente é exigida.\n"
    "- Estado persistido não prova runtime ativo; runtime inativo não prova conclusão da run.\n"
    "- Quando faltar evidência, diga o que falta e qual é a próxima observação mínima útil.\n"
    "Formato obrigatório (quando a tarefa pedir sequência de contrato ou diagnóstico):\n"
    "- Ao resumir uma sequência conforme um contrato fornecido, use exatamente o cabeçalho "
    "SEQUÊNCIA CONFIRMADA (maiúsculo, sozinho na linha), seguido da lista numerada, e depois "
    "o cabeçalho LIMITES (maiúsculo, sozinho na linha) com as restrições aplicadas.\n"
    "- Ao diagnosticar sem fechar causa-raiz, use exatamente os cabeçalhos FATO, "
    "INFORMAÇÃO AUSENTE, DIAGNÓSTICO e PRÓXIMO PASSO (maiúsculo, cada um sozinho na linha, "
    "nesta ordem quando aplicável). Rotule hipóteses explicitamente como \"hipótese\" e diga "
    "que permanecem não confirmadas até evidência.\n"
    "Responda em PT-BR, mantendo termos técnicos e nomes de código como fornecidos."
)


async def dispatch(
    runtime_id: str,
    prompt: str,
    *,
    model: str | None = None,
    on_chunk: Callable[[str, str], Awaitable[None]] | None = None,
) -> dict:
    """Envia prompt ao llama.cpp e devolve o mesmo contrato do driver Ollama."""

    runtime = await ensure_dispatchable(runtime_id, model=model)

    if runtime.engine != agent_runtimes.ENGINE_LLAMACPP:
        raise OllamaDispatchError(
            "wrong_engine",
            f"{runtime.label} não é um runtime llama.cpp",
            {
                "runtime_id": runtime.id,
                "engine": runtime.engine,
            },
        )

    chosen_model = model or agent_runtimes.model_for(runtime)

    if not chosen_model:
        raise OllamaDispatchError(
            "model_not_configured",
            (
                f"Nenhum modelo configurado para {runtime.label}; "
                f"defina {runtime.model_env}"
            ),
            {"runtime_id": runtime.id},
        )

    base = agent_runtimes.base_url(runtime)

    if not base:
        raise OllamaDispatchError(
            "runtime_not_configured",
            f"{runtime.label} não possui endpoint configurado",
            {"runtime_id": runtime.id},
        )

    url = f"{base}/v1/chat/completions"
    headers = agent_runtimes.auth_headers(runtime)
    started = time.monotonic()

    body = {
        "model": chosen_model,
        "messages": [
            {
                "role": "system",
                "content": FIDELITY_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0,
        "stream": True,
        "chat_template_kwargs": {
            "enable_thinking": False,
        },
    }

    partes: list[str] = []

    async def emitir() -> None:
        if on_chunk is not None:
            await on_chunk("".join(partes), "")

    try:
        async with httpx.AsyncClient(
            timeout=dispatch_timeout_seconds(),
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=body,
            ) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    detail = raw.decode("utf-8", errors="replace")[:1000]

                    raise OllamaDispatchError(
                        "dispatch_rejected",
                        (
                            f"{runtime.label} respondeu HTTP "
                            f"{response.status_code}"
                        ),
                        {
                            "runtime_id": runtime.id,
                            "status_code": response.status_code,
                            "detail": detail,
                        },
                    )

                async for linha in response.aiter_lines():
                    linha = linha.strip()

                    if not linha:
                        continue

                    # SSE pode carregar comentários/keep-alives e campos de
                    # controle que não são payload JSON.
                    if linha.startswith(":"):
                        continue

                    if linha.startswith(("event:", "id:", "retry:")):
                        continue

                    if linha.startswith("data:"):
                        linha = linha[5:].strip()

                    if not linha:
                        continue

                    if linha == "[DONE]":
                        break

                    try:
                        evento = json.loads(linha)
                    except ValueError as error:
                        raise OllamaDispatchError(
                            "invalid_response",
                            f"{runtime.label} devolveu evento SSE inválido",
                            {
                                "runtime_id": runtime.id,
                                "line": repr(linha[:500]),
                            },
                        ) from error

                    if evento.get("error"):
                        raise OllamaDispatchError(
                            "dispatch_rejected",
                            f"{runtime.label}: {evento['error']}",
                            {"runtime_id": runtime.id},
                        )

                    choices = evento.get("choices") or []

                    if not choices:
                        continue

                    choice = choices[0]

                    if not isinstance(choice, dict):
                        continue

                    delta = choice.get("delta") or {}

                    if not isinstance(delta, dict):
                        continue

                    content = delta.get("content")

                    if content:
                        partes.append(str(content))
                        await emitir()

    except OllamaDispatchError:
        raise

    except httpx.TimeoutException as error:
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

    text = "".join(partes)

    if not text.strip():
        raise OllamaDispatchError(
            "empty_response",
            f"{runtime.label} concluiu sem devolver resposta",
            {
                "runtime_id": runtime.id,
                "model": chosen_model,
            },
        )

    truncated = len(text) > MAX_RESPONSE_CHARS

    return {
        "runtime_id": runtime.id,
        "model": chosen_model,
        "response": text[:MAX_RESPONSE_CHARS],
        "thinking": "",
        "truncated": truncated,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
