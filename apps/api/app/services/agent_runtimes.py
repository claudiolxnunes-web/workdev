"""Registry dos runtimes Ollama (local e GPU) disponíveis para o Build.

Três regras estruturam este módulo:

1. **Identidade é desacoplada do modelo.** `local-code` continua sendo
   `local-code` se o Ollama trocar de Qwen Coder para outro modelo. O modelo
   é configuração (`*_MODEL`), a identidade é contrato.
2. **Nenhuma credencial no banco.** URL base e token vivem só em variável de
   ambiente; a visão pública (`describe`) nunca devolve nem a URL nem o token,
   só se está configurado.
3. **Host GPU não é fonte de verdade.** Repositório, execução de comandos,
   estado das runs e auditoria ficam na VPS principal. Hostinger é capacidade
   efêmera (disco some ao desligar); RunPod é persistente mas intermitente.
   Nenhum dos dois pode ser dependência permanente do Build.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
import os

import httpx


PROVIDER = "ollama"

KIND_LOCAL = "local"
KIND_GPU = "gpu"

# Semântica de persistência de cada host, usada pela UI e pelas decisões de
# despacho. Nenhuma delas torna o host fonte de verdade.
PERSISTENCE_LOCAL = "local_na_vps"
PERSISTENCE_EPHEMERAL = "efemera"
PERSISTENCE_INTERMITTENT = "persistente_intermitente"


@dataclass(frozen=True)
class OllamaRuntime:
    id: str
    label: str
    kind: str
    persistence: str
    base_url_env: str
    default_base_url: str | None
    model_env: str
    default_model: str | None
    api_key_env: str | None
    notes: str
    # Runtimes Ollama ficam fora do AUTO até existirem benchmarks de
    # qualidade, disponibilidade e custo. Seleção é manual, sempre.
    auto_eligible: bool = False


RUNTIMES: tuple[OllamaRuntime, ...] = (
    OllamaRuntime(
        id="local-code",
        label="Ollama local (VPS)",
        kind=KIND_LOCAL,
        persistence=PERSISTENCE_LOCAL,
        base_url_env="WORKDEV_OLLAMA_LOCAL_URL",
        default_base_url="http://127.0.0.1:11434",
        model_env="WORKDEV_OLLAMA_LOCAL_MODEL",
        # Modelo presente no Ollama da VPS1 em 2026-09-09. É só default: trocar
        # o modelo é configuração, não muda a identidade `local-code`.
        default_model="qwen2.5-coder:14b-instruct-q4_K_M",
        api_key_env=None,
        notes=(
            "Roda na própria VPS do WorkDev. O modelo carregado pode mudar "
            "sem alterar a identidade do agente."
        ),
    ),
    OllamaRuntime(
        id="gpu-hostinger",
        label="GPU Hostinger (efêmera)",
        kind=KIND_GPU,
        persistence=PERSISTENCE_EPHEMERAL,
        base_url_env="WORKDEV_OLLAMA_HOSTINGER_URL",
        default_base_url=None,
        model_env="WORKDEV_OLLAMA_HOSTINGER_MODEL",
        default_model=None,
        api_key_env="WORKDEV_OLLAMA_HOSTINGER_TOKEN",
        notes=(
            "Instância efêmera: ao desligar, o disco é perdido. Capacidade "
            "temporária de inferência apenas — nada indispensável pode ficar "
            "armazenado nela."
        ),
    ),
    OllamaRuntime(
        id="gpu-runpod",
        label="GPU RunPod (persistente, intermitente)",
        kind=KIND_GPU,
        persistence=PERSISTENCE_INTERMITTENT,
        base_url_env="WORKDEV_OLLAMA_RUNPOD_URL",
        default_base_url=None,
        model_env="WORKDEV_OLLAMA_RUNPOD_MODEL",
        default_model=None,
        api_key_env="WORKDEV_OLLAMA_RUNPOD_TOKEN",
        notes=(
            "Armazenamento persistente para modelos, mas a GPU pode não estar "
            "disponível para religamento imediato. Não é dependência garantida "
            "do Build."
        ),
    ),
)


REGISTRY: dict[str, OllamaRuntime] = {
    runtime.id: runtime
    for runtime in RUNTIMES
}

OLLAMA_AGENT_IDS: frozenset[str] = frozenset(REGISTRY)


def get_runtime(runtime_id: str) -> OllamaRuntime | None:
    return REGISTRY.get(runtime_id)


def is_ollama_agent(agent: str | None) -> bool:
    return bool(agent) and agent in OLLAMA_AGENT_IDS


def base_url(runtime: OllamaRuntime) -> str | None:
    """URL do endpoint Ollama. Fica no ambiente, nunca no banco nem na UI."""
    configured = (
        os.getenv(runtime.base_url_env) or runtime.default_base_url or ""
    ).strip()
    return configured.rstrip("/") or None


def model_for(runtime: OllamaRuntime) -> str | None:
    configured = (
        os.getenv(runtime.model_env) or runtime.default_model or ""
    ).strip()
    return configured or None


def api_key(runtime: OllamaRuntime) -> str | None:
    """Token do endpoint. Uso interno do driver; jamais serializado."""
    if not runtime.api_key_env:
        return None
    return (os.getenv(runtime.api_key_env) or "").strip() or None


def is_configured(runtime: OllamaRuntime) -> bool:
    return base_url(runtime) is not None


# Reprovisionamento: o que precisa ser refeito quando a máquina volta.
#
# Hostinger perde o disco ao desligar, então tudo tem que ser reconstruível a
# cada boot. RunPod guarda os modelos, mas a GPU pode não estar disponível para
# religar — o setup é uma vez só, a disponibilidade é que não é garantida.
# Em nenhum dos casos algo indispensável fica só na GPU: repositório, estado da
# run, eventos e auditoria vivem no Postgres da VPS.
REPROVISION_ON_BOOT = "sempre_ao_ligar"
REPROVISION_ON_SETUP = "apenas_no_primeiro_setup"
REPROVISION_NOT_APPLICABLE = "nao_aplicavel"

REPROVISION_POLICY = {
    PERSISTENCE_LOCAL: REPROVISION_NOT_APPLICABLE,
    PERSISTENCE_EPHEMERAL: REPROVISION_ON_BOOT,
    PERSISTENCE_INTERMITTENT: REPROVISION_ON_SETUP,
}


def reprovision_policy(runtime: OllamaRuntime) -> str:
    return REPROVISION_POLICY[runtime.persistence]


def reprovision_steps(runtime: OllamaRuntime) -> list[str]:
    """Passos para reconstruir a capacidade de inferência do zero.

    Só cita nomes de variável — nunca valores. E não inclui clone de
    repositório nem credencial de git: a GPU não recebe nada disso.
    """
    if runtime.persistence == PERSISTENCE_LOCAL:
        return []

    model = model_for(runtime) or f"o modelo definido em {runtime.model_env}"

    steps = [
        "Subir o servidor Ollama na instância e expor a porta de inferência.",
        f"Baixar o modelo na instância: `ollama pull {model}`.",
        f"Apontar {runtime.base_url_env} na VPS para o endereço novo.",
    ]

    if runtime.api_key_env:
        steps.append(
            f"Registrar o token de acesso em {runtime.api_key_env} na VPS "
            "(nunca na instância)."
        )

    steps.append(
        "Nada mais: repositório, estado das runs, eventos e auditoria "
        "continuam no Postgres da VPS principal."
    )

    return steps


def describe(runtime: OllamaRuntime) -> dict:
    """Visão pública do runtime: sem URL, sem token, sem nada sensível."""
    return {
        "id": runtime.id,
        "label": runtime.label,
        "kind": runtime.kind,
        "provider": PROVIDER,
        "persistence": runtime.persistence,
        "auto_eligible": runtime.auto_eligible,
        "configured": is_configured(runtime),
        "model": model_for(runtime),
        "source_of_truth": False,
        "notes": runtime.notes,
        "reprovision": {
            "policy": reprovision_policy(runtime),
            "steps": reprovision_steps(runtime),
        },
    }


def list_runtimes() -> list[dict]:
    return [describe(runtime) for runtime in RUNTIMES]


# --------------------------------------------------------------------------
# Health check
#
# A UI nunca fala com o Ollama: quem sonda é o backend, com timeout curto, e
# devolve só o estado. Endpoint GPU fora do ar é resposta normal da sonda, não
# exceção — nada no WorkDev pode quebrar porque uma GPU está desligada.
# --------------------------------------------------------------------------

HEALTH_TIMEOUT_SECONDS = 2.0
HEALTH_CACHE_TTL_SECONDS = 10.0

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_DEGRADED = "degraded"

# Só `online` despacha. `degraded` significa que o endpoint responde mas o
# modelo esperado não está carregado — despachar assim entrega a inferência a
# um modelo que não é o configurado, silenciosamente. Ficar de fora é a
# diferença entre "não deu" e "deu, com outro modelo".
DISPATCHABLE_STATUSES = {STATUS_ONLINE}

STATUS_LABEL = {
    STATUS_ONLINE: "Online",
    STATUS_OFFLINE: "Indisponível",
    STATUS_UNCONFIGURED: "Não configurado",
    STATUS_DEGRADED: "Online sem o modelo esperado",
}


@dataclass(frozen=True)
class RuntimeHealth:
    runtime_id: str
    status: str
    reason: str | None
    models: tuple[str, ...]
    checked_at: str
    latency_ms: int | None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "status_label": STATUS_LABEL.get(self.status, self.status),
            "reason": self.reason,
            "models": list(self.models),
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "dispatchable": self.status in DISPATCHABLE_STATUSES,
        }


_health_cache: dict[str, tuple[float, RuntimeHealth]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fetch_tags(url: str, headers: dict[str, str]) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_SECONDS) as client:
        response = await client.get(url, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload


def auth_headers(runtime: OllamaRuntime) -> dict[str, str]:
    token = api_key(runtime)
    return {"Authorization": f"Bearer {token}"} if token else {}


async def check_runtime(runtime: OllamaRuntime) -> RuntimeHealth:
    """Sonda `/api/tags` do endpoint. Nunca levanta exceção para o chamador."""
    url = base_url(runtime)

    if not url:
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_UNCONFIGURED,
            reason=f"{runtime.base_url_env} não configurada",
            models=(),
            checked_at=_now_iso(),
            latency_ms=None,
        )

    started = time.monotonic()

    try:
        status_code, payload = await _fetch_tags(
            f"{url}/api/tags",
            auth_headers(runtime),
        )
    except httpx.TimeoutException:
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_OFFLINE,
            reason=(
                f"sem resposta em {HEALTH_TIMEOUT_SECONDS:g}s"
            ),
            models=(),
            checked_at=_now_iso(),
            latency_ms=None,
        )
    except Exception as error:  # rede, DNS, TLS, GPU desligada…
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_OFFLINE,
            reason=type(error).__name__,
            models=(),
            checked_at=_now_iso(),
            latency_ms=None,
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if status_code != 200:
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_OFFLINE,
            reason=f"HTTP {status_code}",
            models=(),
            checked_at=_now_iso(),
            latency_ms=latency_ms,
        )

    models = tuple(
        str(item.get("name"))
        for item in (payload.get("models") or [])
        if isinstance(item, dict) and item.get("name")
    )

    expected = model_for(runtime)

    # Sem modelo resolvido o runtime NÃO é `online`. Antes, `expected=None`
    # pulava o teste abaixo e caía direto em `online`: `ensure_dispatchable`
    # liberava, a run era criada, e só o `dispatch()` estourava
    # `model_not_configured` — com a run já parada na fila. O erro precisa
    # aparecer no envio, não depois.
    if not expected:
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_UNCONFIGURED,
            reason=f"{runtime.model_env} não configurada e sem default_model",
            models=models,
            checked_at=_now_iso(),
            latency_ms=latency_ms,
        )

    if expected not in models:
        return RuntimeHealth(
            runtime_id=runtime.id,
            status=STATUS_DEGRADED,
            reason=f"modelo {expected} não está carregado neste endpoint",
            models=models,
            checked_at=_now_iso(),
            latency_ms=latency_ms,
        )

    return RuntimeHealth(
        runtime_id=runtime.id,
        status=STATUS_ONLINE,
        reason=None,
        models=models,
        checked_at=_now_iso(),
        latency_ms=latency_ms,
    )


async def check_runtime_cached(
    runtime: OllamaRuntime,
    *,
    refresh: bool = False,
) -> RuntimeHealth:
    cached = _health_cache.get(runtime.id)

    if (
        not refresh
        and cached
        and time.monotonic() - cached[0] < HEALTH_CACHE_TTL_SECONDS
    ):
        return cached[1]

    health = await check_runtime(runtime)
    _health_cache[runtime.id] = (time.monotonic(), health)

    return health


async def check_all(*, refresh: bool = False) -> dict[str, RuntimeHealth]:
    """Sonda todos os runtimes em paralelo. Um caindo não afeta os outros."""
    results = await asyncio.gather(
        *(
            check_runtime_cached(runtime, refresh=refresh)
            for runtime in RUNTIMES
        ),
        return_exceptions=True,
    )

    snapshot: dict[str, RuntimeHealth] = {}

    for runtime, result in zip(RUNTIMES, results):
        if isinstance(result, BaseException):
            snapshot[runtime.id] = RuntimeHealth(
                runtime_id=runtime.id,
                status=STATUS_OFFLINE,
                reason=type(result).__name__,
                models=(),
                checked_at=_now_iso(),
                latency_ms=None,
            )
            continue
        snapshot[runtime.id] = result

    return snapshot


def check_runtime_blocking(
    runtime: OllamaRuntime,
    *,
    refresh: bool = True,
) -> RuntimeHealth:
    """Sonda a partir de uma rota síncrona (FastAPI as roda em threadpool)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(check_runtime_cached(runtime, refresh=refresh))

    raise RuntimeError(
        "Em contexto async use check_runtime_cached, não a versão bloqueante"
    )


def reset_health_cache() -> None:
    _health_cache.clear()
