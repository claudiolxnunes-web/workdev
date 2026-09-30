"""Troca do modelo WorkDev Qwen servido pelo local-code (14B / 7B / 4B).

Existe um único llama-server na porta 8080, com alias fixo `workdev-qwen`.
Trocar de modelo é gravar a chave em KEY_FILE e reiniciar o serviço: a
identidade `local-code`, a sessão tmux, os hooks do Qwen e a fila persistente
não mudam.

Por que arquivo de chave e não EnvironmentFile: a API roda com
NoNewPrivileges (sudo não funciona) e um env file gravável pelo `workdev`
permitiria injetar LD_PRELOAD num serviço root. O arquivo guarda só a chave;
quem a traduz em caminho de GGUF é o wrapper root
/usr/local/libexec/workdev-llama-run, que aceita apenas as chaves conhecidas.

Reiniciar derruba inferência em curso, então a troca é recusada com run
ativa, CLI ocupada ou operação de lifecycle em andamento.
"""
from __future__ import annotations

from pathlib import Path

from app.services import agent_lifecycle

AGENT = "local-code"
KEY_FILE = Path("/var/lib/workdev-llama/model")

MODELS = {
    "prod": "WorkDev Qwen 14B Production",
    "dev": "WorkDev Qwen 7B Dev",
    "fast": "WorkDev Qwen 4B 70/30 Fast",
}

DEFAULT_MODEL = "prod"

IDLE_PHASES = {None, "idle", "offline"}


class SwitchError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def current() -> str | None:
    """Modelo configurado, com a mesma regra do wrapper (desconhecido = prod)."""
    try:
        bruto = KEY_FILE.read_bytes()[:32].decode("ascii", "ignore")
    except FileNotFoundError:
        return DEFAULT_MODEL
    except OSError:
        return None
    chave = "".join(c for c in bruto if c.isascii() and (c.islower() or c.isdigit()))
    return chave if chave in MODELS else DEFAULT_MODEL


def options() -> list[dict]:
    return [{"key": chave, "label": rotulo} for chave, rotulo in MODELS.items()]


def switch(key: str, db) -> dict:
    if key not in MODELS:
        raise SwitchError("model_unknown", f"Modelo desconhecido: {key}")
    try:
        with agent_lifecycle.agent_lock(AGENT, blocking=False):
            return _switch_locked(key, db)
    except BlockingIOError as error:
        raise SwitchError("lifecycle_busy", "Outra operação do local-code em andamento") from error


def _switch_locked(key: str, db) -> dict:
    trabalho = agent_lifecycle.active_work(db, AGENT)
    if trabalho:
        raise SwitchError("agent_busy", f"local-code tem trabalho ativo (run {trabalho['run_id']})")

    from app.services import local_code_channel as channel
    try:
        estado = channel.read()
    except agent_lifecycle.LifecycleError as error:
        raise SwitchError("channel_unknown", "Estado da CLI local-code indisponível") from error
    if estado.get("run_id") or estado.get("phase") not in IDLE_PHASES:
        raise SwitchError("agent_busy", "CLI local-code ocupada ou em estado incerto")

    if current() == key:
        return {"model": key, "switched": False, "restarted": False}

    ativo = agent_lifecycle._llama_service("is-active")

    try:
        # Escrita no próprio arquivo: o diretório é do root, rename não é possível.
        with KEY_FILE.open("w") as arquivo:
            arquivo.write(key + "\n")
    except OSError as error:
        raise SwitchError("switch_failed", f"Não foi possível gravar {KEY_FILE}") from error

    # Desligado continua desligado: a chave vale no próximo Ligar.
    if not ativo:
        return {"model": key, "switched": True, "restarted": False}

    if not agent_lifecycle._llama_service("stop"):
        raise SwitchError("switch_failed", "Falha ao parar o llama.cpp; o modelo novo vale no próximo Ligar")
    if not agent_lifecycle._llama_service("start"):
        raise SwitchError("switch_failed", "llama.cpp parou e não voltou; use Ligar no local-code")
    return {"model": key, "switched": True, "restarted": True}
