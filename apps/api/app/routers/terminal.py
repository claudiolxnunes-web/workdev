import time
import asyncio
import json
import os
import pty
import re
import struct
import subprocess
import termios
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.auth import websocket_is_authenticated
from app.database import SessionLocal
from app.models.handoff import AgentRun
from app.services.terminal_transcript import clean_terminal_text, read_transcript


router = APIRouter(tags=["agents"])

# Isolamento estrito: uma sessão persistente por agente configurado. O tmux é o
# terminal manual do agente, não um mecanismo de orquestração — o fluxo
# principal é PLAN → recomendação → escolha do usuário → envio ao agente
# escolhido, que trabalha aqui. Sessões dinâmicas por execução pertencem apenas
# ao runtime AUTO, que é opt-in (ver `_auto_runtime_enabled` em routers/handoffs).
ALLOWED_SESSIONS = {
    "claude": "code",
    "codex": "codex",
    "kimi": "kimi",
    "qwen": "qwen",
    "gemini": "gemini",
}
STANDBY_COMMANDS = {
    "claude": ["/opt/workdev/scripts/start_claude_agent.sh"],
    "codex": ["/opt/workdev/scripts/start_codex_agent.sh"],
    "kimi": ["/opt/workdev/scripts/start_kimi_agent.sh"],
    "qwen": ["/opt/workdev/scripts/start_qwen_agent.sh"],
    "gemini": ["/opt/workdev/scripts/start_gemini_agent.sh"],
}
_active_connections: set[str] = set()
_connections_lock = asyncio.Lock()
_SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}
_PROCESS_LABELS = {"qwen": "qwen-code"}
_HEALTH_STATE_FILE = Path(os.getenv("AGENTS_HEALTH_STATE", "/var/lib/agents-healthcheck/status.json"))
_HEALTH_MAX_AGE_SECONDS = 15 * 60


def _session_target(session: str) -> str:
    """Força correspondência exata de target-session."""
    return f"={session}"


def _pane_target(session: str) -> str:
    """Força sessão exata ao resolver o painel ativo."""
    return f"={session}:"


def _capture_history(session: str, lines: int) -> str:
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", _pane_target(session)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Sessão tmux indisponível")
    return result.stdout.rstrip()


class AgentSendRequest(BaseModel):
    text: str


