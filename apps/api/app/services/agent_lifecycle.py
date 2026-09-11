"""Ligar e desligar agentes locais de verdade (task 177a2f03).

O problema que este módulo resolve: `tmux kill-session` faz a sessão sumir da
lista, mas isso **não é** o agente estar desligado. Um filho que escapou do
process group continua vivo segurando GB de RAM, e o modelo carregado no Ollama
permanece residente em RAM/VRAM até alguém mandar descarregar. A tela dizia
OFFLINE; a memória dizia outra coisa.

Quatro regras estruturam o módulo:

1. **Ciclo do agente ≠ ciclo do modelo.** O modelo é recurso compartilhado:
   descarregá-lo porque UM agente parou pode derrubar outro que ainda o usa.
2. **O endpoint é parte da pergunta.** Sondar e descarregar acontecem via HTTP
   no endpoint DAQUELE runtime. A CLI `ollama` fala sempre com o Ollama local —
   usá-la para uma GPU remota responderia sobre a máquina errada e, ao
   descarregar, derrubaria o modelo do `local-code`.
3. **Encerrar é seletivo, nunca varredura.** Mata-se o process group da sessão
   daquele agente, obtido do `pane_pid`. Nada de varrer `ps` por nome: isso
   atingiria agente de terceiro e processo do host.
4. **Desconhecido não é limpo.** Sondagem que não respondeu vira estado
   desconhecido, nunca "nada carregado". Fail-open aqui faria a API declarar
   OFFLINE e confirmar liberação de memória sem prova alguma.

Revisão independente do Codex (2026-09-11, run 818d6076) rejeitou a primeira
versão por seis achados; os comentários abaixo marcam o que cada um mudou.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field


# Janela entre SIGTERM e SIGKILL. Curta o bastante para o operador não achar que
# travou; longa o bastante para uma CLI salvar estado e sair sozinha.
GRACEFUL_TIMEOUT_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.25

# Descarregar é assíncrono no Ollama. Estes controlam a CONFIRMAÇÃO de que o
# modelo saiu da memória — ver `unload_model`.
UNLOAD_VERIFY_TIMEOUT_SECONDS = 20.0
UNLOAD_POLL_SECONDS = 1.0

PROBE_TIMEOUT_SECONDS = 5.0
LOAD_TIMEOUT_SECONDS = 300.0

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


# --------------------------------------------------------------------------
# Exclusão mútua por agente (achado P2 da revisão)
#
# Sem isto, dois `start` concorrentes liam "sessão ausente" ao mesmo tempo e o
# segundo estourava com `duplicate session` — ou pior, matava a sessão que o
# primeiro acabara de criar. Idempotência sem serialização é só sorte.
# --------------------------------------------------------------------------

_locks_guard = threading.Lock()
_agent_locks: dict[str, threading.Lock] = {}


def agent_lock(agent: str) -> threading.Lock:
    with _locks_guard:
        if agent not in _agent_locks:
            _agent_locks[agent] = threading.Lock()
        return _agent_locks[agent]


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
    # None = desconhecido (sondagem não respondeu). Distinguir de False é o
    # que impede declarar OFFLINE sem prova (achado P1 da revisão).
    model_loaded: bool | None = False
    endpoint_configured: bool = False
    rss_kb: int = 0

    @property
    def agent_process_running(self) -> bool:
        """Sessão com processo que não é o shell — ou seja, agente de fato."""
        return bool(
            self.current_process
            and self.current_process not in SHELL_PROCESSES
        )

    @property
    def model_state_known(self) -> bool:
        return self.model_loaded is not None

    @property
    def offline(self) -> bool:
        """Definição de aceite da task.

        Não basta a sessão ter sumido: enquanto houver processo do grupo vivo
        ou modelo residente, há consumo de memória e o agente NÃO está offline.

        Estado de modelo desconhecido também não é offline — afirmar que a
        memória voltou sem ter conseguido olhar seria exatamente a mentira que
        esta task veio corrigir.
        """
        return (
            not self.session_exists
            and not self.group_pids
            and self.model_loaded is False
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
            "model_state_known": self.model_state_known,
            "endpoint_configured": self.endpoint_configured,
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


# --------------------------------------------------------------------------
# Endpoint do runtime
# --------------------------------------------------------------------------


def endpoint_for(agent: str) -> tuple[str | None, dict]:
    """Endpoint e cabeçalhos do runtime. Agente CLI não tem — devolve None."""
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    if runtime is None:
        return None, {}

    return agent_runtimes.base_url(runtime), agent_runtimes.auth_headers(runtime)


def running_models(endpoint: str | None, headers: dict | None = None):
    """Modelos residentes NO ENDPOINT informado, via `GET /api/ps`.

    Por que HTTP e não o binário `ollama`: a CLI fala sempre com o Ollama
    **local**. Usá-la para um runtime de GPU remota responderia sobre a máquina
    errada — e, no caminho de descarregar, derrubaria o modelo do `local-code`
    achando que estava mexendo na GPU. Foi o achado mais grave da revisão.

    Devolve `None` para **estado desconhecido** (timeout, rede, HTTP != 200).
    Desconhecido não é "vazio".
    """
    if not endpoint:
        return None

    try:
        import httpx

        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS) as client:
            resposta = client.get(f"{endpoint}/api/ps", headers=headers or {})
    except Exception:
        return None

    if resposta.status_code != 200:
        return None

    try:
        payload = resposta.json()
    except ValueError:
        return None

    modelos = payload.get("models")

    if not isinstance(modelos, list):
        return None

    return [
        str(item.get("name") or item.get("model") or "")
        for item in modelos
        if isinstance(item, dict) and (item.get("name") or item.get("model"))
    ]


def model_is_loaded(model: str | None, endpoint: str | None, headers=None):
    """True/False quando se sabe; **None** quando a sondagem não respondeu."""
    if not model:
        return False

    carregados = running_models(endpoint, headers)

    if carregados is None:
        return None

    return model in carregados


# --------------------------------------------------------------------------
# Modelo compartilhado
# --------------------------------------------------------------------------


def model_for_agent(agent: str) -> str | None:
    """Modelo Ollama do agente, quando ele for um runtime Ollama.

    Agente CLI (codex, claude, kimi, qwen, gemini) fala com API remota e não
    tem modelo residente aqui — devolve None, e nada é descarregado por ele.
    """
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    return agent_runtimes.model_for(runtime) if runtime else None


def model_users(model: str, *, excluding: str, db=None) -> list[str]:
    """Runtimes que de fato SEGURAM este modelo no mesmo endpoint.

    Duas correções da revisão vivem aqui:

    - o endpoint precisa ser o mesmo objeto de comparação usado para sondar e
      descarregar, senão "órfão" vira uma conclusão sobre a máquina errada;
    - configuração não é uso. Antes bastava outro runtime estar *configurado*
      com o mesmo modelo para bloquear o unload para sempre, mesmo desligado e
      sem trabalho nenhum. Agora só segura quem tem trabalho ativo — e, sem
      `db`, o comportamento permanece conservador (qualquer configurado segura),
      porque sem consultar não dá para afirmar que ninguém está usando.
    """
    from app.services import agent_runtimes

    endpoint, _headers = endpoint_for(excluding)

    candidatos = [
        runtime.id
        for runtime in agent_runtimes.RUNTIMES
        if runtime.id != excluding
        and agent_runtimes.model_for(runtime) == model
        and agent_runtimes.base_url(runtime) == endpoint
    ]

    if db is None:
        return candidatos

    return [
        runtime_id
        for runtime_id in candidatos
        if active_work(db, runtime_id) is not None
    ]


def load_model(
    model: str,
    endpoint: str | None,
    headers: dict | None = None,
) -> bool:
    """Carrega o modelo no endpoint — o 'Ligar' de um runtime Ollama.

    A revisão apontou que `POST /start` devolvia 409 para `local-code`: o plano
    pede carregar/descarregar modelo, e só o descarregar existia. Um `generate`
    sem prompt carrega o modelo e volta, sem gerar token.
    """
    if not endpoint or not model:
        return False

    try:
        import httpx

        with httpx.Client(timeout=LOAD_TIMEOUT_SECONDS) as client:
            resposta = client.post(
                f"{endpoint}/api/generate",
                headers=headers or {},
                json={"model": model, "prompt": "", "stream": False},
            )
    except Exception:
        return False

    if resposta.status_code != 200:
        return False

    return model_is_loaded(model, endpoint, headers) is True


def unload_model(
    model: str,
    endpoint: str | None,
    headers: dict | None = None,
    *,
    verify_timeout: float | None = None,
) -> bool:
    """Descarrega o modelo do endpoint e CONFIRMA que ele saiu da memória.

    `keep_alive: 0` é o mecanismo do próprio Ollama e funciona no endpoint
    remoto — ao contrário de `ollama stop`, que só alcança o Ollama local.

    Medido na VPS1 em 2026-09-11 com `qwen2.5-coder:7b-instruct-q3_K_S`: o
    descarregamento é **assíncrono**. O `ollama ps` manteve o modelo em
    `Stopping...` e o runner `llama-server` ficou com 4.7 GB de RSS por vários
    minutos antes de a memória voltar (RAM do host 7831 MB → 3372 MB).

    Por isso o retorno é o que a sondagem mostra depois, não o que a chamada
    alegou. `False` significa "ainda residente, ou não consegui verificar" — e
    é a resposta honesta para quem precisa saber se a memória voltou AGORA.
    """
    if not endpoint or not model:
        return False

    if verify_timeout is None:
        verify_timeout = UNLOAD_VERIFY_TIMEOUT_SECONDS

    try:
        import httpx

        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS * 2) as client:
            client.post(
                f"{endpoint}/api/generate",
                headers=headers or {},
                json={"model": model, "keep_alive": 0},
            )
    except Exception:
        return False

    limite = time.monotonic() + verify_timeout

    while time.monotonic() < limite:
        carregado = model_is_loaded(model, endpoint, headers)

        if carregado is False:
            return True
        # `None` é desconhecido: não confirma liberação sem prova.

        time.sleep(UNLOAD_POLL_SECONDS)

    return False


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------


def read_state(
    agent: str,
    session: str | None,
    *,
    known_pgid: int | None = None,
) -> AgentState:
    """Lê o estado do sistema.

    `known_pgid` existe por causa do achado P1 da revisão: depois que a sessão
    tmux morre não há mais `pane_pid` de onde tirar o grupo, e a leitura
    ingênua concluía "sem processos" — reportando OFFLINE com sobreviventes
    vivos segurando RAM. Quem já conhecia o PGID passa ele adiante para que os
    sobreviventes continuem visíveis.
    """
    estado = AgentState(agent=agent, session=session)

    estado.model = model_for_agent(agent)
    endpoint, headers = endpoint_for(agent)
    estado.endpoint_configured = bool(endpoint)

    if estado.model:
        estado.model_loaded = model_is_loaded(estado.model, endpoint, headers)
    else:
        # Agente sem modelo residente: estado conhecido e vazio, não incerto.
        estado.model_loaded = False

    if session:
        estado.session_exists = session_exists(session)

        if estado.session_exists:
            estado.current_process = current_process(session)
            estado.pane_pid = pane_pid(session)

            if estado.pane_pid:
                estado.pgid = pgid_of(estado.pane_pid)

    # O PGID conhecido prevalece quando a sessão já não existe — é ele que
    # revela o processo órfão que o tmux não enxerga mais.
    if estado.pgid is None and known_pgid:
        estado.pgid = known_pgid

    if estado.pgid:
        estado.group_pids = group_pids(estado.pgid)
        estado.rss_kb = group_rss_kb(estado.group_pids)

    return estado


# --------------------------------------------------------------------------
# Encerramento seletivo
# --------------------------------------------------------------------------


def terminate_group(pgid: int) -> dict:
    """SIGTERM no grupo, espera, SIGKILL no que sobrou.

    Só o process group daquele agente. Matar por nome atingiria o agente do
    vizinho e processos do host que por acaso compartilham o binário.
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
# Start / Stop idempotentes e serializados
# --------------------------------------------------------------------------


