"""Autonomia do supervisor sobre a configuração: allowlist, validação e freio.

O teste que importa aqui é o do risco: um valor inválido ou um caminho fora
da allowlist NÃO podem chegar ao disco, e a pausa tem que valer antes de
aplicar qualquer diff.
"""
import json

import pytest

from app.services import supervisor_config
from app.services.config_service import config_service


@pytest.fixture(autouse=True)
def _isola_config(tmp_path, monkeypatch):
    """Nada toca a configuração real nem a auditoria de produção."""
    monkeypatch.setattr(config_service, 'runtime_config_path', tmp_path / 'runtime.json')
    monkeypatch.setattr(config_service, 'user_config_path', tmp_path / 'user.json')
    monkeypatch.setattr(config_service, 'runtime_config', {})
    monkeypatch.setattr(supervisor_config, '_caminho_auditoria',
                        lambda: tmp_path / 'auditoria.jsonl')
    yield


def test_muda_dentro_da_allowlist_e_fica_em_vigor():
    resultado = supervisor_config.mudar('workspace.tentativas_autocorrecao', 2,
                                        chat_session_id='s1', motivo='a fatia falhou duas vezes')
    assert resultado['depois'] == 2
    assert config_service.get_setting('workspace.tentativas_autocorrecao') == 2


def test_grava_somente_o_campo_alterado():
    """O resto da seção continua vindo do user.json do operador."""
    config_service.user_config_path.parent.mkdir(parents=True, exist_ok=True)
    config_service.user_config_path.write_text(
        json.dumps({'agents': {'adaptive_supervision': {'enabled': True}}}), encoding='utf-8')
    supervisor_config.mudar('workspace.max_tokens_fatia', 2000)
    runtime = json.loads(config_service.runtime_config_path.read_text(encoding='utf-8'))
    assert runtime == {'workspace': {'max_tokens_fatia': 2000}}


def test_fora_da_allowlist_e_recusado():
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.mudar('database.host', 'outro-host')
    assert erro.value.codigo == 'fora_da_allowlist'
    assert not config_service.runtime_config_path.exists()


def test_chave_protegida_e_recusada():
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.mudar('agents.adaptive_supervision.max_cost_usd', 1.0)
    assert erro.value.codigo == 'chave_protegida'


def test_chave_de_credencial_e_recusada():
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.mudar('workspace.api_key', 'x')
    assert erro.value.codigo == 'chave_sensivel'


def test_valor_invalido_nao_chega_ao_disco():
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.mudar('workspace.tentativas_autocorrecao', 99)
    assert erro.value.codigo == 'valor_invalido'
    assert not config_service.runtime_config_path.exists()


def test_campo_desconhecido_e_recusado():
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.mudar('workspace.tentativas_autocorrecão', 1)
    assert erro.value.codigo == 'campo_desconhecido'


def test_auditoria_registra_o_antes_e_o_depois():
    supervisor_config.mudar('workspace.teto_falhas', 3, chat_session_id='s1', motivo='teste')
    registro = supervisor_config.auditoria()
    assert registro[-1]['acao'] == 'mudar_configuracao'
    assert registro[-1]['caminho'] == 'workspace.teto_falhas'
    assert registro[-1]['depois'] == 3
    assert registro[-1]['motivo'] == 'teste'


def test_pausar_e_retomar_a_sessao(monkeypatch):
    gravados = {}

    class Meta(dict):
        pass

    meta = {'id': 'ws-1', 'status': 'ativa'}

    def _ativa():
        return meta

    def _gravar(novo):
        gravados.update(novo)
        meta.update(novo)

    monkeypatch.setattr('app.services.workspace_sessao.ativa', _ativa)
    monkeypatch.setattr('app.services.workspace_sessao._gravar_meta', _gravar)

    supervisor_config.pausar_sessao('diff grande demais', chat_session_id='s1')
    assert gravados['pausada']['motivo'] == 'diff grande demais'

    supervisor_config.retomar_sessao(chat_session_id='s1', motivo='corrigido')
    assert gravados['pausada'] is None


def test_pausar_sem_sessao_ativa_e_recusado(monkeypatch):
    monkeypatch.setattr('app.services.workspace_sessao.ativa', lambda: None)
    with pytest.raises(supervisor_config.SupervisorConfigErro) as erro:
        supervisor_config.pausar_sessao('motivo')
    assert erro.value.codigo == 'sem_sessao'


def test_tool_do_chat_responde_com_erro_estruturado():
    from app.routers.ai import _tool_supervisor_config
    saida = json.loads(_tool_supervisor_config('mudar_configuracao',
                                              {'caminho': 'database.host', 'valor': 'x'}))
    assert saida['executado'] is False
    assert saida['code'] == 'fora_da_allowlist'


def test_tool_do_chat_le_a_configuracao():
    from app.routers.ai import _tool_supervisor_config
    saida = json.loads(_tool_supervisor_config('ler_configuracoes', {}))
    assert 'limites' in saida
    assert 'gravaveis' in saida['limites']
