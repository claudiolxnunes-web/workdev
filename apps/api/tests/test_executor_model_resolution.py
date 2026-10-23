"""Etapa 2A: o modelo do executor CLI vem da aba Agentes e fica gravado na run."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.routers import handoffs, terminal
from app.schemas.handoff import BuildRequest
from app.services import cli_agent_models as models
from app.services.handoff import CLI_AGENTS, HandoffError, queue_build


def _db():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _plan():
    return SimpleNamespace(id="plan-1", backlog_id="task-1", status="approved")


# --- validate_selected -------------------------------------------------------

def test_validate_selected_sem_selecao_devolve_default_nao_explicito():
    assert models.validate_selected("claude") == (models.DEFAULTS["claude"], False)


def test_validate_selected_com_selecao_devolve_modelo_explicito():
    models.choose("codex", "gpt-5.6-luna")
    assert models.validate_selected("codex") == ("gpt-5.6-luna", True)


def test_validate_selected_rejeita_selecao_persistida_invalida():
    models.choose("claude", "claude-sonnet-5")
    path = models._path()
    path.write_text(path.read_text().replace("claude-sonnet-5", "claude-inexistente"))
    with pytest.raises(ValueError, match="claude-inexistente"):
        models.validate_selected("claude")
    # selected() mantém o fallback antigo; só a resolução do envio é estrita.
    assert models.selected("claude") == models.DEFAULTS["claude"]


def test_validate_selected_agente_sem_catalogo_levanta_erro():
    with pytest.raises(ValueError):
        models.validate_selected("gpu-runpod")


# --- queue_build -------------------------------------------------------------

@pytest.mark.parametrize("agent", sorted(CLI_AGENTS))
def test_queue_build_grava_modelo_selecionado_para_todo_agente_cli(agent):
    chosen = models.MODELS[agent][-1][0]
    models.choose(agent, chosen)
    run, event = queue_build(_db(), _plan(), agent, reviewer="gemini" if agent != "gemini" else "codex")
    assert run.model == chosen
    assert event.payload["model"] == chosen


def test_queue_build_sem_selecao_usa_default():
    run, _ = queue_build(_db(), _plan(), "claude", reviewer="codex")
    assert run.model == models.DEFAULTS["claude"]


def test_queue_build_preserva_modelo_explicito():
    models.choose("claude", "claude-haiku-4-5")
    run, _ = queue_build(_db(), _plan(), "claude", reviewer="codex", model="claude-sonnet-5")
    assert run.model == "claude-sonnet-5"


def test_queue_build_selecao_invalida_bloqueia_sem_criar_run():
    models.choose("claude", "claude-sonnet-5")
    path = models._path()
    path.write_text(path.read_text().replace("claude-sonnet-5", "claude-inexistente"))
    db = _db()
    with pytest.raises(HandoffError, match="aba Agentes"):
        queue_build(db, _plan(), "claude", reviewer="codex")
    db.add.assert_not_called()


def test_queue_build_nao_resolve_no_modo_auto_nem_para_runtime_sem_catalogo():
    models.choose("claude", "claude-haiku-4-5")
    auto, _ = queue_build(_db(), _plan(), "claude", reviewer="codex", routing_mode="auto",
                          complexity="low", complexity_score=10)
    runtime, _ = queue_build(_db(), _plan(), "gpu-runpod", reviewer="claude")
    assert auto.model is None and runtime.model is None


def test_revisor_e_observer_nao_recebem_modelo_do_executor():
    models.choose("claude", "claude-haiku-4-5")
    models.choose("codex", "gpt-5.6-luna")
    run, _ = queue_build(_db(), _plan(), "claude", reviewer="codex")
    assert run.model == "claude-haiku-4-5" and run.reviewer_agent == "codex"


# --- POST /plans/{id}/build --------------------------------------------------

def _send(agent="claude", **fields):
    payload = BuildRequest(agent=agent, reviewer="codex", routing_mode="manual", **fields)
    captured = {}

    def fake_queue(_db, _plan, _agent, **kwargs):
        captured.update(kwargs)
        run = SimpleNamespace(id="run-1", model=kwargs["model"], agent=_agent, routing_mode="manual")
        return run, SimpleNamespace(id="event-1")

    with patch.object(handoffs, "_get_plan", return_value=_plan()), \
         patch.object(handoffs, "allowed_models_for_agent", return_value=[]), \
         patch.object(handoffs, "queue_build", side_effect=fake_queue), \
         patch.object(handoffs, "_sync_run"), \
         patch.object(handoffs, "_run_out", side_effect=lambda _db, row: {"model": row.model}):
        result = handoffs.send_to_build("plan-1", payload, Mock(), Mock())
    return result, captured


def _session(exists):
    return patch("app.services.agent_operability.resolve",
                 return_value=SimpleNamespace(session_exists=exists))


def test_envio_so_com_agente_usa_modelo_configurado_na_aba_agentes():
    models.choose("claude", "claude-haiku-4-5")
    result, captured = _send("claude")
    assert result["model"] == captured["model"] == "claude-haiku-4-5"


def test_envio_com_modelo_explicito_e_preservado():
    models.choose("claude", "claude-haiku-4-5")
    result, _ = _send("claude", model="claude-sonnet-5")
    assert result["model"] == "claude-sonnet-5"


def test_sessao_viva_com_outro_modelo_bloqueia_com_409_claro():
    models.record_active("claude", "claude-opus-5")
    models.choose("claude", "claude-haiku-4-5")
    with _session(True), pytest.raises(HTTPException) as error:
        _send("claude")
    assert error.value.status_code == 409
    detail = error.value.detail
    assert detail["code"] == "model_requires_new_session"
    assert detail["details"] == {"agent": "claude", "selected": "claude-haiku-4-5",
                                 "active": "claude-opus-5"}
    assert "Reinicie" in detail["message"]


def test_bloqueio_vale_tambem_para_agente_openrouter():
    models.record_active("qwen", "qwen/qwen3-coder-next")
    models.choose("qwen", "qwen/qwen3-coder-flash")
    with _session(True), pytest.raises(HTTPException) as error:
        _send("qwen")
    assert error.value.detail["code"] == "model_requires_new_session"


def test_sessao_encerrada_ou_modelo_igual_nao_bloqueia():
    models.record_active("claude", "claude-opus-5")
    models.choose("claude", "claude-haiku-4-5")
    with _session(False):
        assert _send("claude")[0]["model"] == "claude-haiku-4-5"
    models.record_active("claude", "claude-haiku-4-5")
    with _session(True):
        assert _send("claude")[0]["model"] == "claude-haiku-4-5"


def test_modelo_explicito_ignora_o_bloqueio_de_sessao():
    models.record_active("claude", "claude-opus-5")
    with _session(True):
        assert _send("claude", model="claude-sonnet-5")[0]["model"] == "claude-sonnet-5"


def test_selecao_persistida_invalida_devolve_409_descritivo():
    models.choose("claude", "claude-sonnet-5")
    path = models._path()
    path.write_text(path.read_text().replace("claude-sonnet-5", "claude-inexistente"))
    with pytest.raises(HTTPException) as error:
        _send("claude")
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "invalid_model_selection"


# --- run.model -> launcher ---------------------------------------------------

def test_start_run_entrega_run_model_ao_runtime():
    run = SimpleNamespace(id="run-1", status="queued", agent="claude", model="claude-haiku-4-5")
    background = Mock()
    with patch.object(handoffs, "_get_run", return_value=run), \
         patch.object(handoffs, "build_context", return_value={"prompt": "p"}), \
         patch("app.services.run_pause.assert_run_can_continue"), \
         patch("app.services.agent_workspace.audit"):
        handoffs.start_workspace_run("run-1", background, Mock())
    args = background.add_task.call_args.args
    assert args[2:4] == ("claude", "claude-haiku-4-5")


@pytest.mark.parametrize("agent, model, expected", [
    ("claude", "claude-haiku-4-5", ["--model", "claude-haiku-4-5"]),
    ("codex", "gpt-5.6-luna", ["--model", "gpt-5.6-luna"]),
    ("kimi", "moonshotai/kimi-k2.6", ["KIMI_MODEL=moonshotai/kimi-k2.6"]),
    ("qwen", "qwen/qwen3-coder-next", ["QWEN_MODEL=qwen/qwen3-coder-next"]),
])
def test_runtime_injeta_o_modelo_da_run_no_launcher(agent, model, expected):
    models.choose(agent, models.DEFAULTS[agent])  # seleção global diferente da run
    seen = {}

    def fake_start(_agent, _session, launcher):
        seen["launcher"] = launcher
        return {"started": True}

    with patch.object(terminal.agent_lifecycle, "start", side_effect=fake_start), \
         patch.object(terminal, "_current_process", return_value="node"), \
         patch.object(terminal, "_send_text"):
        terminal.start_agent_runtime(agent, "prompt", model=model)
    assert all(item in seen["launcher"] for item in expected)


def test_agente_nao_cli_continua_sem_modelo_no_launcher():
    assert models.launcher("gpu-runpod", ["/script"]) == ["/script"]