def start(agent: str, session: str | None, launcher: list[str] | None) -> dict:
    """Liga o agente. Chamar de novo com ele ligado não recria nada.

    Idempotência aqui não é cosmética: recriar a sessão mataria o trabalho em
    curso do agente que já estava rodando. O lock por agente garante que duas
    chamadas simultâneas não leiam "ausente" ao mesmo tempo.
    """
    with agent_lock(agent):
        antes = read_state(agent, session)

        # Runtime Ollama não tem sessão: ligar é CARREGAR O MODELO. Antes isto
        # devolvia 409 e o 'Ligar' do plano simplesmente não existia.
        if session is None:
            if not antes.model:
                raise LifecycleError(
                    "model_not_configured",
                    f"{agent} não tem modelo configurado para carregar",
                )

            if antes.model_loaded is True:
                return {
                    "agent": agent,
                    "started": False,
                    "already_running": True,
                    "state": antes.as_dict(),
                }

            endpoint, headers = endpoint_for(agent)

            if not endpoint:
                raise LifecycleError(
                    "endpoint_not_configured",
                    f"{agent} não tem endpoint configurado",
                )

            carregou = load_model(antes.model, endpoint, headers)

            if not carregou:
                raise LifecycleError(
                    "model_load_failed",
                    f"Não foi possível carregar {antes.model} em {agent}",
                )

            return {
                "agent": agent,
                "started": True,
                "already_running": False,
                "state": read_state(agent, session).as_dict(),
            }

        if antes.agent_process_running:
            return {
                "agent": agent,
                "started": False,
                "already_running": True,
                "state": antes.as_dict(),
            }

        # Sessão existe mas só com shell: casca de standby, não agente.
        if antes.session_exists:
            _run(["tmux", "kill-session", "-t", f"={session}"], 5)

        resultado = _run(
            [
                "tmux", "new-session", "-d", "-s", session,
                "-c", "/opt/workdev", *(launcher or []),
            ],
            15,
        )

        if resultado.returncode != 0:
            raise LifecycleError(
                "start_failed",
                resultado.stderr.strip() or "Falha ao iniciar a sessão tmux",
            )

        return {
            "agent": agent,
            "started": True,
            "already_running": False,
            "state": read_state(agent, session).as_dict(),
        }


