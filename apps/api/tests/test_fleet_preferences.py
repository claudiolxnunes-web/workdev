from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.config_service import ConfigService
from app.services.agent_router import _agent_for_model, resolve_execution_selection, AgentRoutingError
from app.schemas.handoff import BuildRequest
from tests.test_review_lifecycle import lifecycle_api, add_evidence
from app.services import review_cycle


def test_build_ignores_old_saved_default_and_uses_the_chosen_executor(tmp_path, monkeypatch):
    """Não existe executor padrão: um valor antigo salvo (até "ollama") não interfere."""
    from app.routers import handoffs
    from app.services import config_service
    monkeypatch.setenv("WORKDEV_USER_CONFIG_FILE", str(tmp_path / "user.json"))
    config = ConfigService()
    assert config.update_user_config({"agents": {"executor": {"provider": "ollama", "model": "workdev-qwen", "runtime_id": "local-code"}}})
    monkeypatch.setattr(config_service, "config_service", config)
    plan = SimpleNamespace(id="plan", backlog_id="task", status="approved")
    monkeypatch.setattr(handoffs, "_get_plan", lambda *_: plan)
    monkeypatch.setattr(handoffs, "allowed_models_for_agent", lambda *_: [])
    queued = Mock(return_value=(SimpleNamespace(routing_mode="manual"), None))
    monkeypatch.setattr(handoffs, "queue_build", queued)
    monkeypatch.setattr(handoffs, "_sync_run", lambda *_: None)
    monkeypatch.setattr(handoffs, "_run_out", lambda *_: {})
    payload = BuildRequest(reviewer="claude", agent="codex", model="explicit-model")
    handoffs.send_to_build("plan", payload, Mock(), Mock())
    assert queued.call_args.args[2] == "codex"
    assert queued.call_args.kwargs["model"] == "explicit-model"


def test_manual_build_without_executor_is_refused():
    with pytest.raises(ValueError, match="Escolha o executor"):
        BuildRequest(reviewer="claude")
    # Cliente antigo que ainda mande use_default_executor não ganha padrão nenhum.
    with pytest.raises(ValueError, match="Escolha o executor"):
        BuildRequest.model_validate({"use_default_executor": True, "reviewer": "claude"})


def test_settings_no_longer_persist_an_executor_and_keep_other_settings(tmp_path, monkeypatch):
    import asyncio
    from app.api.endpoints import settings
    monkeypatch.setenv("WORKDEV_USER_CONFIG_FILE", str(tmp_path / "user.json"))
    assert ConfigService().update_user_config({"agents": {"executor": {"provider": "ollama", "model": "workdev-qwen", "runtime_id": "local-code"}}})
    monkeypatch.setattr(settings, "config_service", ConfigService())
    result = asyncio.run(settings.update_settings({"app": {"name": "Mantido"}, "agents": {
        "executor": {"provider": "openrouter", "model": "qwen/qwen3.5-397b-a17b"},
        "adaptive_supervision": {"enabled": True}}}, Mock()))
    saved = ConfigService()
    # O valor antigo continua legível sem erro, mas nada novo é gravado nele.
    assert saved.get_setting("agents.executor") == {"provider": "ollama", "model": "workdev-qwen", "runtime_id": "local-code"}
    assert saved.get_setting("agents.adaptive_supervision.enabled") is True
    assert saved.get_setting("app.name") == "Mantido"
    assert result["app"]["name"] == "Mantido"


def test_default_persists_across_instances_and_preserves_other_settings(tmp_path, monkeypatch):
    path = tmp_path / "user.json"
    monkeypatch.setenv("WORKDEV_USER_CONFIG_FILE", str(path))
    first, second = ConfigService(), ConfigService()
    assert first.update_user_config({"app": {"name": "Preserved"}, "agents": {"executor": {"provider": "ollama", "model": "real-model", "runtime_id": "local-code"}}})
    assert second.get_setting("agents.executor.model") == "real-model"
    assert second.update_user_config({"agents": {"executor": None}})
    assert first.get_setting("agents.executor") is None
    assert first.get_setting("app.name") == "Preserved"
    assert ConfigService().get_setting("app.name") == "Preserved"


