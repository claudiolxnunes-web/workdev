"""O servidor tmux dos agentes só nasce dentro do workdev-agents.service."""
import subprocess

import pytest

from app.services import agent_lifecycle

# Exercita a função real; o _run é simulado em cada teste.
pytestmark = pytest.mark.tmux_ensure_real


def resultado(codigo: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], codigo, "", stderr)


@pytest.fixture
def chamadas(monkeypatch):
    registro: list[list[str]] = []
    monkeypatch.setattr(agent_lifecycle.time, "sleep", lambda *_: None)
    return registro


def test_com_servidor_vivo_nao_chama_o_wrapper(chamadas, monkeypatch):
    def run(args, timeout=None):
        chamadas.append(args)
        return resultado(0)
    monkeypatch.setattr(agent_lifecycle, "_run", run)
    agent_lifecycle.ensure_tmux_server()
    assert chamadas == [["tmux", "list-sessions"]]


def test_sem_servidor_chama_o_wrapper_e_espera_responder(chamadas, monkeypatch):
    respostas = iter([1, 1, 0])  # ausente, ainda subindo, respondeu

    def run(args, timeout=None):
        chamadas.append(args)
        if args[0] == agent_lifecycle.AGENTS_CTL:
            return resultado(0)
        return resultado(next(respostas))
    monkeypatch.setattr(agent_lifecycle, "_run", run)
    agent_lifecycle.ensure_tmux_server()
    assert [agent_lifecycle.AGENTS_CTL, "ensure-server"] in chamadas
    assert chamadas.count(["tmux", "list-sessions"]) == 3


def test_wrapper_falhando_da_mensagem_clara(chamadas, monkeypatch):
    def run(args, timeout=None):
        if args[0] == agent_lifecycle.AGENTS_CTL:
            return resultado(1, "Interactive authentication required.")
        return resultado(1)
    monkeypatch.setattr(agent_lifecycle, "_run", run)
    with pytest.raises(agent_lifecycle.LifecycleError) as erro:
        agent_lifecycle.ensure_tmux_server()
    assert erro.value.code == "tmux_server_unavailable"
    assert "workdev-agents-ensure não o recriou" in str(erro.value)
    assert "Interactive authentication required" in str(erro.value)


def test_servidor_que_nao_volta_estoura_o_prazo(chamadas, monkeypatch):
    relogio = iter(range(0, 1000))
    monkeypatch.setattr(agent_lifecycle.time, "monotonic", lambda: next(relogio))

    def run(args, timeout=None):
        return resultado(0 if args[0] == agent_lifecycle.AGENTS_CTL else 1)
    monkeypatch.setattr(agent_lifecycle, "_run", run)
    with pytest.raises(agent_lifecycle.LifecycleError) as erro:
        agent_lifecycle.ensure_tmux_server()
    assert "não respondeu em" in str(erro.value)


def test_start_garante_o_servidor_antes_de_criar_a_sessao():
    import inspect
    fonte = inspect.getsource(agent_lifecycle)
    criacao = fonte.index('"tmux", "new-session", "-d", "-s", session,')
    assert "ensure_tmux_server()" in fonte[criacao - 300:criacao]


def test_terminal_auto_garante_o_servidor_antes_de_criar_a_sessao():
    import inspect
    from app.routers import terminal
    fonte = inspect.getsource(terminal)
    assert fonte.index("agent_lifecycle.ensure_tmux_server()") < fonte.index('"tmux", "new-session", "-d", "-s", session,')
