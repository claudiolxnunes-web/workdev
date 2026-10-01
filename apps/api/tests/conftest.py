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