def test_catalog_binding_replaces_model_name_overrides():
    row = SimpleNamespace(provider="openrouter", provider_model_id="moonshotai/kimi-k3", agent_slug=None)
    assert _agent_for_model(row) is None
    row.agent_slug = "openrouter"
    assert _agent_for_model(row) == "openrouter"


def test_resolve_uses_active_bound_catalog_and_rejects_removed(monkeypatch):
    from app.services import agent_router
    monkeypatch.setattr(agent_router, "configured_execution_models", lambda _: [
        {"provider": "openrouter", "model": "vendor/new", "agent": "openrouter", "label": "New", "review_capable": True},
    ])
    selection = {"provider": "openrouter", "model": "vendor/new", "agent": "attacker"}
    assert resolve_execution_selection(Mock(), selection)["agent"] == "openrouter"
    with pytest.raises(AgentRoutingError):
        resolve_execution_selection(Mock(), {**selection, "model": "removed"})


def test_request_requires_explicit_decline_and_rejects_self_review():
    assert BuildRequest(agent="codex", review_requested=False).reviewer is None
    with pytest.raises(ValueError):
        BuildRequest(agent="codex")
    with pytest.raises(ValueError):
        BuildRequest(agent="codex", reviewer="codex", review_requested=True)
    with pytest.raises(ValueError):
        BuildRequest(agent="codex", reviewer="claude", review_requested=False)


@pytest.mark.parametrize("sensitive,requested,expected", [
    (False, False, "completed"), (False, True, "review"),
    # O operador decide em qualquer risco: escopo sensível + "Não" conclui,
    # com a dispensa registrada; escopo sensível + "Sim" vai para revisão.
    (True, False, "completed"), (True, True, "review"),
])
def test_review_choice_rechecked_against_diff_and_persisted(lifecycle_api, monkeypatch, sensitive, requested, expected):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, "collect_diff_stats", lambda *_: (["app/auth.py"] if sensitive else ["readme.md"], "+changed"))
    with factory() as db:
        run = db.get(Run, run_id)
        run.reviewer_agent = "claude" if requested else None
        db.add(Event(run_id=run_id, event_type="build.review_preference", payload={"requested": requested, "actor": "user"}))
        add_evidence(db, Run, Event, run_id)
    response = client.patch(f"/api/handoffs/runs/{run_id}", json={"status": "review"})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(Run, run_id).status == expected
        assert db.query(Event).filter_by(event_type="build.review_preference").one().payload["requested"] is requested
        if sensitive and requested:
            assert db.query(Cycle).one().decision == "REVISAR"
        if sensitive and not requested:
            cycle = db.query(Cycle).one()
            assert cycle.decision == "NO_REVIEW_COMPLETE"
            assert cycle.sensitive
            assert "dispensada pelo operador" in cycle.justification
            assert "escopo sensível" in cycle.justification
    if sensitive and requested:
        refused = client.patch(f"/api/handoffs/runs/{run_id}", json={"status": "completed"})
        assert refused.status_code == 409


def test_decline_does_not_bypass_failed_gate(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, _ = lifecycle_api
    monkeypatch.setattr(review_cycle, "collect_diff_stats", lambda *_: (["readme.md"], "+changed"))
    with factory() as db:
        db.add(Event(run_id=run_id, event_type="build.review_preference", payload={"requested": False}))
        add_evidence(db, Run, Event, run_id, passed=False)
    assert client.patch(f"/api/handoffs/runs/{run_id}", json={"status": "review"}).status_code == 409
    with factory() as db:
        assert db.get(Run, run_id).status != "completed"