def _send_text(session: str, text: str) -> None:
    stripped = text.rstrip("\n")
    if stripped:
        literal = subprocess.run(
            ["tmux", "send-keys", "-t", _pane_target(session), "-l", "--", stripped],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if literal.returncode != 0:
            raise RuntimeError(literal.stderr.strip() or "Sessão tmux indisponível")
    enter = subprocess.run(
        ["tmux", "send-keys", "-t", _pane_target(session), "Enter"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if enter.returncode != 0:
        raise RuntimeError(enter.stderr.strip() or "Falha ao confirmar envio")


@router.post("/api/agents/{agent}/send")
async def agent_send(agent: str, payload: AgentSendRequest):
    session = ALLOWED_SESSIONS.get(agent)
    if not session:
        raise HTTPException(status_code=404, detail="Agente inválido")
    try:
        await asyncio.to_thread(_send_text, session, payload.text)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"agent": agent, "sent": True}


@router.get("/api/agents/{agent}/history")
async def agent_history(
    agent: str,
    lines: int = Query(default=10000, ge=100, le=100000),
):
    session = ALLOWED_SESSIONS.get(agent)
    if not session:
        raise HTTPException(status_code=404, detail="Agente inválido")
    try:
        content = await asyncio.to_thread(_capture_history, session, lines)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"agent": agent, "lines": len(content.splitlines()), "content": content}


@router.get("/api/agents/{agent}/transcript")
async def agent_transcript(agent: str):
    if agent not in ALLOWED_SESSIONS:
        raise HTTPException(status_code=404, detail="Agente inválido")
    content, updated_at = await asyncio.to_thread(read_transcript, agent)
    return {
        "agent": agent,
        "lines": len(content.splitlines()),
        "content": content,
        "updated_at": updated_at,
    }


def _resize(fd: int, rows: int, cols: int) -> None:
    rows = max(5, min(rows, 300))
    cols = max(10, min(cols, 500))
    import fcntl
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _requested_terminal_size(websocket: WebSocket) -> tuple[int, int]:
    """Lê o tamanho inicial sem confiar nos valores enviados pelo navegador."""
    try:
        rows = int(websocket.query_params.get("rows", "24"))
        cols = int(websocket.query_params.get("cols", "80"))
    except (TypeError, ValueError):
        return 24, 80
    return max(5, min(rows, 300)), max(10, min(cols, 500))


async def _claim(session: str) -> bool:
    async with _connections_lock:
        if session in _active_connections:
            return False
        _active_connections.add(session)
        return True


async def _release(session: str) -> None:
    async with _connections_lock:
        _active_connections.discard(session)


async def _read_pty(master_fd: int) -> bytes:
    """Espera dados do PTY sem ocupar uma thread bloqueada em ``os.read``."""
    loop = asyncio.get_running_loop()
    readable = asyncio.Event()
    loop.add_reader(master_fd, readable.set)
    try:
        await readable.wait()
        return os.read(master_fd, 65536)
    finally:
        loop.remove_reader(master_fd)


async def _send_output(websocket: WebSocket, master_fd: int) -> None:
    while True:
        try:
            data = await _read_pty(master_fd)
        except OSError:
            return
        if not data:
            return
        try:
            await websocket.send_bytes(data)
        except Exception:
            # The browser may disconnect while PTY output is still in flight.
            # Treat that as a normal end-of-stream so terminal cleanup can run.
            return


def _current_process(session: str) -> str:
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", _pane_target(session), "#{pane_current_command}"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""

def _start_gemini_headless_runtime(
    agent: str,
    prompt: str,
    model: str | None = None,
) -> dict:
    session = _standby_session(agent)

    command = [
        *STANDBY_COMMANDS[agent],
        *(["--model", model] if model else []),
        "--prompt",
        prompt,
    ]

    result = subprocess.run(
        command,
        cwd="/opt/workdev",
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or f"Gemini headless encerrou com código {result.returncode}"
        )

    return {
        "agent": agent,
        "session": session,
        "started": True,
        "process": "gemini",
        "returncode": result.returncode,
    }

def _start_standby_session(agent: str, session: str) -> bool:
    current_process = _current_process(session)
    if current_process and current_process not in _SHELL_PROCESSES:
        return False
    if current_process:
        subprocess.run(
            ["tmux", "kill-session", "-t", _session_target(session)],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    result = subprocess.run(
        [
            "tmux", "new-session", "-d", "-s", session,
            "-c", "/opt/workdev", *STANDBY_COMMANDS[agent],
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Falha ao iniciar sessão tmux")
    return True


def _stop_standby_session(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "kill-session", "-t", _session_target(session)],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if result.returncode == 0:
        return True
    if "can't find session" in result.stderr or "no server running" in result.stderr:
        return False
    raise RuntimeError(result.stderr.strip() or "Falha ao encerrar sessão tmux")

def _standby_session(agent: str) -> str:
    session = ALLOWED_SESSIONS.get(agent)
    if not session:
        raise HTTPException(status_code=404, detail="Agente inválido")
    if agent not in STANDBY_COMMANDS:
        raise HTTPException(
            status_code=409,
            detail="Agente sem launcher standby configurado",
        )
    return session


def _auto_session(agent: str, run_id) -> str:
    _standby_session(agent)
    return f"auto-{agent}-{run_id}"

def start_agent_runtime(
    agent: str,
    prompt: str,
    timeout_seconds: float = 15.0,
    model: str | None = None,
    run_id = None,
) -> dict:
    session = _auto_session(agent, run_id) if run_id else _standby_session(agent)

    if agent == "gemini":
        return _start_gemini_headless_runtime(
            agent,
            prompt,
            model,
        )

    started = _start_standby_session(
        agent,
        session,
    )

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        process = _current_process(session)

        ready = (
            process
            and process not in _SHELL_PROCESSES
        )

        if ready and agent == "gemini":
            history = _capture_history(
                session,
                80,
            )
            ready = "Type your message" in history

        if ready:

            _send_text(
                session,
                prompt,
            )
            return {
                "agent": agent,
                "session": session,
                "started": started,
                "process": process,
            }

        time.sleep(0.25)

    raise RuntimeError(
        f"{agent}: sessão iniciou, mas a CLI não ficou pronta"
    )


def stop_agent_runtime(agent: str, run_id) -> bool:
    session = _auto_session(agent, run_id)
    return _stop_standby_session(session)


def auto_runtime_running(agent: str, run_id) -> bool:
    process = _current_process(_auto_session(agent, run_id))
    return bool(process and process not in _SHELL_PROCESSES)


def finalize_auto_runtime(agent: str, run_id) -> dict:
    """Encerra só a sessão AUTO e confirma que o agente está em standby."""
    auto_session = _auto_session(agent, run_id)
    stopped = _stop_standby_session(auto_session)
    standby_session = _standby_session(agent)
    standby_started = _start_standby_session(agent, standby_session)
    process = _current_process(standby_session)
    if not process or process in _SHELL_PROCESSES:
        raise RuntimeError(f"{agent}: não retornou ao standby")
    return {
        "session": auto_session,
        "stopped": stopped,
        "standby_session": standby_session,
        "standby_started": standby_started,
        "standby_process": process,
    }

@router.post("/api/agents/{agent}/session")
async def start_agent_session(agent: str):
    session = _standby_session(agent)
    try:
        started = await asyncio.to_thread(_start_standby_session, agent, session)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"agent": agent, "running": True, "started": started}


@router.delete("/api/agents/{agent}/session")
async def stop_agent_session(agent: str):
    session = _standby_session(agent)
    try:
        stopped = await asyncio.to_thread(_stop_standby_session, session)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"agent": agent, "running": False, "stopped": stopped}


# Heurística, não parsing exato por CLI: cada agente (Claude/Codex/Kimi/Qwen)
# formata seu próprio prompt de aprovação de um jeito diferente e não há uma
# forma segura de descobrir os formatos exatos sem interromper uma sessão
# real. Checa só as últimas linhas não vazias para reduzir falso positivo
# vindo de texto de saída antigo que já rolou pra fora da tela.
_APPROVAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\(y/n\)", r"\[y/n\]", r"\by/n\b",
        r"do you want to proceed", r"do you approve",
        r"allow (?:this )?(?:execution|action|command|tool)",
        r"approve\?", r"proceed\?", r"confirm\?",
        r"allow once", r"allow for this session",
        r"permission required", r"requires? (?:your )?approval",
        r"would you like to (?:run|execute|proceed)",
        r"deseja continuar", r"aprovar\s*\?", r"confirmar\s*\?",
        r"❯\s*1\.\s*(yes|sim)", r"press enter to continue",
    ]
]

