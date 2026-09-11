"""Ligar e desligar agentes locais de verdade (task 177a2f03).

O problema que este módulo resolve: `tmux kill-session` faz a sessão sumir da
lista, mas isso **não é** o agente estar desligado. Um filho que escapou do
process group continua vivo segurando GB de RAM, e o modelo carregado no Ollama
permanece residente em RAM/VRAM até alguém mandar descarregar. A tela dizia
OFFLINE; a memória dizia outra coisa.

Três separações que estruturam o módulo:

1. **Ciclo do agente ≠ ciclo do modelo.** O modelo do Ollama é recurso
   compartilhado: descarregá-lo porque UM agente parou pode derrubar outro que
   ainda o usa. Só se descarrega modelo órfão.
2. **Encerrar é seletivo, nunca varredura.** Mata-se o process group da sessão
   daquele agente — obtido do `pane_pid` do tmux. Nada de `pkill ollama` ou
   `killall node`: isso mataria agente de terceiro e processo do host.
3. **OFFLINE é uma verificação, não uma suposição.** Depois de encerrar, o
   estado é lido de novo do sistema: sessão, processos do grupo e modelo. Só
   quando os três estão limpos é que o agente está offline.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass, field


# `ollama stop` descarrega o modelo da RAM/VRAM sem derrubar o servidor.
OLLAMA_BIN = os.getenv("WORKDEV_OLLAMA_BIN", "ollama")

# Janela entre SIGTERM e SIGKILL. Curta o bastante para o operador não achar que
# travou; longa o bastante para uma CLI salvar estado e sair sozinha.
GRACEFUL_TIMEOUT_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.25

# `ollama stop` é assíncrono e mente no exit code (ver `unload_model`). Estes
# controlam a CONFIRMAÇÃO de que o modelo saiu da memória.
UNLOAD_VERIFY_TIMEOUT_SECONDS = 20.0
UNLOAD_POLL_SECONDS = 1.0

CMD_TIMEOUT_SECONDS = 10

# Processos que são o shell da sessão, não o agente. Se é só isso que sobrou, a
# sessão está em standby — viva, mas sem agente rodando.
SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}


class LifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class AgentState:
    """Retrato do agente lido do sistema, não do que se espera dele."""

    agent: str
    session: str | None = None
    session_exists: bool = False
    pane_pid: int | None = None
    pgid: int | None = None
    group_pids: list[int] = field(default_factory=list)
    current_process: str = ""
    model: str | None = None
    model_loaded: bool = False
    rss_kb: int = 0

    @property
    def agent_process_running(self) -> bool:
        """Sessão com processo que não é o shell — ou seja, agente de fato."""
        return bool(
            self.current_process
            and self.current_process not in SHELL_PROCESSES
        )

    @property
    def offline(self) -> bool:
        """Definição de aceite da task.

        Não basta a sessão ter sumido: enquanto houver processo do grupo vivo
        ou modelo residente, há consumo de memória e o agente NÃO está offline.
        """
        return (
            not self.session_exists
            and not self.group_pids
            and not self.model_loaded
        )

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "session": self.session,
            "session_exists": self.session_exists,
            "pane_pid": self.pane_pid,
            "pgid": self.pgid,
            "group_pids": list(self.group_pids),
            "current_process": self.current_process,
            "agent_process_running": self.agent_process_running,
            "model": self.model,
            "model_loaded": self.model_loaded,
            "rss_kb": self.rss_kb,
            "offline": self.offline,
        }


# --------------------------------------------------------------------------
# Leitura do sistema
# --------------------------------------------------------------------------


def _run(args: list[str], timeout: int = CMD_TIMEOUT_SECONDS):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def session_exists(session: str) -> bool:
    return _run(["tmux", "has-session", "-t", f"={session}"], 5).returncode == 0


def pane_pid(session: str) -> int | None:
    """PID do processo do painel. É a raiz do que pertence a este agente."""
    resultado = _run(
        ["tmux", "display-message", "-p", "-t", f"={session}:", "#{pane_pid}"],
        5,
    )

    if resultado.returncode != 0:
        return None

    bruto = resultado.stdout.strip()

    return int(bruto) if bruto.isdigit() else None


def current_process(session: str) -> str:
    resultado = _run(
        [
            "tmux", "display-message", "-p", "-t", f"={session}:",
            "#{pane_current_command}",
        ],
        5,
    )
    return resultado.stdout.strip() if resultado.returncode == 0 else ""


def pgid_of(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None


def group_pids(pgid: int) -> list[int]:
    """PIDs vivos do process group. É o escopo exato do que pode ser morto."""
    if not pgid:
        return []

    resultado = _run(["ps", "-o", "pid=", "-g", str(pgid)], 5)

    if resultado.returncode != 0:
        return []

    return [
        int(linha.strip())
        for linha in resultado.stdout.splitlines()
        if linha.strip().isdigit()
    ]


def group_rss_kb(pids: list[int]) -> int:
    """Memória residente somada do grupo — a prova de que algo foi liberado."""
    if not pids:
        return 0

    resultado = _run(
        ["ps", "-o", "rss=", "-p", ",".join(str(pid) for pid in pids)], 5
    )

    if resultado.returncode != 0:
        return 0

    return sum(
        int(linha.strip())
        for linha in resultado.stdout.splitlines()
        if linha.strip().isdigit()
    )


def running_models() -> list[str]:
    """Modelos residentes agora, via `ollama ps`.

    Detecção primária conforme o plano. Ollama ausente ou fora do ar não é
    exceção: é 'nenhum modelo carregado' — desligar agente não pode quebrar
    porque o Ollama não está instalado.
    """
    try:
        resultado = _run([OLLAMA_BIN, "ps"])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    if resultado.returncode != 0:
        return []

    linhas = resultado.stdout.strip().splitlines()

    if len(linhas) <= 1:  # só o cabeçalho NAME/ID/SIZE/...
        return []

    modelos = []

    for linha in linhas[1:]:
        nome = linha.split()[0] if linha.split() else ""
        if nome:
            modelos.append(nome)

    return modelos


def model_is_loaded(model: str | None) -> bool:
    if not model:
        return False
    return model in running_models()


# --------------------------------------------------------------------------
# Modelo compartilhado
# --------------------------------------------------------------------------


def model_for_agent(agent: str) -> str | None:
    """Modelo Ollama do agente, quando ele for um runtime Ollama.

    Agente CLI (codex, claude, kimi, qwen, gemini) fala com API remota e não
    tem modelo residente aqui — devolve None, e nada é descarregado por causa
    dele.
    """
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    return agent_runtimes.model_for(runtime) if runtime else None


def _endpoint_of(agent: str) -> str | None:
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    return agent_runtimes.base_url(runtime) if runtime else None


def model_users(model: str, *, excluding: str) -> list[str]:
    """Outros runtimes que usam este modelo NO MESMO endpoint.

    O endpoint importa: `gpu-runpod` pode carregar o mesmo modelo que
    `local-code`, mas em outra máquina. `ollama stop` só alcança o Ollama
    local, então um runtime remoto não é motivo para manter o modelo local
    residente.
    """
    from app.services import agent_runtimes

    endpoint = _endpoint_of(excluding)

    return [
        runtime.id
        for runtime in agent_runtimes.RUNTIMES
        if runtime.id != excluding
        and agent_runtimes.model_for(runtime) == model
        and agent_runtimes.base_url(runtime) == endpoint
    ]


def unload_model(model: str, *, verify_timeout: float = None) -> bool:
    """`ollama stop <model>` e CONFIRMA que ele saiu da memória.

    Medido nesta VPS em 2026-09-11, com `qwen2.5-coder:7b-instruct-q3_K_S`:
    `ollama stop` retorna **exit 0 imediatamente**, mas o descarregamento é
    assíncrono — o `ollama ps` manteve o modelo em `Stopping...` e o runner
    `llama-server` continuou com 4.7 GB de RSS por **vários minutos** antes de
    a memória voltar (RAM do host: 7831 MB → 3372 MB, só no fim).

    Por isso o retorno aqui é o que o `ollama ps` mostra depois da janela de
    verificação, não o que o comando alegou. `False` significa "ainda residente
    quando olhei", não necessariamente "vai ficar para sempre" — e é a resposta
    honesta para quem precisa saber se a memória já voltou AGORA.

    A janela é curta de propósito: uma rota HTTP não pode bloquear por minutos.
    Quem quiser o desfecho consulta `GET /api/agents/{agent}/lifecycle` depois.
    """
    if verify_timeout is None:
        verify_timeout = UNLOAD_VERIFY_TIMEOUT_SECONDS

    try:
        _run([OLLAMA_BIN, "stop", model], 30)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

    limite = time.monotonic() + verify_timeout

    while time.monotonic() < limite:
        if not model_is_loaded(model):
            return True
        time.sleep(UNLOAD_POLL_SECONDS)

    # Continua residente. Quem chama precisa saber que a memória NÃO voltou.
    return False


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------


def read_state(agent: str, session: str | None) -> AgentState:
    estado = AgentState(agent=agent, session=session)

    estado.model = model_for_agent(agent)
    estado.model_loaded = model_is_loaded(estado.model)

    if not session:
        return estado

    estado.session_exists = session_exists(session)

    if not estado.session_exists:
        return estado

    estado.current_process = current_process(session)
    estado.pane_pid = pane_pid(session)

    if estado.pane_pid:
        estado.pgid = pgid_of(estado.pane_pid)

    if estado.pgid:
        estado.group_pids = group_pids(estado.pgid)
        estado.rss_kb = group_rss_kb(estado.group_pids)

    return estado


# --------------------------------------------------------------------------
# Encerramento seletivo
# --------------------------------------------------------------------------


def terminate_group(pgid: int) -> dict:
    """SIGTERM no grupo, espera, SIGKILL no que sobrou.

    Só o process group daquele agente. Sem `pkill`, sem varrer `ps` por nome:
    matar por nome atingiria o agente do vizinho e processos do host que por
    acaso compartilham o binário.
    """
    if not pgid:
        return {"signalled": False, "survivors": [], "escalated": False}

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return {"signalled": False, "survivors": [], "escalated": False}
    except PermissionError as error:
        raise LifecycleError(
            "permission_denied",
            f"Sem permissão para encerrar o grupo {pgid}",
        ) from error

    limite = time.monotonic() + GRACEFUL_TIMEOUT_SECONDS

    while time.monotonic() < limite:
        if not group_pids(pgid):
            return {"signalled": True, "survivors": [], "escalated": False}
        time.sleep(POLL_INTERVAL_SECONDS)

    # Não saiu no tempo combinado. SIGKILL é o que garante a liberação de
    # memória que o aceite exige — sem isto, "desligado" seria só uma palavra.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return {"signalled": True, "survivors": [], "escalated": True}

    time.sleep(POLL_INTERVAL_SECONDS * 4)

    return {
        "signalled": True,
        "survivors": group_pids(pgid),
        "escalated": True,
    }


# --------------------------------------------------------------------------
# Trabalho ativo
# --------------------------------------------------------------------------

# Status que representam trabalho FÍSICO em curso — processo rodando agora.
# `blocked` e `review` ficam de fora de propósito: são estados de espera por
# decisão humana, e manter um agente ligado semanas porque uma revisão não saiu
# é justamente o desperdício de RAM que esta task existe para eliminar. O
# trabalho não se perde: o estado vive no Postgres, não no processo.
PHYSICALLY_ACTIVE_STATUSES = ("running",)

# Um job de despacho vivo é trabalho físico mesmo com a run em `queued`: o
# modelo está gerando neste instante.
ACTIVE_JOB_STATES = ("queued", "running")


def active_work(db, agent: str) -> dict | None:
    """Trabalho físico do agente agora, ou None. Base do bloqueio de parada."""
    from app.models.handoff import AgentBuildJob, AgentRun

    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.agent == agent,
            AgentRun.status.in_(PHYSICALLY_ACTIVE_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
        .first()
    )

    if run is not None:
        return {"run_id": str(run.id), "status": run.status, "reason": "run_running"}

    # Run ainda `queued` mas com despacho vivo: o modelo está trabalhando.
    job = (
        db.query(AgentBuildJob)
        .join(AgentRun, AgentRun.id == AgentBuildJob.run_id)
        .filter(
            AgentRun.agent == agent,
            AgentBuildJob.state.in_(ACTIVE_JOB_STATES),
        )
        .order_by(AgentBuildJob.created_at.desc())
        .first()
    )

    if job is not None:
        return {
            "run_id": str(job.run_id),
            "job_id": str(job.id),
            "status": job.state,
            "reason": "dispatch_active",
        }

    return None


# --------------------------------------------------------------------------
# Start / Stop idempotentes
# --------------------------------------------------------------------------


def start(agent: str, session: str, launcher: list[str]) -> dict:
    """Liga o agente. Chamar de novo com ele ligado não recria nada.

    Idempotência aqui não é cosmética: recriar a sessão mataria o trabalho em
    curso do agente que já estava rodando.
    """
    antes = read_state(agent, session)

    if antes.agent_process_running:
        return {
            "agent": agent,
            "started": False,
            "already_running": True,
            "state": antes.as_dict(),
        }

    # Sessão existe mas só com shell: é casca de standby, não agente. Recriar é
    # seguro e é o que devolve o agente ao ar.
    if antes.session_exists:
        _run(["tmux", "kill-session", "-t", f"={session}"], 5)

    resultado = _run(
        ["tmux", "new-session", "-d", "-s", session, "-c", "/opt/workdev", *launcher],
        15,
    )

    if resultado.returncode != 0:
        raise LifecycleError(
            "start_failed",
            resultado.stderr.strip() or "Falha ao iniciar a sessão tmux",
        )

    depois = read_state(agent, session)

    return {
        "agent": agent,
        "started": True,
        "already_running": False,
        "state": depois.as_dict(),
    }


def stop(agent: str, session: str | None, *, unload: bool = True) -> dict:
    """Desliga o agente de verdade: sessão, processos do grupo e modelo órfão.

    Idempotente: com o agente já desligado, devolve o estado offline sem erro.
    Desligar o que já está desligado não é falha operacional.
    """
    antes = read_state(agent, session)
    rss_antes = antes.rss_kb

    if antes.offline:
        return {
            "agent": agent,
            "stopped": False,
            "already_offline": True,
            "rss_freed_kb": 0,
            "model_unloaded": False,
            "state": antes.as_dict(),
        }

    pgid = antes.pgid
    encerramento = {"signalled": False, "survivors": [], "escalated": False}

    if session and antes.session_exists:
        # tmux primeiro: é a saída limpa, e costuma levar o grupo junto.
        _run(["tmux", "kill-session", "-t", f"={session}"], 5)

    # O grupo pode ter sobrevivido ao kill-session — filho reparentado para o
    # init continua consumindo memória e é invisível para o tmux. É esse caso
    # que fazia a tela mostrar OFFLINE com GB ainda ocupados.
    if pgid and group_pids(pgid):
        encerramento = terminate_group(pgid)

    modelo_descarregado = False
    motivo_modelo = "sem modelo associado"

    if unload and antes.model:
        usuarios = model_users(antes.model, excluding=agent)

        if usuarios:
            motivo_modelo = (
                f"mantido: também usado por {', '.join(usuarios)}"
            )
        elif not model_is_loaded(antes.model):
            motivo_modelo = "já não estava carregado"
        else:
            modelo_descarregado = unload_model(antes.model)
            motivo_modelo = (
                "descarregado" if modelo_descarregado
                else (
                    "ollama stop aceito, mas o modelo ainda estava residente "
                    f"após {UNLOAD_VERIFY_TIMEOUT_SECONDS:g}s; o "
                    "descarregamento é assíncrono — consulte o lifecycle "
                    "para confirmar a liberação"
                )
            )

    depois = read_state(agent, session)

    return {
        "agent": agent,
        "stopped": True,
        "already_offline": False,
        # Prova de liberação: RSS do grupo antes menos o que restou.
        "rss_freed_kb": max(0, rss_antes - depois.rss_kb),
        "model_unloaded": modelo_descarregado,
        "model_reason": motivo_modelo,
        "termination": encerramento,
        "state": depois.as_dict(),
    }
