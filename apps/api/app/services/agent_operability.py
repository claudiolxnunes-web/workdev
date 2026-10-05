"""Fonte única de verdade sobre a capacidade FÍSICA de um agente agora.

Invariante central (ADR docs/adr/0001-estado-operacional-derivado.md):

    O estado operacional é DERIVADO do sistema no momento do uso.
    Snapshot, PID, PGID e daemon auxiliar DESCREVEM; nunca CONCEDEM.

Antes deste módulo, `/api/agents/status` publicava Codex como ONLINE enquanto
`/api/agents/codex/send` devolvia 503: o status vinha de um snapshot (ou de um
process group sobrevivente) e o send ia direto no `tmux send-keys` de uma sessão
que não existia mais. Eram duas definições de "operacional" na mesma aba.

Aqui existe uma só. Todos os consumidores — status, send, history, terminal
(WebSocket), lifecycle, reset e healthcheck — chamam `resolve()` e obtêm o mesmo
veredito sobre o mesmo estado físico.

Para agentes CLI (tmux), ONLINE exige sessão física comprovada: `has-session`
exato, painel resolvível, painel vivo e anexável. Para agentes headless/HTTP a
regra é a do próprio runtime — exigir tmux deles seria um requisito artificial.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import subprocess


# Sessão tmux canônica de cada agente CLI. Era `terminal.ALLOWED_SESSIONS`;
# mora aqui porque o resolvedor é consumido também pelo healthcheck, que não
# pode importar o router (puxaria a app FastAPI inteira num oneshot).
CLI_SESSIONS = {
    "claude": "code",
    "codex": "codex",
    "kimi": "kimi",
    "qwen": "qwen",
    "grok": "grok",
    "deepseek": "deepseek",
    "gemini": "gemini",
}

SHELL_PROCESSES = frozenset({"bash", "dash", "fish", "sh", "tmux", "zsh"})

KIND_CLI = "cli"
KIND_HEADLESS = "headless"

SOURCE_AUTO = "auto"
SOURCE_STANDBY = "standby"
SOURCE_NONE = "none"

PROBE_TIMEOUT_SECONDS = 5

# Motivos estáveis. A UI e os testes dependem destes literais; mudá-los é
# mudança de contrato, não refactor.
REASON_NO_SESSION = "no_live_session"
REASON_DAEMON_ONLY = "daemon_alive_without_session"
REASON_SHELL_ONLY = "session_without_agent_process"
REASON_PROBE_UNKNOWN = "tmux_probe_timeout"
REASON_PANE_DEAD = "pane_dead"


class OperabilityDenied(RuntimeError):
    """Operação dependente de terminal recusada por ausência de sessão física.

    Carrega o estado resolvido para que o chamador devolva erro ESTRUTURADO em
    vez do 503 opaco que esta task veio eliminar.
    """

    def __init__(self, state: "OperationalState", operation: str):
        self.state = state
        self.operation = operation
        super().__init__(state.health_reason or REASON_NO_SESSION)


def auto_session_name(agent: str, run_id) -> str:
    """Mesma convenção do runtime AUTO, centralizada em agent_snapshot."""
    from app.services import agent_snapshot

    return agent_snapshot.auto_session_name(agent, run_id)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionProbe:
    """Resultado de uma sondagem física de sessão tmux."""

    name: str
    exists: bool = False
    # False só quando a sondagem RESPONDEU dizendo que não dá. Timeout vira
    # `determinate=False`: desconhecido não é ausência (achado 29/set/2026 —
    # servidor tmux lento não pode apagar da aba um agente vivo).
    attachable: bool = False
    process: str = ""
    determinate: bool = True
    reason: str | None = None

    @property
    def agent_process(self) -> bool:
        return bool(self.process) and self.process not in SHELL_PROCESSES


@dataclass(frozen=True)
class OperationalState:
    """Contrato único de operacionalidade. Tudo deriva do estado físico lido."""

    agent: str
    kind: str = KIND_CLI
    # Agente de fato no ar e apto a trabalhar.
    operational: bool = False
    # Tem canal interativo (terminal) por natureza. Headless nunca tem.
    interactive: bool = False
    session_name: str | None = None
    session_source: str = SOURCE_NONE
    session_exists: bool = False
    # Processo do agente (não o shell) rodando no painel.
    process_alive: bool = False
    # Comando do painel lido na mesma sondagem que decidiu a sessão. Reconsultar
    # depois abriria janela para divergir do veredito recém-tomado.
    process: str = ""
    # Processo/daemon auxiliar sobrevivente. NUNCA concede operacionalidade.
    daemon_alive: bool = False
    # `tmux send-keys` chegaria no agente agora.
    send_ready: bool = False
    # `tmux attach-session` funcionaria agora.
    terminal_ready: bool = False
    # None quando a sondagem não conseguiu concluir (nem vivo, nem morto).
    determinate: bool = True
    health_reason: str | None = None
    checked_at: str = field(default_factory=now)
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "kind": self.kind,
            "operational": self.operational,
            "interactive": self.interactive,
            "session_name": self.session_name,
            "session_source": self.session_source,
            "session_exists": self.session_exists,
            "process_alive": self.process_alive,
            "process": self.process,
            "daemon_alive": self.daemon_alive,
            "send_ready": self.send_ready,
            "terminal_ready": self.terminal_ready,
            "determinate": self.determinate,
            "health_reason": self.health_reason,
            "checked_at": self.checked_at,
        }

    def require(self, operation: str) -> str:
        """Autoriza `send`/`terminal` ou levanta OperabilityDenied.

        Único ponto de autorização. Nenhum caminho pode mandar texto para uma
        sessão sem passar por aqui — era exatamente assim que `_live_session`
        devolvia um nome de sessão inexistente para falhar depois no tmux.
        """
        allowed = self.send_ready if operation == "send" else self.terminal_ready
        if not allowed or not self.session_name:
            raise OperabilityDenied(self, operation)
        return self.session_name


# --------------------------------------------------------------------------
# Sondagem física
# --------------------------------------------------------------------------


def _tmux(args: list[str], timeout: int = PROBE_TIMEOUT_SECONDS):
    """Única porta de execução de tmux do backend.

    Delega ao `agent_lifecycle._run` de propósito: é lá que os testes de
    integração redirecionam o socket (`tmux -S ...`). Um `subprocess.run`
    próprio aqui sondaria o tmux de produção durante a suíte.
    """
    from app.services import agent_lifecycle

    return agent_lifecycle._run(["tmux", *args], timeout)


def probe_session(name: str) -> SessionProbe:
    """Sessão utilizável = has-session + painel resolvível + painel vivo.

    `has-session` sozinho não basta: um painel morto (`pane_dead`) responde ao
    `has-session` e recusa `send-keys`. Os três sinais vêm de duas chamadas
    com target exato (`=nome`), nunca por prefixo.
    """
    if not name:
        return SessionProbe(name="", exists=False, reason=REASON_NO_SESSION)
    try:
        if _tmux(["has-session", "-t", f"={name}"]).returncode != 0:
            return SessionProbe(name=name, exists=False, reason=REASON_NO_SESSION)
        pane = _tmux(
            [
                "display-message", "-p", "-t", f"={name}:",
                "#{pane_id}\t#{pane_dead}\t#{pane_current_command}",
            ]
        )
    except subprocess.TimeoutExpired:
        # Nem vivo nem morto: estado desconhecido, jamais ONLINE nem OFFLINE.
        return SessionProbe(name=name, determinate=False, reason=REASON_PROBE_UNKNOWN)
    if pane.returncode != 0:
        return SessionProbe(name=name, exists=True, reason=REASON_PANE_DEAD)
    parts = pane.stdout.strip().split("\t")
    pane_id = parts[0] if parts else ""
    dead = len(parts) > 1 and parts[1] == "1"
    process = parts[2].strip() if len(parts) > 2 else ""
    if not pane_id or dead:
        return SessionProbe(name=name, exists=True, reason=REASON_PANE_DEAD)
    return SessionProbe(name=name, exists=True, attachable=True, process=process)


# --------------------------------------------------------------------------
# Resolvedor canônico
# --------------------------------------------------------------------------


def resolve(
    agent: str,
    *,
    standby_session: str | None = None,
    run_id=None,
    daemon_alive: bool = False,
    kind: str = KIND_CLI,
    runtime_online: bool | None = None,
    probe=None,
) -> OperationalState:
    """Estado operacional físico do agente AGORA.

    CLI: AUTO (se houver run) → standby → nenhuma. Só a sessão que a sondagem
    confirmou utilizável vira `session_name`; nunca se devolve um nome na
    esperança de que exista.

    Headless/HTTP: `runtime_online` manda. Sem requisito de tmux.
    """
    if kind == KIND_HEADLESS:
        return _resolve_headless(agent, runtime_online, daemon_alive)
    # Resolvido aqui, não como default do parâmetro: assim substituir
    # `probe_session` no módulo (testes) realmente troca a sondagem.
    return _resolve_cli(agent, standby_session, run_id, daemon_alive, probe or probe_session)


def _resolve_headless(agent, runtime_online, daemon_alive) -> OperationalState:
    if runtime_online is None:
        return OperationalState(
            agent=agent, kind=KIND_HEADLESS, determinate=False,
            daemon_alive=daemon_alive, health_reason="runtime_state_unknown",
        )
    return OperationalState(
        agent=agent, kind=KIND_HEADLESS, operational=bool(runtime_online),
        daemon_alive=daemon_alive, process_alive=bool(runtime_online),
        health_reason=None if runtime_online else "runtime_offline",
    )


def _resolve_cli(agent, standby_session, run_id, daemon_alive, probe) -> OperationalState:
    candidates: list[tuple[str, str]] = []
    if run_id:
        candidates.append((SOURCE_AUTO, auto_session_name(agent, run_id)))
    if standby_session:
        candidates.append((SOURCE_STANDBY, standby_session))

    names = tuple(name for _, name in candidates)
    results = [(source, probe(name)) for source, name in candidates]

    # 1ª passada: sessão viva COM o processo do agente. É o único estado que
    # autoriza /send — mandar texto para um shell não é falar com o agente.
    for source, result in results:
        if result.determinate and result.attachable and result.agent_process:
            return OperationalState(
                agent=agent, kind=KIND_CLI, operational=True, interactive=True,
                session_name=result.name, session_source=source,
                session_exists=True, process_alive=True, process=result.process,
                daemon_alive=daemon_alive,
                send_ready=True, terminal_ready=True, candidates=names,
            )

    # 2ª passada: sessão viva, mas só com shell. O terminal abre (o operador
    # precisa ver a casca para consertá-la), o /send não é autorizado.
    for source, result in results:
        if result.determinate and result.attachable:
            return OperationalState(
                agent=agent, kind=KIND_CLI, operational=False, interactive=True,
                session_name=result.name, session_source=source,
                session_exists=True, process_alive=False, process=result.process,
                daemon_alive=daemon_alive,
                send_ready=False, terminal_ready=True,
                health_reason=REASON_SHELL_ONLY, candidates=names,
            )

    # Sondagem que não concluiu não vira OFFLINE: vira desconhecido explícito.
    if any(not result.determinate for _, result in results):
        return OperationalState(
            agent=agent, kind=KIND_CLI, interactive=True, determinate=False,
            daemon_alive=daemon_alive, health_reason=REASON_PROBE_UNKNOWN,
            candidates=names,
        )

    dead_pane = next(
        (result for _, result in results if result.reason == REASON_PANE_DEAD), None
    )
    return OperationalState(
        agent=agent, kind=KIND_CLI, interactive=True, daemon_alive=daemon_alive,
        health_reason=(
            REASON_PANE_DEAD if dead_pane is not None
            else REASON_DAEMON_ONLY if daemon_alive
            else REASON_NO_SESSION
        ),
        candidates=names,
    )


def from_agent_state(agent: str, state, session: str | None = None) -> OperationalState:
    """OperationalState derivado de um `AgentState` já lido, sem nova sondagem.

    Usado no desfecho de start/stop: o `read_state` acabou de sondar o tmux
    sob o mesmo lock da operação. Sondar outra vez aqui produziria dois
    vereditos sobre o mesmo instante — e um deles estaria errado.
    """
    session = session or getattr(state, "session", None)
    exists = bool(session) and bool(getattr(state, "session_exists", False))
    process = getattr(state, "current_process", "") or ""
    alive = bool(process) and process not in SHELL_PROCESSES
    daemon = bool(getattr(state, "group_pids", None))
    if exists and alive:
        return OperationalState(
            agent=agent, operational=True, interactive=True, session_name=session,
            session_source=SOURCE_AUTO if str(session).startswith("auto-") else SOURCE_STANDBY,
            session_exists=True, process_alive=True, process=process,
            daemon_alive=daemon, send_ready=True, terminal_ready=True,
        )
    if exists:
        return OperationalState(
            agent=agent, interactive=True, session_name=session,
            session_source=SOURCE_AUTO if str(session).startswith("auto-") else SOURCE_STANDBY,
            session_exists=True, process=process, daemon_alive=daemon,
            terminal_ready=True, health_reason=REASON_SHELL_ONLY,
        )
    return OperationalState(
        agent=agent, interactive=True, daemon_alive=daemon,
        health_reason=REASON_DAEMON_ONLY if daemon else REASON_NO_SESSION,
    )


def reconcile_snapshot(state: OperationalState, *, db=None) -> bool:
    """Reescreve o snapshot com o estado físico que acabou de ser observado.

    Chamado quando uma operação é recusada: a aba precisa parar de anunciar
    disponibilidade no mesmo instante em que o backend descobriu que ela não
    existe, sem esperar o próximo ciclo do healthcheck. Falha aqui nunca
    propaga — reconciliar é melhoria de observabilidade, não parte do erro
    que o chamador está prestes a devolver.
    """
    from app.services import agent_lifecycle, agent_snapshot

    try:
        physical = agent_lifecycle.read_state(
            state.agent, CLI_SESSIONS.get(state.agent), db=db
        )
        row = agent_snapshot.from_physical(state.agent, physical, operability=state)
        agent_snapshot.publish([row], source="reconcile")
        return True
    except Exception:  # noqa: BLE001 - diagnóstico não pode mascarar o erro real
        import logging

        logging.getLogger(__name__).warning(
            "falha ao reconciliar snapshot de %s apos recusa fisica", state.agent
        )
        return False


def resolve_from_state(agent: str, state, *, standby_session=None, run_id=None, probe=None):
    """Adapter para quem já tem um `agent_lifecycle.AgentState` em mãos.

    O `daemon_alive` sai de `group_pids`: processos do agente sobreviventes a
    uma sessão que morreu. É o "Codex App Server vivo" do enunciado — sinal de
    observabilidade, nunca de operacionalidade.
    """
    from app.services import agent_runtimes

    daemon_alive = bool(getattr(state, "group_pids", None))
    if standby_session is None:
        standby_session = CLI_SESSIONS.get(agent)
    if standby_session is None and agent_runtimes.is_ollama_agent(agent):
        return resolve(
            agent, kind=KIND_HEADLESS, daemon_alive=daemon_alive,
            runtime_online=getattr(state, "model_loaded", None),
        )
    return resolve(
        agent, standby_session=standby_session, run_id=run_id,
        daemon_alive=daemon_alive, probe=probe,
    )
