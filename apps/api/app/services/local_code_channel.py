"""Handshake for the existing local-code CLI; lifecycle still owns the process.

No worker/PTY/server is created here. A durable reservation spans API/worker
restarts. Qwen hooks acknowledge delivery; tmux keystrokes alone are not proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import UUID, uuid4

from app.services import agent_lifecycle as lifecycle, agent_snapshot

AGENT = SESSION = 'local-code'
MARKER = 'WORKDEV_BUILD'
CANCEL_MARKER = 'WORKDEV_CANCEL'
IDLE_MARKER = 'WORKDEV_IDLE'
ACK_TIMEOUT = 15.0


def root():
    return lifecycle.GROUPS_FILE.parent / 'local-code-channel'


@contextmanager
def channel_lock():
    with agent_snapshot.file_lock(root() / 'channel.lock'):
        yield


def read():
    try:
        data = json.loads((root() / 'state.json').read_text())
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('schema')
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise lifecycle.LifecycleError('channel_unknown', 'Registro da CLI indisponível') from error


def save(data):
    agent_snapshot.atomic_json(root() / 'state.json', {**data, 'version': 1})


def identity_matches(data):
    return bool(data.get('pid') and data.get('starttime')
                and lifecycle.process_starttime(data['pid']) == data['starttime']
                and lifecycle.session_exists(SESSION)
                and lifecycle.pane_pid(SESSION) == data['pid'])


def previous_process_exited(data):
    """Absence/reused PID is evidence; permission/read errors are not."""
    try:
        stat = Path(f"/proc/{int(data['pid'])}/stat").read_text()
        fields = stat[stat.rfind(')') + 2:].split()
        return fields[0] == 'Z' or fields[19] != str(data['starttime'])
    except FileNotFoundError:
        return True
    except (OSError, ValueError, KeyError, IndexError):
        return False


def abandoned_without_tools(data):
    return previous_process_exited(data) and not data.get('tools') and not data.get('background_work')


def _hook_identity():
    """A hook must descend from the canonical pane's current process."""
    pid = lifecycle.pane_pid(SESSION)
    if not pid:
        raise lifecycle.LifecycleError('cli_missing', 'Sessão local-code ausente')
    current = os.getpid()
    ancestors = set()
    while current > 1 and current not in ancestors:
        ancestors.add(current)
        try:
            stat = Path(f'/proc/{current}/stat').read_text()
            current = int(stat[stat.rfind(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    if pid not in ancestors:
        raise lifecycle.LifecycleError('hook_identity_mismatch', 'Hook fora do Qwen canônico')
    return {'pid': pid, 'starttime': lifecycle.process_starttime(pid)}


def _block(reason):
    return {'decision': 'block', 'reason': reason}


def hook(payload):
    """Called locally by Qwen. No API key, DB connection or model invocation."""
    identity = _hook_identity()
    event = payload.get('hook_event_name')
    qwen_session = payload.get('session_id')
    with channel_lock():
        data = read()
        if event == 'SessionStart' or (event == 'UserPromptSubmit' and payload.get('prompt', '').strip() == 'WORKDEV_READY'):
            if data and all(data.get(k) == v for k, v in identity.items()) and data.get('qwen_session') == qwen_session:
                return _block('Canal WorkDev pronto') if event == 'UserPromptSubmit' else {}
            if data.get('run_id'):
                # A restarted CLI cannot silently adopt an in-flight run.
                data['phase'] = 'uncertain'
                data['replacement'] = {**identity, 'qwen_session': qwen_session,
                                       'input_file': os.environ['WORKDEV_LOCAL_CODE_INPUT_FILE']}
                save(data)
                return _block('Entrega pendente requer reconciliação') if event == 'UserPromptSubmit' else {}
            save({**identity, 'qwen_session': qwen_session, 'phase': 'idle',
                  'input_file': os.environ['WORKDEV_LOCAL_CODE_INPUT_FILE']})
            return _block('Canal WorkDev pronto') if event == 'UserPromptSubmit' else {}
        if any(data.get(k) != v for k, v in identity.items()) or data.get('qwen_session') != qwen_session:
            return _block('Identidade da CLI mudou; despacho requer reconciliação')
        if event == 'UserPromptSubmit':
            prompt = payload.get('prompt', '').strip()
            delivery = f"{MARKER} {data.get('run_id')} {data.get('nonce')}"
            cancel = f"{CANCEL_MARKER} {data.get('run_id')} {data.get('nonce')}"
            idle = f"{IDLE_MARKER} {data.get('qwen_session')} {data.get('turn_nonce')}"
            if (prompt == idle and data.get('phase') == 'finishing'
                    and not data.get('tools') and not data.get('background_work')):
                data['phase'] = 'turn_done' if data.get('run_id') else 'idle'
                save(data)
                return _block('Turno concluído; canal ocioso confirmado')
            if prompt == cancel and data.get('phase') == 'cancelling':
                if data.get('tools') or data.get('background_work'):
                    return _block('Há ferramentas pendentes; cancelamento ainda não confirmado')
                data.update(phase='cancelled', cancel_ack=True)
                save(data)
                return _block('Run interrompida pelo WorkDev; sessão preservada')
            if prompt == delivery and data.get('phase') == 'reserved':
                content = (root() / f"{UUID(data['run_id'])}.txt").read_text()
                if sha256(content.encode()).hexdigest() != data.get('prompt_sha256'):
                    return _block('Contexto alterado após a reserva')
                data.update(phase='busy', acknowledged=True, turn_nonce=uuid4().hex)
                save(data)
                return {'hookSpecificOutput': {
                    'hookEventName': 'UserPromptSubmit', 'additionalContext': content,
                }}
            if prompt.startswith((MARKER, CANCEL_MARKER, IDLE_MARKER)):
                return _block('Entrega duplicada ou marcador inválido')
            if data.get('run_id'):
                return _block('Run reservada pelo WorkDev; use Parar Run antes de outro prompt')
            data.update(phase='manual', turn_nonce=uuid4().hex)
            save(data)
        elif event in {'Stop', 'StopFailure'}:
            # Stop with active background work is not proof of an idle CLI.
            tasks = [task for task in (payload.get('background_tasks') or [])
                     if task.get('status') not in {'completed', 'failed', 'cancelled'}]
            crons = payload.get('crons') or []
            data['background_work'] = bool(tasks or crons)
            if tasks or crons or data.get('tools') or payload.get('stop_hook_active'):
                data['phase'] = 'uncertain'
            elif data.get('phase') != 'cancelling':
                data['phase'] = 'finishing'
                append_input(data, f"{IDLE_MARKER} {qwen_session} {data.get('turn_nonce')}")
            save(data)
        elif event == 'SessionEnd':
            data['phase'] = 'uncertain' if data.get('run_id') else 'offline'
            save(data)
        elif event == 'PreToolUse' and data.get('phase') in {'cancelling', 'cancelled', 'uncertain'}:
            return {'hookSpecificOutput': {
                'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'Run interrompida ou identidade incerta',
            }}
        elif event == 'PreToolUse':
            data['tools'] = list(set(data.get('tools', [])) | {payload.get('tool_use_id') or 'unknown'})
            save(data)
        elif event in {'PostToolUse', 'PostToolUseFailure'}:
            data['tools'] = [key for key in data.get('tools', []) if key != payload.get('tool_use_id')]
            save(data)
        return {}


def reserve(run_id, job_id, prompt):
    """Caller holds lifecycle agent lock. Return None while offline/busy."""
    run_id = str(UUID(str(run_id)))
    with channel_lock():
        data = read()
        if data.get('run_id') or data.get('phase') != 'idle' or not identity_matches(data):
            return None
        path = root() / f'{run_id}.txt'
        # Exclusive creation protects the context of a previous attempt.
        with path.open('x', encoding='utf-8') as out:
            os.chmod(path, 0o600)
            out.write(prompt)
            out.flush()
            os.fsync(out.fileno())
        data.update(run_id=run_id, job_id=str(job_id), nonce=uuid4().hex,
                    prompt_sha256=sha256(prompt.encode()).hexdigest(),
                    phase='reserved', acknowledged=False, reserved_at=time.time())
        save(data)
        lifecycle._save_run_binding(run_id, dict(
            agent=AGENT, session=SESSION, pid=data['pid'], starttime=data['starttime'],
            mode='persistent_cli', stopped=False, job_id=str(job_id),
            prompt_sha256=data['prompt_sha256'],
        ))
        return data


def send_marker(data, *, cancel=False):
    """Transport only; success here does not mean the CLI accepted the run."""
    if not identity_matches(data):
        raise lifecycle.LifecycleError('identity_mismatch', 'Qwen foi substituído; envio recusado')
    marker = CANCEL_MARKER if cancel else MARKER
    literal = f"{marker} {data['run_id']} {data['nonce']}"
    # No prompt content or shell syntax is sent to the terminal.
    if cancel:
        result = lifecycle._run(['tmux', 'send-keys', '-t', f'={SESSION}:', 'Escape'], 5)
        if result.returncode:
            raise lifecycle.LifecycleError('delivery_uncertain', 'Interrupção não enviada')
    append_input(data, literal)


def append_input(data, literal):
    # Qwen's native JSONL input watcher only submits when the interactive TUI
    # is idle. It neither creates another CLI nor types a shell command.
    path = Path(data['input_file'])
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise lifecycle.LifecycleError('input_not_private', 'Canal de entrada não é privado')
        payload = (json.dumps({'type': 'submit', 'text': literal}) + '\n').encode()
        if os.write(fd, payload) != len(payload):
            raise lifecycle.LifecycleError('delivery_uncertain', 'Escrita parcial; sem reenvio')
        os.fsync(fd)
    finally:
        os.close(fd)


def wait_ack(run_id, *, cancel=False, timeout=ACK_TIMEOUT):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with channel_lock():
            data = read()
        if data.get('run_id') != str(run_id) or not identity_matches(data):
            break
        if data.get('cancel_ack' if cancel else 'acknowledged'):
            return data
        time.sleep(.1)
    raise lifecycle.LifecycleError('cli_ack_timeout', 'CLI não confirmou; reserva preservada, sem reenvio')


def stop(run_id, *, locked=False):
    """Run lock is held by caller. Never kill the persistent pane/process."""
    key = str(run_id)
    from contextlib import nullcontext
    with (nullcontext() if locked else lifecycle.agent_lock(AGENT)):
        binding = lifecycle.run_binding(AGENT, key)
        if not binding or binding.get('mode') != 'persistent_cli':
            raise lifecycle.LifecycleError('run_unbound', 'Run sem vínculo persistente')
        if binding.get('stopped'):
            return {'stopped': True, 'already_stopped': True, 'session': SESSION}
        with channel_lock():
            data = read()
            if data.get('run_id') != key:
                raise lifecycle.LifecycleError('identity_mismatch', 'Run não ocupa mais esta CLI')
            if not identity_matches(data):
                if not abandoned_without_tools(data):
                    raise lifecycle.LifecycleError('identity_mismatch', 'CLI mudou; trabalho residual requer inspeção')
                data.update(phase='cancelled', cancel_ack=True, process_exited=True)
                save(data)
            if data.get('phase') == 'turn_done':
                data.update(phase='cancelled', cancel_ack=True)
                save(data)
            elif not data.get('cancel_ack'):
                data['phase'] = 'cancelling'
                save(data)
        if not data.get('cancel_ack'):
            send_marker(data, cancel=True)
            wait_ack(key, cancel=True)
        binding['stopped'] = True
        lifecycle._save_run_binding(key, binding)
        # Keep reservation until workflow cancellation commits/reconciles.
        return {'stopped': True, 'already_stopped': False, 'session': SESSION}


def release(run_id):
    """Only after confirmed idle and terminal workflow (or cancelled binding)."""
    with channel_lock():
        data = read()
        if data.get('run_id') != str(run_id) or data.get('phase') not in {'turn_done', 'cancelled'}:
            return False
        if not identity_matches(data):
            if not abandoned_without_tools(data):
                return False
            replacement = data.get('replacement', {})
            save({**replacement, 'phase': 'idle'} if identity_matches(replacement) else {})
            return True
        save({key: data[key] for key in ('pid', 'starttime', 'qwen_session', 'input_file')} | {'phase': 'idle'})
        return True
