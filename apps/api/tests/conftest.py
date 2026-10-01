"""Isola os testes da config real do servidor (/opt/workdev/config/user.json):
por padrao a supervisao adaptativa (Jev) fica desligada, igual ao default do
AdaptiveConfig, nao importa o que estiver ligado em producao. Um teste que
precisa dela ligada faz o proprio monkeypatch.setattr(adaptive_config, 'load',
lambda: config) (como ja faz test_adaptive_supervision.py), que sobrescreve
este default sem problema."""
import pytest

from app.services import adaptive_config


@pytest.fixture(autouse=True)
def _isolate_adaptive_supervision_config(monkeypatch):
    monkeypatch.setattr(adaptive_config, 'load', lambda: adaptive_config.AdaptiveConfig())


@pytest.fixture(autouse=True)
def _isolate_cli_model_selection(tmp_path, monkeypatch):
    """Nunca gravar a seleção real de /var/lib/agents-healthcheck/cli-models.json.

    O fluxo de ligar agente chama cli_agent_models.record_active; sem isto, o
    gate de deploy (que roda esta suíte) sobrescrevia o modelo ativo de
    produção, e uma rodada como root deixava o arquivo ilegível para a API."""
    monkeypatch.setenv('WORKDEV_CLI_AGENT_MODELS_FILE', str(tmp_path / 'cli-models.json'))


def pytest_configure(config):
    config.addinivalue_line("markers", "tmux_ensure_real: usa o ensure_tmux_server real (com _run simulado)")


@pytest.fixture(autouse=True)
def _isolate_tmux_server_ensure(request, monkeypatch):
    """Testes nunca acionam o workdev-agents-ensure de verdade.

    O start de agentes chama ensure_tmux_server(), que sem servidor pediria ao
    systemd a unidade real. Nos testes ela vira no-op, exceto onde o próprio
    teste exercita a função (marcador tmux_ensure_real) com _run simulado."""
    if request.node.get_closest_marker("tmux_ensure_real"):
        return
    from app.services import agent_lifecycle
    monkeypatch.setattr(agent_lifecycle, "ensure_tmux_server", lambda: None)
