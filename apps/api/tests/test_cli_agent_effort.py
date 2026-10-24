"""Seletor de esforço por agente: só onde a CLI tem mecanismo comprovado."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.terminal import CliEffortSelection, select_cli_agent_effort
from app.services import cli_agent_models as models

SNAPSHOT = {"agents": [{"activity_state": "IDLE"}]}


def test_sem_escolha_nao_injeta_esforco_e_a_cli_usa_o_padrao():
    assert models.describe("claude")["effort"] is None
    assert models.launcher("claude", ["/s"], "claude-opus-5") == ["/s", "--model", "claude-opus-5"]


@pytest.mark.parametrize("agent, model, effort, esperado", [
    ("claude", "claude-opus-5", "xhigh", ["/s", "--model", "claude-opus-5", "--effort", "xhigh"]),
    ("codex", "gpt-5.6-sol", "high",
     ["/s", "--model", "gpt-5.6-sol", "-c", "model_reasoning_effort=high"]),
    ("kimi", "moonshotai/kimi-k3", "low",
     ["env", "KIMI_PROVIDER=openrouter", "KIMI_MODEL=moonshotai/kimi-k3",
      "KIMI_MODEL_THINKING_EFFORT=low", "/s"]),
])
def test_esforco_salvo_vai_para_o_launcher_de_cada_cli(agent, model, effort, esperado):
    models.choose_effort(agent, effort)
    assert models.describe(agent)["effort"] == effort
    assert models.launcher(agent, ["/s"], model) == esperado


def test_esforco_explicito_no_launcher_vence_o_salvo_e_limpar_volta_ao_padrao():
    models.choose_effort("claude", "low")
    assert models.launcher("claude", ["/s"], "claude-opus-5", "max")[-2:] == ["--effort", "max"]
    models.choose_effort("claude", None)
    assert models.selected_effort("claude") is None


@pytest.mark.parametrize("agent", ["gemini", "qwen", "grok", "deepseek"])
def test_agente_sem_mecanismo_nao_oferece_esforco(agent):
    assert models.describe(agent)["efforts"] == []
    with pytest.raises(ValueError):
        models.choose_effort(agent, "high")


def test_esforco_invalido_e_recusado_e_nao_altera_o_salvo():
    models.choose_effort("codex", "medium")
    with pytest.raises(ValueError):
        models.choose_effort("codex", "max")
    assert models.selected_effort("codex") == "medium"


def test_esforco_salvo_obsoleto_vira_padrao_em_vez_de_quebrar():
    models.choose_effort("kimi", "high")
    path = models._path()
    path.write_text(path.read_text().replace('"high"', '"inexistente"'))
    assert models.selected_effort("kimi") is None
    assert models.launcher("kimi", ["/s"], "moonshotai/kimi-k3")[-1] == "/s"


def test_endpoint_salva_esforco_e_nao_afeta_o_modelo_selecionado():
    models.choose("claude", "claude-haiku-4-5")
    with patch("app.routers.terminal.agent_snapshot.read_snapshot", return_value=SNAPSHOT):
        result = select_cli_agent_effort("claude", CliEffortSelection(effort="high"))
    assert result["effort"] == "high" and result["selected"] == "claude-haiku-4-5"
    assert result["efforts"] == ["low", "medium", "high", "xhigh", "max"]


def test_endpoint_recusa_agente_sem_seletor_valor_invalido_e_agente_ocupado():
    with patch("app.routers.terminal.agent_snapshot.read_snapshot", return_value=SNAPSHOT):
        with pytest.raises(HTTPException) as sem:
            select_cli_agent_effort("gemini", CliEffortSelection(effort="high"))
        with pytest.raises(HTTPException) as invalido:
            select_cli_agent_effort("codex", CliEffortSelection(effort="max"))
    busy = {"agents": [{"activity_state": "BUSY"}]}
    with patch("app.routers.terminal.agent_snapshot.read_snapshot", return_value=busy), \
         pytest.raises(HTTPException) as ocupado:
        select_cli_agent_effort("codex", CliEffortSelection(effort="low"))
    assert (sem.value.status_code, invalido.value.status_code, ocupado.value.status_code) == (404, 422, 409)
