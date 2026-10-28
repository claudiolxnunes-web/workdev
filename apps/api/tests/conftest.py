"""Isola os testes da config real do servidor (/opt/workdev/config/user.json):
por padrao a supervisao adaptativa (Jev) fica desligada, igual ao default do
AdaptiveConfig, nao importa o que estiver ligado em producao. Um teste que
precisa dela ligada faz o proprio monkeypatch.setattr(adaptive_config, 'load',
lambda: config) (como ja faz test_adaptive_supervision.py), que sobrescreve
este default sem problema."""
import urllib.parse
import urllib.request

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


@pytest.fixture(autouse=True)
def _isolate_ai_telemetry(tmp_path, monkeypatch):
    """A telemetria do loop de tools (tool_loop.registrar) não grava no checkout real."""
    monkeypatch.setenv('AI_TELEMETRIA_DIR', str(tmp_path / 'ai-telemetria'))


@pytest.fixture(autouse=True)
def _isolate_semantic_complement(monkeypatch):
    """O complemento semântico do Build (ADR 011) fica desligado na suíte.

    Sem isto, toda montagem de prompt chamaria o RAG de verdade — embedding
    pago, latência de rede e um resultado que depende do índice externo. O
    piso lexical é o que a suíte precisa enxergar; o complemento tem suíte
    própria, com o `rag_search` mockado.
    """
    monkeypatch.setenv('WORKDEV_SEMANTIC_COMPLEMENT', '0')


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


@pytest.fixture(autouse=True)
def _isolate_live_tmux_sessions(monkeypatch):
    """Testes de envio nunca enxergam as sessões tmux reais do host.

    O bloqueio de sessão viva com modelo divergente sonda a sessão standby;
    sem isto, o resultado dependia de existir (ou não) uma sessão real de
    codex/claude no servidor. Testes que exercitam o bloqueio sobrescrevem."""
    from app.routers import handoffs
    monkeypatch.setattr(handoffs, "_standby_session_alive", lambda agent: False)


@pytest.fixture(autouse=True)
def _nunca_chamar_a_api_real(monkeypatch):
    """Nenhum teste fala com a API de produção em 127.0.0.1:8000.

    Achado em 2026-10-26: test_deploy_pipeline rodava o pipeline inteiro e o
    _persist_deployment_outcome fazia POST real em /api/deployments/outcomes —
    3 por rodada da suíte, inclusive no gate do prepare. Como workdev dava 401
    (a chave em /etc/workdev-deploy/api.key é ilegível); como root, gravaria
    deploys falsos no banco e sujaria o DORA. Teste que precisa de HTTP
    monkeypatcha urlopen por cima desta trava, como os de contrato já fazem.
    """
    original = urllib.request.urlopen

    def urlopen_vigiado(alvo, *args, **kwargs):
        url = alvo.full_url if isinstance(alvo, urllib.request.Request) else str(alvo)
        destino = urllib.parse.urlsplit(url)
        if destino.hostname in ("127.0.0.1", "localhost", "0.0.0.0") and destino.port == 8000:
            raise RuntimeError(f"teste tentou chamar a API real: {url}")
        return original(alvo, *args, **kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen_vigiado)


@pytest.fixture(autouse=True)
def _isolate_supervisor_config(tmp_path, monkeypatch):
    """O supervisor dos testes não mexe na configuração real nem chama o observer.

    A auditoria (observer) e a autocorreção do supervisor speak de rede e de
    arquivo: desligadas por padrão na suíte, como o resto das travas daqui."""
    from app.services import supervisor_config
    from app.services.config_service import config_service

    monkeypatch.setattr(config_service, 'runtime_config_path', tmp_path / 'runtime.json')
    monkeypatch.setattr(config_service, 'user_config_path', tmp_path / 'user.json')
    monkeypatch.setattr(supervisor_config, '_caminho_auditoria', lambda: tmp_path / 'auditoria.jsonl')
    monkeypatch.setattr(supervisor_config, 'limites', lambda: {
        "em_vigor": supervisor_config.WorkspaceConfig(
            observador_auditoria=False, tentativas_autocorrecao=0).model_dump(),
        "config": {}, "gravaveis": list(supervisor_config.GRAVAVEIS),
        "protegidas": list(supervisor_config.PROTEGIDAS)})
