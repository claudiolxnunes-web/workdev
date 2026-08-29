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


router = APIRouter(tags=["agents"])
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


def _capture_history(session: str, lines: int) -> str:
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", session],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Sessão tmux indisponível")
    return result.stdout.rstrip()


def _scroll_terminal(session: str, direction: str) -> None:
    command = (
        ["tmux", "copy-mode", "-u", "-t", session]
        if direction == "up"
        else ["tmux", "send-keys", "-X", "-t", session, "page-down"]
    )
    subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    position = subprocess.run(
        ["tmux", "display-message", "-p", "-t", session, "#{scroll_position}"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if position.stdout.strip() in {"", "0"}:
        subprocess.run(
            ["tmux", "send-keys", "-X", "-t", session, "cancel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )


class AgentSendRequest(BaseModel):
    text: str


def _send_text(session: str, text: str) -> None:
    stripped = text.rstrip("\n")
    if stripped:
        literal = subprocess.run(
            ["tmux", "send-keys", "-t", session, "-l", "--", stripped],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if literal.returncode != 0:
            raise RuntimeError(literal.stderr.strip() or "Sessão tmux indisponível")
    enter = subprocess.run(
        ["tmux", "send-keys", "-t", session, "Enter"],
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
    lines: int = Query(default=5000, ge=100, le=20000),
):
    session = ALLOWED_SESSIONS.get(agent)
    if not session:
        raise HTTPException(status_code=404, detail="Agente inválido")
    try:
        content = await asyncio.to_thread(_capture_history, session, lines)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"agent": agent, "lines": len(content.splitlines()), "content": content}


def _resize(fd: int, rows: int, cols: int) -> None:
    rows = max(5, min(rows, 300))
    cols = max(10, min(cols, 500))
    import fcntl
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def _claim(session: str) -> bool:
    async with _connections_lock:
        if session in _active_connections:
            return False
        _active_connections.add(session)
        return True


async def _release(session: str) -> None:
    async with _connections_lock:
        _active_connections.discard(session)


async def _send_output(websocket: WebSocket, master_fd: int) -> None:
    while True:
        try:
            data = await asyncio.to_thread(os.read, master_fd, 65536)
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
        ["tmux", "display-message", "-p", "-t", session, "#{pane_current_command}"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""

def _start_gemini_headless_runtime(
    agent: str,
    prompt: str,
) -> dict:
    session = _standby_session(agent)

    _stop_standby_session(session)

    command = [
        *STANDBY_COMMANDS[agent],
        "--prompt",
        prompt,
    ]

    result = subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "-c",
            "/opt/workdev",
            *command,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "Falha ao iniciar Gemini headless"
        )

    return {
        "agent": agent,
        "session": session,
        "started": True,
        "process": "node",
    }

def _start_standby_session(agent: str, session: str) -> bool:
    current_process = _current_process(session)
    if current_process and current_process not in _SHELL_PROCESSES:
        return False
    if current_process:
        subprocess.run(
            ["tmux", "kill-session", "-t", session],
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
        ["tmux", "kill-session", "-t", session],
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


def start_agent_runtime(
    agent: str,
    prompt: str,
    timeout_seconds: float = 15.0,
) -> dict:
    session = _standby_session(agent)

    if agent == "gemini":
        return _start_gemini_headless_runtime(
            agent,
            prompt,
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


def stop_agent_runtime(
    agent: str,
) -> bool:
    session = _standby_session(agent)
    return _stop_standby_session(
        session,
    )

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
        r"allow this (action|command|tool)",
        r"deseja continuar", r"aprovar\s*\?", r"confirmar\s*\?",
        r"❯\s*1\.\s*(yes|sim)", r"press enter to continue",
    ]
]


def _awaiting_approval(session: str) -> bool:
    try:
        tail = _capture_history(session, 6)
    except RuntimeError:
        return False
    non_empty = [line for line in tail.splitlines() if line.strip()]
    recent = "\n".join(non_empty[-3:])
    return any(pattern.search(recent) for pattern in _APPROVAL_PATTERNS)


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


async def _agent_status(agent: str, session: str, supervisor: dict | None = None) -> dict:
    current_process = await asyncio.to_thread(_current_process, session)
    running = bool(current_process and current_process not in _SHELL_PROCESSES)
    awaiting_approval = await asyncio.to_thread(_awaiting_approval, session) if running else False
    health = supervisor or {}
    health_status = health.get("status")
    if health_status not in {"idle", "busy", "blocked", "offline", "degraded"}:
        health_status = "idle" if running else "offline"
    return {
        "agent": agent,
        "running": running,
        "process": _PROCESS_LABELS.get(agent, current_process) if running else current_process,
        "awaiting_approval": awaiting_approval,
        "health": health_status,
        "health_reason": health.get("reason"),
        "checked_at": health.get("checked_at"),
        "recovered": bool(health.get("recovered")),
    }


@router.get("/api/agents/status")
async def agents_status():
    supervisor = await asyncio.to_thread(_load_supervisor_health)
    results = await asyncio.gather(
        *(
            _agent_status(agent, session, supervisor.get(agent))
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
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen(
            ["tmux", "attach-session", "-t", session],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
            env=env,
        )
        os.close(slave_fd)
        slave_fd = -1
        initial_status = await _agent_status(agent, session)
        await websocket.send_text(json.dumps({"type": "status", **initial_status}))
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
            elif payload.get("type") == "scroll" and payload.get("direction") in {"up", "down"}:
                await asyncio.to_thread(_scroll_terminal, session, payload["direction"])
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