_USER_PROMPT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"type your message", r"what can i (?:do|help)",
        r"(?:^|\n)\s*[>❯›]\s*$", r"enter your (?:prompt|message)",
    ]
]
_COMPLETED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [r"build concluído", r"task completed", r"completed successfully", r"concluído com sucesso"]
]
_ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [r"fatal error", r"unhandled exception", r"process exited", r"encerrou com código [1-9]"]
]
_RESUMED_PATTERN = re.compile(
    r"(?:aplicando|continuando|executing|running command|conclu[ií]do|completed|finished)",
    re.IGNORECASE,
)


def _approval_state(session: str) -> tuple[bool, str | None]:
    try:
        tail = _capture_history(session, 60)
    except RuntimeError:
        return False, None
    non_empty = [line for line in tail.splitlines() if line.strip()]
    recent_lines = non_empty[-20:]
    recent = "\n".join(recent_lines)
    matches = [
        index
        for index, line in enumerate(recent_lines)
        if any(pattern.search(line) for pattern in _APPROVAL_PATTERNS)
    ]
    if not matches:
        return False, None
    last_match = matches[-1]
    if _RESUMED_PATTERN.search("\n".join(recent_lines[last_match + 1:])):
        return False, None
    prompt = clean_terminal_text("\n".join(recent_lines[max(0, last_match - 2):]))
    return True, prompt or None


def _awaiting_approval(session: str) -> bool:
    return _approval_state(session)[0]


def _load_run_states() -> dict[str, str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AgentRun)
            .filter(AgentRun.status.in_(("queued", "running", "blocked", "review")))
            .order_by(AgentRun.created_at.desc())
            .all()
        )
        states: dict[str, str] = {}
        for row in rows:
            states.setdefault(row.agent, row.status)
        return states
    except Exception:
        return {}
    finally:
        db.close()


def _operational_status(
    session: str,
    running: bool,
    health_status: str,
    awaiting_approval: bool,
    run_status: str | None,
) -> str:
    if awaiting_approval:
        return "awaiting_approval"
    if health_status == "blocked" or run_status == "blocked":
        return "blocked"
    if not running or health_status in {"offline", "degraded"}:
        return "error"
    if run_status == "review":
        return "awaiting_user"
    if run_status == "running" or health_status == "busy":
        return "executing"
    try:
        recent = _capture_history(session, 40)
    except RuntimeError:
        return "error"
    if any(pattern.search(recent) for pattern in _ERROR_PATTERNS):
        return "error"
    if any(pattern.search(recent) for pattern in _COMPLETED_PATTERNS):
        return "completed"
    if any(pattern.search(recent) for pattern in _USER_PROMPT_PATTERNS):
        return "awaiting_user"
    return "standby"


