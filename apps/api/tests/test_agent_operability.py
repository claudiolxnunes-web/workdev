"""Regressão da unificação do estado operacional (task 853b702d).

Defeito original: `/api/agents/status?workspace=true` publicava Codex como
ONLINE enquanto `/api/agents/codex/send` devolvia 503, porque a sessão tmux do
canal interativo não existia e o status vinha de outra fonte de verdade.

Cada teste aqui fixa uma das garantias do aceite. Todos sondam um tmux
simulado: o veredito não pode depender do que estiver no ar na VPS.
"""
import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.routers import terminal
from app.services import agent_lifecycle, agent_operability as operability, agent_snapshot

SPEC = importlib.util.spec_from_file_location(
    'operability_health', Path(__file__).parents[3] / 'scripts/agents_healthcheck.py')
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)


def probe_for(sessions: dict[str, str | None]):
    """Sondagem simulada. Valor None = sessão existe com painel morto."""
    def probe(name):
        if name not in sessions:
            return operability.SessionProbe(
                name=name, exists=False, reason=operability.REASON_NO_SESSION)
        process = sessions[name]
        if process is None:
            return operability.SessionProbe(
                name=name, exists=True, reason=operability.REASON_PANE_DEAD)
        return operability.SessionProbe(
            name=name, exists=True, attachable=True, process=process)
    return probe


def timing_out_probe(name):
    return operability.SessionProbe(
        name=name, determinate=False, reason=operability.REASON_PROBE_UNKNOWN)


