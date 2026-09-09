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

from dataclasses import dataclass
import os


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
        default_model="qwen2.5-coder:7b",
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
    }


def list_runtimes() -> list[dict]:
    return [describe(runtime) for runtime in RUNTIMES]
