"""Terminal web interativo por execução (run_id).

REST cria/inspeciona/encerra a TerminalSession da Task 4; o WebSocket faz a
ponte bidirecional com o PTY vivo (input, output em streaming, resize).
Fechar o navegador nunca encerra o PTY: reconexão é apenas um novo attach.
"""
import asyncio
import base64
import json
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.auth import websocket_is_authenticated
from app.database import SessionLocal
from app.models.handoff import AgentRun
from app.services.terminal_sessions import TerminalSessionManager, TerminalSessionError


router = APIRouter(tags=["run-terminal"])


def _session_payload(item) -> dict:
    return {
        "id": str(item.id),
        "run_id": str(item.run_id),
        "state": item.state,
        "pid": item.pid,
        "cwd": item.cwd,
        "exit_code": item.exit_code,
        "error": item.error,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "closed_at": item.closed_at.isoformat() if item.closed_at else None,
    }


def _create(run_id: str):
    with SessionLocal() as db:
        manager = TerminalSessionManager(db)
        return _session_payload(manager.create(run_id))


def _health(run_id: str):
    with SessionLocal() as db:
        manager = TerminalSessionManager(db)
        item, worker = manager.snapshot(run_id)
        run = db.get(AgentRun, UUID(run_id))
        buffer = (worker or {}).get('output_base64', '')
        # Compatibility with an already-running Task 5 worker.
        if worker and 'output_base64' not in worker:
            buffer = base64.b64encode(worker.get('output', '').encode()).decode()
        return {
            **_session_payload(item),
            'run': {'id': str(run.id), 'status': run.status},
            'process': {'pid': item.pid, 'supervisor_pid': item.supervisor_pid,
                        'identity': item.process_identity, 'alive': worker is not None and item.state == 'RUNNING'},
            'pty': {'path': item.pty_path, 'available': worker is not None and item.state == 'RUNNING'},
            'buffer': {'data': buffer, 'encoding': 'base64', 'limit_bytes': 65536,
                       'available': worker is not None, 'retention': 'worker_lifetime'},
        }


def _close(run_id: str):
    with SessionLocal() as db:
        manager = TerminalSessionManager(db)
        return _session_payload(manager.close(run_id))


def _write(run_id: str, text: str) -> None:
    with SessionLocal() as db:
        TerminalSessionManager(db).write(run_id, text)


def _resize(run_id: str, rows: int, cols: int) -> None:
    with SessionLocal() as db:
        TerminalSessionManager(db).resize(run_id, rows, cols)


def _attach(run_id: str):
    with SessionLocal() as db:
        return TerminalSessionManager(db).attach(run_id)


@router.post("/api/runs/{run_id}/terminal")
async def create_run_terminal(run_id: str):
    """Cria (idempotente) a sessão de terminal persistente da execução."""
    try:
        UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Execução inválida")
    try:
        return await asyncio.to_thread(_create, run_id)
    except TerminalSessionError as error:
        detail = str(error)
        code = 404 if "Run not found" in detail else 409
        raise HTTPException(status_code=code, detail=detail) from error


@router.get("/api/runs/{run_id}/terminal")
async def run_terminal_state(run_id: str):
    try:
        UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Execução inválida")
    try:
        return await asyncio.to_thread(_health, run_id)
    except TerminalSessionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/runs/{run_id}/terminal/reconnect")
async def reconnect_run_terminal(run_id: str):
    """Resolve an existing terminal. The WS recreates only the client bridge."""
    snapshot = await run_terminal_state(run_id)
    if snapshot['state'] != 'RUNNING' or not snapshot['pty']['available']:
        raise HTTPException(409, detail=snapshot)
    return {**snapshot, 'websocket_url': f'/ws/runs/{run_id}/terminal?existing=1'}


@router.delete("/api/runs/{run_id}/terminal")
async def close_run_terminal(run_id: str):
    """Encerra de vez o PTY da execução (mata o processo e descendentes)."""
    try:
        UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Execução inválida")
    try:
        return await asyncio.to_thread(_close, run_id)
    except TerminalSessionError as error:
        detail = str(error)
        code = 404 if "no terminal session" in detail else 409
        raise HTTPException(status_code=code, detail=detail) from error


async def _stream_output(websocket: WebSocket, conn, pending: bytes) -> None:
    """Empurra cada chunk do PTY para o browser até o worker fechar."""
    loop = asyncio.get_running_loop()
    buffer = bytearray(pending)
    try:
        while True:
            # An attach ack can arrive together with complete stream events.
            while b"\n" in buffer:
                line, _, rest = bytes(buffer).partition(b"\n")
                buffer = bytearray(rest)
                try:
                    event = json.loads(line)
                    data = base64.b64decode(event.get("output", ""))
                except (ValueError, TypeError):
                    continue
                if data:
                    await websocket.send_bytes(data)
            chunk = await loop.sock_recv(conn, 65536)
            if not chunk:
                return
            buffer.extend(chunk)
    except (OSError, WebSocketDisconnect, RuntimeError):
        return
    finally:
        # Worker EOF must reach the browser, otherwise a dead PTY looks connected.
        with suppress(Exception):
            await websocket.close(code=1000, reason="Terminal stream ended")


@router.websocket("/ws/runs/{run_id}/terminal")
async def run_terminal_ws(websocket: WebSocket, run_id: str):
    if not websocket_is_authenticated(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Não autenticado")
        return
    try:
        UUID(run_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Execução inválida")
        return
    try:
        # Recovery is explicitly attach-only; retain Task 5's legacy first-open contract.
        if websocket.query_params.get('existing') == '1':
            await asyncio.to_thread(_health, run_id)
        else:
            await asyncio.to_thread(_create, run_id)
    except TerminalSessionError as error:
        reason = "Execução não encontrada" if "Run not found" in str(error) else str(error)[:110]
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
        return
    try:
        conn, ack, pending = await asyncio.to_thread(_attach, run_id)
    except (TerminalSessionError, OSError, ValueError) as error:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(error)[:110])
        return

    output_task: asyncio.Task | None = None
    try:
        await websocket.accept()
        snapshot = base64.b64decode(ack.get("output", ""))
        if snapshot:
            await websocket.send_bytes(snapshot)
        await websocket.send_text(json.dumps({
            "type": "status", "state": ack.get("state"), "pid": ack.get("pid"),
        }))
        output_task = asyncio.create_task(_stream_output(websocket, conn, pending))

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            try:
                if payload.get("type") == "input" and isinstance(payload.get("data"), str):
                    await asyncio.to_thread(_write, run_id, payload["data"])
                elif payload.get("type") == "resize":
                    await asyncio.to_thread(
                        _resize, run_id,
                        payload.get("rows", 24), payload.get("cols", 80),
                    )
            except TerminalSessionError:
                # PTY encerrou entre mensagens; o stream de saída sinaliza o fim.
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if output_task:
            output_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await output_task
        # Só o attach morre aqui — o PTY/worker sobrevive para reconexão.
        with suppress(OSError):
            conn.close()