@pytest.fixture
def snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / 'status.json'
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(path))
    monkeypatch.setattr(terminal, '_HEALTH_STATE_FILE', path)
    monkeypatch.setattr(agent_lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    return path


def client():
    app = FastAPI()
    app.include_router(terminal.router)
    return TestClient(app)


# --------------------------------------------------------------------------
# 1-3. Sessão ausente nunca é ONLINE, nem com processo sobrevivente
# --------------------------------------------------------------------------


@pytest.mark.parametrize('agent,session', [('codex', 'codex'), ('claude', 'code')])
def test_cli_sem_sessao_nunca_e_operacional(agent, session):
    state = operability.resolve(agent, standby_session=session, probe=probe_for({}))
    assert state.operational is False
    assert state.send_ready is False
    assert state.terminal_ready is False
    assert state.session_name is None
    assert state.session_source == 'none'
    assert state.health_reason == operability.REASON_NO_SESSION


def test_daemon_vivo_sem_tmux_nao_e_agente_operacional():
    """Codex App Server de pé não substitui o terminal: não é ONLINE."""
    state = operability.resolve(
        'codex', standby_session='codex', daemon_alive=True, probe=probe_for({}))
    assert state.daemon_alive is True
    assert (state.operational, state.send_ready) == (False, False)
    assert state.health_reason == operability.REASON_DAEMON_ONLY


def test_snapshot_de_daemon_sem_sessao_fica_error_com_motivo(snapshot_file):
    physical = agent_lifecycle.AgentState(agent='codex', session='codex', group_pids=[4242])
    state = operability.resolve(
        'codex', standby_session='codex', daemon_alive=True, probe=probe_for({}))
    row = agent_snapshot.from_physical('codex', physical, operability=state)
    assert row.runtime_state.value == 'ERROR'
    assert row.reason == operability.REASON_DAEMON_ONLY
    assert row.send_ready is False
    assert row.daemon_alive is True


# --------------------------------------------------------------------------
# 4-6. AUTO -> standby -> nenhuma
# --------------------------------------------------------------------------


def test_auto_valida_tem_precedencia_sobre_standby():
    sessions = {'auto-codex-r1': 'codex', 'codex': 'codex'}
    state = operability.resolve('codex', standby_session='codex', run_id='r1',
                                probe=probe_for(sessions))
    assert state.session_source == 'auto'
    assert state.session_name == 'auto-codex-r1'
    assert state.send_ready is True


def test_standby_so_e_usada_quando_auto_nao_existe():
    state = operability.resolve('codex', standby_session='codex', run_id='r1',
                                probe=probe_for({'codex': 'codex'}))
    assert state.session_source == 'standby'
    assert state.session_name == 'codex'
    assert state.send_ready is True


def test_auto_e_standby_mortas_devolvem_motivo_e_nenhuma_sessao():
    state = operability.resolve('codex', standby_session='codex', run_id='r1',
                                probe=probe_for({}))
    assert state.session_name is None
    assert state.send_ready is False
    assert state.health_reason == operability.REASON_NO_SESSION
    with pytest.raises(operability.OperabilityDenied):
        state.require('send')


def test_sessao_so_com_shell_abre_terminal_mas_nao_autoriza_send():
    state = operability.resolve('codex', standby_session='codex',
                                probe=probe_for({'codex': 'bash'}))
    assert state.terminal_ready is True
    assert state.send_ready is False
    assert state.health_reason == operability.REASON_SHELL_ONLY
    assert state.require('terminal') == 'codex'
    with pytest.raises(operability.OperabilityDenied):
        state.require('send')


def test_painel_morto_nao_conta_como_sessao_utilizavel():
    state = operability.resolve('codex', standby_session='codex',
                                probe=probe_for({'codex': None}))
    assert (state.operational, state.terminal_ready) == (False, False)
    assert state.health_reason == operability.REASON_PANE_DEAD


def test_sondagem_inconclusiva_nao_vira_offline_nem_online(snapshot_file):
    """Servidor tmux lento não apaga agente vivo nem promove agente morto."""
    state = operability.resolve('codex', standby_session='codex', probe=timing_out_probe)
    assert state.determinate is False
    assert (state.operational, state.send_ready) == (False, False)
    physical = agent_lifecycle.AgentState(agent='codex', session='codex')
    row = agent_snapshot.from_physical('codex', physical, operability=state)
    assert row.runtime_state.value == 'ERROR'
    assert row.reason == operability.REASON_PROBE_UNKNOWN


# --------------------------------------------------------------------------
# 7. /status e /send concordam; morte entre os dois é erro estruturado
# --------------------------------------------------------------------------


def publish_online(path, monkeypatch, *, send_ready=True):
    monkeypatch.setattr(operability, 'probe_session', probe_for({'codex': 'codex'}))
    physical = agent_lifecycle.AgentState(
        agent='codex', session='codex', session_exists=True, current_process='codex')
    state = operability.resolve('codex', standby_session='codex')
    row = agent_snapshot.from_physical('codex', physical, operability=state)
    agent_snapshot.publish([row], path)
    return row


def test_status_publica_online_e_send_ready_com_tmux_vivo(snapshot_file, monkeypatch):
    publish_online(snapshot_file, monkeypatch)
    with client() as api:
        row = next(r for r in api.get('/api/agents/status').json()['agents']
                   if r['agent'] == 'codex')
    assert row['runtime_state'] == 'ONLINE'
    assert row['running'] is True
    assert row['send_ready'] is True
    assert row['session_source'] == 'standby'


def test_status_sem_tmux_nunca_anuncia_running_nem_send_ready(snapshot_file, monkeypatch):
    monkeypatch.setattr(operability, 'probe_session', probe_for({}))
    physical = agent_lifecycle.AgentState(agent='codex', session='codex', group_pids=[7])
    state = operability.resolve('codex', standby_session='codex', daemon_alive=True)
    agent_snapshot.publish(
        [agent_snapshot.from_physical('codex', physical, operability=state)], snapshot_file)
    with client() as api:
        row = next(r for r in api.get('/api/agents/status').json()['agents']
                   if r['agent'] == 'codex')
    assert row['running'] is False
    assert row['send_ready'] is False
    assert row['health_reason'] == operability.REASON_DAEMON_ONLY


def test_send_endpoint_recusa_com_erro_estruturado_e_reconcilia(snapshot_file, monkeypatch):
    """O cenário exato do defeito: /status disse ONLINE, a sessão sumiu."""
    publish_online(snapshot_file, monkeypatch)
    before = agent_snapshot.read_snapshot(['codex'], snapshot_file)['agents'][0]
    assert (before['running'], before['send_ready']) == (True, True)

    monkeypatch.setattr(operability, 'probe_session', probe_for({}))
    monkeypatch.setattr(agent_lifecycle, 'active_work', lambda *a, **k: None)
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex', group_pids=[7]))
    sent = []
    monkeypatch.setattr(terminal, '_send_text', lambda *a: sent.append(a))

    with client() as api:
        response = api.post('/api/agents/codex/send', json={'text': 'oi'})

    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['code'] == 'agent_not_operational'
    assert detail['health_reason'] == operability.REASON_DAEMON_ONLY
    assert detail['session_source'] == 'none'
    assert sent == []  # nunca chegou a tentar o tmux send-keys

    # Snapshot reconciliado no mesmo instante, sem esperar o healthcheck.
    after = agent_snapshot.read_snapshot(['codex'], snapshot_file)['agents'][0]
    assert after['running'] is False
    assert after['send_ready'] is False
    assert after['health_reason'] == operability.REASON_DAEMON_ONLY


def test_websocket_recusa_quando_sessao_nao_e_anexavel(snapshot_file, monkeypatch):
    monkeypatch.setattr(operability, 'probe_session', probe_for({}))
    monkeypatch.setattr(agent_lifecycle, 'active_work', lambda *a, **k: None)
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex'))
    monkeypatch.setattr(terminal, 'websocket_is_authenticated', lambda _ws: True)
    attached = []
    monkeypatch.setattr(terminal.subprocess, 'Popen', lambda *a, **k: attached.append(a))

    import json

    with client() as api, api.websocket_connect('/ws/agents/codex') as socket:
        # Handshake completo: a aba recebe o motivo estruturado, não um 403 mudo.
        payload = json.loads(socket.receive_text())
        assert payload['running'] is False
        assert payload['terminal_ready'] is False
        assert payload['runtime_state'] == 'OFFLINE'
        assert payload['health_reason'] == operability.REASON_NO_SESSION
        closing = socket.receive()
        assert closing['type'] == 'websocket.close'
        assert operability.REASON_NO_SESSION in closing['reason']
    assert attached == []  # nenhum attach-session contra sessão inexistente


# --------------------------------------------------------------------------
# 8. Healthcheck: detecção em um ciclo e recovery com revalidação
# --------------------------------------------------------------------------


def test_healthcheck_detecta_sumico_da_sessao_em_um_ciclo(snapshot_file, monkeypatch):
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex', session_exists=True, current_process='codex'))
    monkeypatch.setattr(operability, 'probe_session', probe_for({'codex': 'codex'}))
    monkeypatch.setattr(health, 'capture_recent', lambda *a: '')
    monkeypatch.setattr(health, 'STATE_FILE', snapshot_file)
    online = health.collect_agent('codex', 'codex', None)
    assert online.runtime_state.value == 'ONLINE'

    # Um único ciclo depois, com a sessão morta e o daemon de pé.
    monkeypatch.setattr(operability, 'probe_session', probe_for({}))
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex', group_pids=[7]))
    offline = health.collect_agent('codex', 'codex', None)
    assert offline.runtime_state.value == 'ERROR'
    assert offline.reason == operability.REASON_DAEMON_ONLY
    assert offline.send_ready is False


def test_recovery_revalida_fisicamente_antes_de_declarar_online(snapshot_file, monkeypatch):
    """`started=True` é intenção cumprida, não prova de agente no ar."""
    live = {'up': False}

    def read_state(agent, session, **kw):
        return agent_lifecycle.AgentState(
            agent=agent, session=session, session_exists=live['up'],
            current_process='codex' if live['up'] else '')

    def probe(name):
        return probe_for({'codex': 'codex'} if live['up'] else {})(name)

    def recover(agent, session, launcher):
        live['up'] = True
        return {'agent': agent, 'started': True}

    monkeypatch.setattr(agent_lifecycle, 'read_state', read_state)
    monkeypatch.setattr(agent_lifecycle, 'try_recover', recover)
    monkeypatch.setattr(operability, 'probe_session', probe)
    monkeypatch.setattr(health, 'capture_recent', lambda *a: '')
    monkeypatch.setattr(health, 'RECOVERY_FILE', snapshot_file.with_name('recovery.json'))
    monkeypatch.setattr(agent_lifecycle, 'read_operation', lambda _agent: {})

    row = health.collect_agent('codex', 'codex', None, allow_restart=True)
    assert row.runtime_state.value == 'ONLINE'
    assert row.send_ready is True
    assert row.session_source == 'standby'


def test_recovery_que_nao_sobe_a_sessao_nao_vira_online(snapshot_file, monkeypatch):
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex'))
    monkeypatch.setattr(agent_lifecycle, 'try_recover',
                        lambda *a: {'agent': 'codex', 'started': False})
    monkeypatch.setattr(operability, 'probe_session', probe_for({}))
    monkeypatch.setattr(health, 'RECOVERY_FILE', snapshot_file.with_name('recovery.json'))
    monkeypatch.setattr(agent_lifecycle, 'read_operation', lambda _agent: {})
    row = health.collect_agent('codex', 'codex', None, allow_restart=True)
    assert row.runtime_state.value != 'ONLINE'
    assert row.send_ready is False


def test_backoff_para_de_tentar_apos_tres_falhas(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'RECOVERY_FILE', tmp_path / 'recovery.json')
    monkeypatch.setattr(agent_lifecycle, 'try_recover', lambda *a: (_ for _ in ()).throw(
        agent_lifecycle.LifecycleError('start_failed', 'launcher quebrado')))
    for _ in range(health.RECOVERY_MAX_ATTEMPTS):
        assert health.recovery_allowed('codex') is True
        assert health.attempt_recovery('codex', 'codex') is False
    assert health.recovery_allowed('codex') is False


def test_recovery_nao_destroi_sessao_viva_so_com_shell(snapshot_file, monkeypatch):
    """Casca de shell é diagnóstico do operador; recriar seria destrutivo."""
    monkeypatch.setattr(agent_lifecycle, 'read_state', lambda *a, **k: agent_lifecycle.AgentState(
        agent='codex', session='codex', session_exists=True, current_process='bash'))
    monkeypatch.setattr(operability, 'probe_session', probe_for({'codex': 'bash'}))
    monkeypatch.setattr(agent_lifecycle, 'read_operation', lambda _agent: {})
    def forbidden(*a, **k):
        raise AssertionError('recovery não pode matar sessão existente')
    monkeypatch.setattr(agent_lifecycle, 'try_recover', forbidden)
    row = health.collect_agent('codex', 'codex', None, allow_restart=True)
    assert row.runtime_state.value == 'ERROR'
    assert row.reason == operability.REASON_SHELL_ONLY


# --------------------------------------------------------------------------
# 9. Headless/HTTP preservados
# --------------------------------------------------------------------------


def test_headless_nao_ganha_requisito_de_tmux():
    state = operability.resolve('gpu-local', kind=operability.KIND_HEADLESS,
                                runtime_online=True)
    assert state.operational is True
    assert state.interactive is False
    assert state.session_source == 'none'
    assert state.terminal_ready is False


def test_headless_offline_tem_motivo_proprio():
    state = operability.resolve('gpu-local', kind=operability.KIND_HEADLESS,
                                runtime_online=False)
    assert (state.operational, state.health_reason) == (False, 'runtime_offline')


def test_headless_com_estado_desconhecido_e_indeterminado():
    state = operability.resolve('gpu-local', kind=operability.KIND_HEADLESS,
                                runtime_online=None)
    assert state.determinate is False
    assert state.health_reason == 'runtime_state_unknown'


def test_runtime_headless_mantem_online_sem_sessao_no_snapshot(snapshot_file, monkeypatch):
    """Regra antiga do runtime sem terminal continua valendo."""
    physical = agent_lifecycle.AgentState(agent='gpu-local', session=None,
                                          model='m', model_loaded=True)
    state = operability.resolve('gpu-local', kind=operability.KIND_HEADLESS,
                                runtime_online=True)
    row = agent_snapshot.from_physical('gpu-local', physical, operability=state)
    assert row.runtime_state.value == 'ONLINE'


# --------------------------------------------------------------------------
# Robustez do snapshot: descreve, nunca concede
# --------------------------------------------------------------------------


def test_snapshot_stale_perde_send_ready(snapshot_file, monkeypatch):
    publish_online(snapshot_file, monkeypatch)
    monkeypatch.setenv('AGENTS_HEALTH_MAX_AGE_SECONDS', '-1')
    row = agent_snapshot.read_snapshot(['codex'], snapshot_file)['agents'][0]
    assert row['runtime_state'] == 'ERROR'
    assert row['reason'] == 'snapshot_stale'
    assert row['send_ready'] is False


def test_snapshot_de_outro_boot_nao_e_reaproveitado(snapshot_file, monkeypatch):
    """Reinício da API não herda um retrato saudável de um sistema que morreu."""
    publish_online(snapshot_file, monkeypatch)
    monkeypatch.setattr(agent_snapshot, 'boot_id', lambda: 'boot-novo-depois-do-reinicio')
    row = agent_snapshot.read_snapshot(['codex'], snapshot_file)['agents'][0]
    assert row['runtime_state'] == 'ERROR'
    assert row['reason'] == 'snapshot_foreign_boot'
    assert row['send_ready'] is False
    assert row['running'] is False


# --------------------------------------------------------------------------
# Físico: tmux de verdade em socket privado, nunca o de produção
# --------------------------------------------------------------------------


@pytest.fixture
def private_tmux(tmp_path, monkeypatch):
    import subprocess

    socket = str(tmp_path / 'tmux.sock')
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(tmp_path / 'status.json'))
    monkeypatch.setattr(agent_lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    original = agent_lifecycle._run

    def scoped(args, timeout=10):
        if args and args[0] == 'tmux':
            args = ['tmux', '-S', socket, *args[1:]]
        return original(args, timeout)

    monkeypatch.setattr(agent_lifecycle, '_run', scoped)
    monkeypatch.setattr(health, 'run', scoped)
    monkeypatch.setattr(agent_lifecycle, 'active_work', lambda *a, **k: None)
    monkeypatch.setattr(health, 'capture_recent', lambda *a: '')
    yield scoped
    subprocess.run(['tmux', '-S', socket, 'kill-server'], capture_output=True, timeout=5)


def test_fisico_morte_da_tmux_com_daemon_vivo_derruba_online(private_tmux):
    """Aceite central: Codex sem sessão tmux nunca é ONLINE, nem com daemon.

    Sessão e processos são reais, mas num servidor tmux privado — o tmux de
    produção nunca é tocado por esta suíte.
    """
    import os
    import signal
    import subprocess
    import sys
    import time

    agent_lifecycle.start('codex', 'fixture', [sys.executable, '-c', 'import time; time.sleep(300)'])

    deadline = time.monotonic() + 5
    row = health.collect_agent('codex', 'fixture', None)
    while row.runtime_state.value != 'ONLINE' and time.monotonic() < deadline:
        time.sleep(.05)
        row = health.collect_agent('codex', 'fixture', None)
    assert row.runtime_state.value == 'ONLINE'
    assert row.send_ready is True
    assert row.terminal_ready is True
    assert row.session_source == 'standby'

    # Daemon auxiliar que sobrevive à sessão (o "Codex App Server" do enunciado).
    daemon = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                              start_new_session=True)
    try:
        assert agent_lifecycle.remember_group('codex', os.getpgid(daemon.pid))
        private_tmux(['tmux', 'kill-session', '-t', '=fixture'])

        dead = health.collect_agent('codex', 'fixture', None)
        assert dead.runtime_state.value != 'ONLINE'
        assert dead.send_ready is False
        assert dead.terminal_ready is False
        assert dead.daemon_alive is True
        assert dead.reason == operability.REASON_DAEMON_ONLY

        # E o resolvedor recusa o envio em vez de entregar um nome de sessão.
        state = operability.resolve('codex', standby_session='fixture', daemon_alive=True)
        with pytest.raises(operability.OperabilityDenied):
            state.require('send')
    finally:
        os.killpg(os.getpgid(daemon.pid), signal.SIGKILL)
        daemon.wait(timeout=5)


def test_fisico_sessao_viva_autoriza_send_e_terminal(private_tmux):
    import sys
    import time

    agent_lifecycle.start('codex', 'fixture', [sys.executable, '-c', 'import time; time.sleep(300)'])
    deadline = time.monotonic() + 5
    state = operability.resolve('codex', standby_session='fixture')
    while not state.operational and time.monotonic() < deadline:
        time.sleep(.05)
        state = operability.resolve('codex', standby_session='fixture')
    assert state.operational is True
    assert state.require('send') == 'fixture'
    assert state.require('terminal') == 'fixture'
    assert state.process_alive is True


def test_sessao_canonica_e_unica_para_router_e_healthcheck():
    assert terminal.ALLOWED_SESSIONS is operability.CLI_SESSIONS
    for agent, (session, _launcher) in health.AGENTS.items():
        assert operability.CLI_SESSIONS[agent] == session