def stop(agent: str, session: str | None, *, unload: bool = True, db=None) -> dict:
    """Desliga o agente de verdade: sessão, processos do grupo e modelo órfão.

    Idempotente e serializado. Com o agente já desligado, devolve o estado
    offline sem erro — desligar o que já está desligado não é falha.
    """
    with agent_lock(agent):
        antes = read_state(agent, session)
        rss_antes = antes.rss_kb
        pgid = antes.pgid

        if antes.offline:
            return {
                "agent": agent,
                "stopped": False,
                "already_offline": True,
                "rss_freed_kb": 0,
                "model_unloaded": False,
                "model_reason": "já estava offline",
                "termination": {
                    "signalled": False, "survivors": [], "escalated": False,
                },
                "state": antes.as_dict(),
            }

        encerramento = {"signalled": False, "survivors": [], "escalated": False}

        if session and antes.session_exists:
            # tmux primeiro: é a saída limpa, e costuma levar o grupo junto.
            _run(["tmux", "kill-session", "-t", f"={session}"], 5)

        # O grupo pode ter sobrevivido ao kill-session — filho reparentado para
        # o init continua consumindo memória e é invisível para o tmux. É esse
        # caso que fazia a tela mostrar OFFLINE com GB ainda ocupados.
        if pgid and group_pids(pgid):
            encerramento = terminate_group(pgid)

        modelo_descarregado = False
        motivo_modelo = "sem modelo associado"

        if unload and antes.model:
            endpoint, headers = endpoint_for(agent)
            usuarios = model_users(antes.model, excluding=agent, db=db)

            if usuarios:
                motivo_modelo = f"mantido: em uso por {', '.join(usuarios)}"
            elif antes.model_loaded is False:
                motivo_modelo = "já não estava carregado"
            elif antes.model_loaded is None:
                motivo_modelo = (
                    "estado desconhecido: a sondagem do endpoint não respondeu"
                )
            else:
                modelo_descarregado = unload_model(antes.model, endpoint, headers)
                motivo_modelo = (
                    "descarregado" if modelo_descarregado
                    else (
                        "ainda residente após "
                        f"{UNLOAD_VERIFY_TIMEOUT_SECONDS:g}s; o descarregamento "
                        "é assíncrono — consulte o lifecycle para confirmar"
                    )
                )

        # Releitura carregando o PGID original: sem isso, sobrevivente do grupo
        # ficaria invisível e o estado alegaria offline (achado P1).
        depois = read_state(agent, session, known_pgid=pgid)

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
