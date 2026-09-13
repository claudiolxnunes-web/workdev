"""Terminal web interativo por execução (run_id).

REST cria/inspeciona/encerra a TerminalSession da Task 4; o WebSocket faz a
ponte bidirecional com o PTY vivo (input, output em streaming, resize).
Fechar o navegador nunca encerra o PTY: reconexão é apenas um novo attach.
"""
import asyncio
import base64
import json
import logging
import threading
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.auth import websocket_is_authenticated
from app.database import SessionLocal
from app.models.handoff import AgentRun
from app.services.terminal_sessions import TerminalSessionManager, TerminalSessionError


logger = logging.getLogger('workdev.terminal')
router = APIRouter(tags=["run-terminal"])

# Writer/observer registry: produção roda um único processo uvicorn; o mapa em
# memória é autoridade suficiente e libera sempre em finally.
MAX_WS_CLIENTS_PER_RUN = 32
_clients_lock = threading.Lock()
_clients: dict[str, dict] = {}  # run_id -> {'writer': WebSocket|None, 'total': int}


def _claim(run_id: str, websocket: WebSocket, requested: str | None, takeover: bool):
    """Resolve o papel e registra o cliente. Retorna (role, motivo, writer_expulso)."""
    with _clients_lock:
        entry = _clients.setdefault(run_id, {'writer': None, 'total': 0})
        if entry['total'] >= MAX_WS_CLIENTS_PER_RUN:
            return None, 'Limite de clientes por execução atingido', None
        occupied = entry['writer'] is not None
        if requested == 'observer' or (requested is None and occupied):
            entry['total'] += 1
            logger.info('terminal observer attached run=%s', run_id)
            return 'observer', None, None
        kicked = None
        if occupied:
            if not takeover:
                return None, 'Escrita em uso por outro cliente (use takeover=1)', None
            kicked = entry['writer'] if entry['writer'] is not websocket else None
            if kicked is not None:
                logger.info('terminal writer takeover run=%s', run_id)
        entry['writer'] = websocket
        entry['total'] += 1
        logger.info('terminal writer claimed run=%s', run_id)
        return 'writer', None, kicked


def _release(run_id: str, websocket: WebSocket):
    with _clients_lock:
        entry = _clients.get(run_id)
        if entry is None:
            return
        was_writer = entry['writer'] is websocket
        if was_writer:
            entry['writer'] = None
        entry['total'] -= 1
        if entry['total'] <= 0:
            del _clients[run_id]
    if was_writer:
        logger.info('terminal writer released run=%s', run_id)


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
        # Canonical form: UUID aliases (case, sem hífens) não podem abrir slots paralelos.
        run_id = str(UUID(run_id))
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Execução inválida")
        return
    requested = websocket.query_params.get('role')
    if requested not in (None, 'writer', 'observer'):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Papel inválido")
        return
    takeover = websocket.query_params.get('takeover') == '1'
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
    role, rejection, kicked = _claim(run_id, websocket, requested, takeover)
    if role is None:
        logger.warning('terminal ws rejected run=%s reason=%s', run_id, rejection)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=rejection[:110])
        return

    output_task: asyncio.Task | None = None
    conn = None
    try:
        if kicked is not None:
            with suppress(Exception):
                await kicked.close(code=1000, reason='Escrita assumida por outro cliente')
        # Cancelamento do handler não pode cancelar a thread de attach
        # (shield), senão o socket tardio se perderia sem close.
        consumed = False
        attach_task = asyncio.ensure_future(asyncio.to_thread(_attach, run_id))
        try:
            conn, ack, pending = await asyncio.shield(attach_task)
            consumed = True
        except asyncio.CancelledError as cancel:
            def _close_orphan(done):
                if consumed or done.cancelled():
                    return
                with suppress(Exception):
                    done.result()[0].close()
            attach_task.add_done_callback(_close_orphan)
            raise cancel
        except (TerminalSessionError, OSError, ValueError) as error:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(error)[:110])
            return
        await websocket.accept()
        snapshot = base64.b64decode(ack.get("output", ""))
        if snapshot:
            await websocket.send_bytes(snapshot)
        await websocket.send_text(json.dumps({
            "type": "status", "state": ack.get("state"), "pid": ack.get("pid"), "role": role,
        }))
        output_task = asyncio.create_task(_stream_output(websocket, conn, pending))

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if not text or role != 'writer':
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
        # Liberação garantida em normal, abrupto, erro e cancelamento.
        _release(run_id, websocket)
        if output_task:
            output_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await output_task
        # Só o attach morre aqui — o PTY/worker sobrevive para reconexão.
        if conn is not None:
            with suppress(OSError):
                conn.close()
