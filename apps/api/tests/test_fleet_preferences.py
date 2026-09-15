from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.config_service import ConfigService
from app.services.agent_router import _agent_for_model, resolve_execution_selection, AgentRoutingError
from app.schemas.handoff import BuildRequest
from tests.test_review_lifecycle import lifecycle_api, add_evidence
from app.services import review_cycle


@pytest.mark.parametrize("explicit", [False, True])
def test_build_uses_saved_default_unless_execution_overrides(tmp_path, monkeypatch, explicit):
    from app.routers import handoffs
    from app.services import config_service, agent_router
    monkeypatch.setenv("WORKDEV_USER_CONFIG_FILE", str(tmp_path / "user.json"))
    config = ConfigService()
    assert config.update_user_config({"agents": {"executor": {"provider": "openrouter", "model": "vendor/new"}}})
    monkeypatch.setattr(config_service, "config_service", config)
    monkeypatch.setattr(agent_router, "configured_execution_models", lambda _: [
        {"provider": "openrouter", "model": "vendor/new", "agent": "qwen", "label": "New", "review_capable": True}])
    plan = SimpleNamespace(id="plan", backlog_id="task", status="approved")
    monkeypatch.setattr(handoffs, "_get_plan", lambda *_: plan)
    monkeypatch.setattr(handoffs, "allowed_models_for_agent", lambda *_: [])
    queued = Mock(return_value=(SimpleNamespace(routing_mode="manual"), None))
    monkeypatch.setattr(handoffs, "queue_build", queued)
    monkeypatch.setattr(handoffs, "_sync_run", lambda *_: None)
    monkeypatch.setattr(handoffs, "_run_out", lambda *_: {})
    payload = BuildRequest(use_default_executor=True, reviewer="claude",
                           agent="codex" if explicit else None, model="explicit-model" if explicit else None)
    handoffs.send_to_build("plan", payload, Mock(), Mock())
    assert queued.call_args.args[2] == ("codex" if explicit else "qwen")
    assert queued.call_args.kwargs["model"] == ("explicit-model" if explicit else "vendor/new")


def test_settings_endpoint_validates_then_persists_canonical_selection(tmp_path, monkeypatch):
    import asyncio
    from app.api.endpoints import settings
    monkeypatch.setenv("WORKDEV_USER_CONFIG_FILE", str(tmp_path / "user.json"))
    monkeypatch.setattr(settings, "config_service", ConfigService())
    monkeypatch.setattr(settings, "resolve_execution_selection", lambda *_: {
        "provider": "ollama", "model": "installed", "runtime_id": "local-code", "agent": "local-code"})
    result = asyncio.run(settings.update_settings({"agents": {"executor": {"provider": "ollama", "model": "installed"}}}, Mock()))
    assert result["agents"]["executor"] == ConfigService().get_setting("agents.executor")
    assert "agent" not in result["agents"]["executor"]


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
    row.agent_slug = "qwen"
    assert _agent_for_model(row) == "qwen"


def test_resolve_uses_active_bound_catalog_and_rejects_removed(monkeypatch):
    from app.services import agent_router
    monkeypatch.setattr(agent_router, "configured_execution_models", lambda _: [
        {"provider": "openrouter", "model": "vendor/new", "agent": "qwen", "label": "New", "review_capable": True},
    ])
    selection = {"provider": "openrouter", "model": "vendor/new", "agent": "attacker"}
    assert resolve_execution_selection(Mock(), selection)["agent"] == "qwen"
    with pytest.raises(AgentRoutingError):
        resolve_execution_selection(Mock(), {**selection, "model": "removed"})


def test_request_requires_explicit_decline_and_rejects_self_review():
    assert BuildRequest(use_default_executor=True, review_requested=False).reviewer is None
    with pytest.raises(ValueError):
        BuildRequest(use_default_executor=True)
    with pytest.raises(ValueError):
        BuildRequest(agent="codex", reviewer="codex", review_requested=True)
    with pytest.raises(ValueError):
        BuildRequest(agent="codex", reviewer="claude", review_requested=False)


@pytest.mark.parametrize("sensitive,requested,expected", [(False, False, "completed"), (False, True, "review"), (True, False, "review")])
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
        if sensitive:
            assert db.query(Cycle).one().decision == "REVISAR"
    if sensitive:
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
