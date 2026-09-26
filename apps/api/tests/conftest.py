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
