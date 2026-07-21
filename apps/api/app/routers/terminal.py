import asyncio
import json
import os
import pty
import struct
import subprocess
import termios
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.auth import websocket_is_authenticated


router = APIRouter(tags=["agents"])
ALLOWED_SESSIONS = {
    "claude": "code",
    "codex": "codex",
    "kimi": "kimi",
    "qwen": "qwen",
}
_active_connections: set[str] = set()
_connections_lock = asyncio.Lock()
_SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}
_PROCESS_LABELS = {"qwen": "qwen-code"}


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
        current_process = await asyncio.to_thread(_current_process, session)
        running = bool(current_process and current_process not in _SHELL_PROCESSES)
        await websocket.send_text(json.dumps({
            "type": "status",
            "running": running,
            "process": _PROCESS_LABELS.get(agent, current_process) if running else current_process,
        }))
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