def _load_supervisor_health() -> dict[str, dict]:
    try:
        payload = json.loads(_HEALTH_STATE_FILE.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age > _HEALTH_MAX_AGE_SECONDS:
            return {}
        agents = payload.get("agents", {})
        return agents if isinstance(agents, dict) else {}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {}


async def _agent_status(
    agent: str,
    session: str,
    supervisor: dict | None = None,
    run_status: str | None = None,
) -> dict:
    current_process = await asyncio.to_thread(_current_process, session)
    running = bool(current_process and current_process not in _SHELL_PROCESSES)
    awaiting_approval, approval_prompt = (
        await asyncio.to_thread(_approval_state, session) if running else (False, None)
    )
    health = supervisor or {}
    health_status = health.get("status")
    if health_status not in {"idle", "busy", "blocked", "offline", "degraded"}:
        health_status = "idle" if running else "offline"
    return {
        "agent": agent,
        "running": running,
        "process": _PROCESS_LABELS.get(agent, current_process) if running else current_process,
        "awaiting_approval": awaiting_approval,
        "approval_prompt": approval_prompt,
        "operational_status": await asyncio.to_thread(
            _operational_status,
            session,
            running,
            health_status,
            awaiting_approval,
            run_status,
        ),
        "health": health_status,
        "health_reason": health.get("reason"),
        "checked_at": health.get("checked_at"),
        "recovered": bool(health.get("recovered")),
    }


def agent_runtime_snapshot() -> dict[str, dict]:
    """Estado real das sessões, síncrono e tolerante a falha.

    Usado pela recomendação consultiva do PLAN. Quando a sonda não consegue
    ler o tmux, o agente fica marcado como NÃO verificado — nunca como
    disponível por suposição.
    """
    supervisor = _load_supervisor_health()
    snapshot: dict[str, dict] = {}

    for agent, session in ALLOWED_SESSIONS.items():
        try:
            current_process = _current_process(session)
        except Exception as error:  # tmux ausente, timeout, socket inacessível
            snapshot[agent] = {
                "agent": agent,
                "checked": False,
                "running": None,
                "health": None,
                "error": str(error),
            }
            continue

        running = bool(
            current_process and current_process not in _SHELL_PROCESSES
        )
        health = supervisor.get(agent) or {}
        health_status = health.get("status")

        if health_status not in {"idle", "busy", "blocked", "offline", "degraded"}:
            health_status = "idle" if running else "offline"

        snapshot[agent] = {
            "agent": agent,
            "checked": True,
            "running": running,
            "health": health_status,
            "health_reason": health.get("reason"),
            "checked_at": health.get("checked_at"),
        }

    return snapshot


@router.get("/api/agents/status")
async def agents_status():
    supervisor = await asyncio.to_thread(_load_supervisor_health)
    run_states = await asyncio.to_thread(_load_run_states)
    results = await asyncio.gather(
        *(
            _agent_status(agent, session, supervisor.get(agent), run_states.get(agent))
            for agent, session in ALLOWED_SESSIONS.items()
        )
    )
    return {"agents": list(results)}


@router.websocket("/ws/agents/{agent}")
async def agent_terminal(websocket: WebSocket, agent: str):
    if not websocket_is_authenticated(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Não autenticado")
        return
    session = ALLOWED_SESSIONS.get(agent)
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Agente inválido")
        return
    if not await _claim(session):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Terminal já está em uso")
        return

    master_fd = slave_fd = -1
    process: subprocess.Popen[bytes] | None = None
    output_task: asyncio.Task | None = None
    try:
        await websocket.accept()
        master_fd, slave_fd = pty.openpty()
        rows, cols = _requested_terminal_size(websocket)
        _resize(master_fd, rows, cols)
        run_states = await asyncio.to_thread(_load_run_states)
        initial_status = await _agent_status(agent, session, run_status=run_states.get(agent))
        await websocket.send_text(json.dumps({"type": "status", **initial_status}))
        try:
            history = await asyncio.to_thread(_capture_history, session, 5000)
        except (RuntimeError, subprocess.TimeoutExpired):
            history = ""
        await websocket.send_text(json.dumps({
            "type": "snapshot",
            "content": history,
        }))
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen(
            ["tmux", "attach-session", "-t", _session_target(session)],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
            env=env,
        )
        os.close(slave_fd)
        slave_fd = -1
        output_task = asyncio.create_task(_send_output(websocket, master_fd))

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                os.write(master_fd, message["bytes"])
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "input" and isinstance(payload.get("data"), str):
                os.write(master_fd, payload["data"].encode())
            elif payload.get("type") == "resize":
                _resize(master_fd, int(payload.get("rows", 24)), int(payload.get("cols", 80)))
    except WebSocketDisconnect:
        pass
    finally:
        try:
            if output_task:
                output_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await output_task
            if process and process.poll() is None:
                with suppress(OSError):
                    process.terminate()
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=2)
                if process.poll() is None:
                    with suppress(OSError):
                        process.kill()
            if master_fd >= 0:
                with suppress(OSError):
                    os.close(master_fd)
            if slave_fd >= 0:
                with suppress(OSError):
                    os.close(slave_fd)
        finally:
            await _release(session)
