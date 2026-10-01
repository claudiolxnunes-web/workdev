import json
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.routers.handoffs import send_to_build
from app.routers import terminal
from app.routers.terminal import (
    CliModelSelection,
    STANDBY_COMMANDS,
    select_cli_agent_model,
)
from app.schemas.handoff import BuildRequest
from app.services import cli_agent_models


NEW_AGENTS = ("qwen", "grok", "deepseek")
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.mark.parametrize("agent, model, expected", [
    ("qwen", "qwen/qwen3-coder-next",
     ["env", "QWEN_PROVIDER=openrouter", "QWEN_MODEL=qwen/qwen3-coder-next",
      "/opt/workdev/scripts/start_qwen_agent.sh"]),
    ("grok", "x-ai/grok-build-0.1",
     ["env", "GROK_MODEL=x-ai/grok-build-0.1",
      "/opt/workdev/scripts/start_grok_agent.sh"]),
    ("deepseek", "deepseek/deepseek-v4-pro-0813",
     ["env", "DEEPSEEK_MODEL=deepseek/deepseek-v4-pro-0813",
      "/opt/workdev/scripts/start_deepseek_agent.sh"]),
])
def test_ui_selection_is_persisted_and_dispatched_exactly(agent, model, expected):
    """Cobre a cadeia usada pela UI: PUT -> estado persistido -> launcher."""
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ), patch(
        "app.routers.terminal.agent_snapshot.read_snapshot",
        return_value={"agents": [{"activity_state": "IDLE"}]},
    ):
        result = select_cli_agent_model(agent, CliModelSelection(model=model))

        assert result["selected"] == model
        assert cli_agent_models.launcher(agent, STANDBY_COMMANDS[agent]) == expected


def test_legacy_selection_without_model_uses_qwen_default():
    """Estado anterior ao seletor não possui model; Qwen 3.5 segue funcionando."""
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ):
        assert cli_agent_models.launcher(
            "qwen", STANDBY_COMMANDS["qwen"]
        ) == [
            "env",
            "QWEN_PROVIDER=openrouter",
            "QWEN_MODEL=qwen/qwen3.5-397b-a17b",
            "/opt/workdev/scripts/start_qwen_agent.sh",
        ]


def test_selected_model_is_fixed_on_new_run_and_reaches_runtime_launcher():
    """PUT da UI -> handoff -> modelo persistido -> despacho do runtime CLI."""
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ), patch(
        "app.routers.terminal.agent_snapshot.read_snapshot",
        return_value={"agents": [{"activity_state": "IDLE"}]},
    ):
        select_cli_agent_model(
            "deepseek", CliModelSelection(model="deepseek/deepseek-v4-pro-0813")
        )
        plan = SimpleNamespace(id="plan-1", backlog_id="task-1", status="approved")
        run = SimpleNamespace(
            id="run-1", plan_id=plan.id, backlog_id=plan.backlog_id,
            agent="deepseek", routing_mode="manual", status="queued", model=None,
        )

        def persist_run(_db, _plan, _agent, **kwargs):
            run.model = kwargs["model"]
            return run, SimpleNamespace(id="event-1")

        with patch("app.routers.handoffs._get_plan", return_value=plan), \
             patch("app.routers.handoffs.allowed_models_for_agent", return_value=[
                 SimpleNamespace(provider_model_id="deepseek/deepseek-v4-pro-0813")
             ]), \
             patch("app.routers.handoffs.queue_build", side_effect=persist_run), \
             patch("app.routers.handoffs._sync_run"), \
             patch("app.routers.handoffs._run_out", side_effect=lambda _db, row: {"model": row.model}):
            result = send_to_build(
                plan.id, BuildRequest(agent="deepseek", reviewer="claude"), Mock(), Mock()
            )

        assert result["model"] == "deepseek/deepseek-v4-pro-0813"
        # O start de uma run recebe run.model, não a seleção global posterior.
        cli_agent_models.choose("deepseek", "deepseek/deepseek-v4.1-flash")
        assert cli_agent_models.launcher(
            "deepseek", ["/opt/workdev/scripts/start_deepseek_agent.sh"], run.model
        )[1] == "DEEPSEEK_MODEL=deepseek/deepseek-v4-pro-0813"


def test_explicit_run_model_is_not_replaced_by_global_selection():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ):
        cli_agent_models.choose("grok", "x-ai/grok-build-0.1")
        plan = SimpleNamespace(id="plan-1", backlog_id="task-1", status="approved")
        run = SimpleNamespace(
            id="run-1", agent="grok", routing_mode="manual",
            status="queued", model="x-ai/grok-4.3"
        )
        with patch("app.routers.handoffs._get_plan", return_value=plan), \
             patch("app.routers.handoffs.allowed_models_for_agent", return_value=[
                 SimpleNamespace(provider_model_id=run.model)
             ]), \
             patch("app.routers.handoffs.queue_build", return_value=(run, SimpleNamespace(id="event-1"))) as queued, \
             patch("app.routers.handoffs._sync_run"), \
             patch("app.routers.handoffs._run_out", return_value={"model": run.model}):
            send_to_build(plan.id, BuildRequest(agent="grok", reviewer="kimi", model=run.model), Mock(), Mock())
        assert queued.call_args.kwargs["model"] == run.model


@pytest.mark.parametrize("model, agent, expected_model", [
    (None, "qwen", "qwen/qwen3.5-397b-a17b"),
    ("qwen/qwen3.5-397b-a17b", "qwen", "qwen/qwen3.5-397b-a17b"),
    ("x-ai/grok-4.7", "grok", "x-ai/grok-4.7"),
    ("deepseek/deepseek-v4-flash", "deepseek", "deepseek/deepseek-v4-flash"),
])
def test_legacy_openrouter_run_starts_on_agent_of_its_model(model, agent, expected_model):
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ):
        # Seleção global posterior não altera run antiga.
        cli_agent_models.choose("qwen", "qwen/qwen3-coder-next")
        with patch.object(terminal.agent_lifecycle, "run_lock", return_value=nullcontext()), \
             patch.object(terminal.agent_lifecycle, "agent_lock", return_value=nullcontext()), \
             patch.object(terminal.agent_lifecycle, "run_binding", return_value=None), \
             patch("app.services.run_pause.checked_work_unit", return_value=nullcontext()), \
             patch.object(terminal, "_start_agent_runtime") as started:
            terminal.start_agent_runtime("openrouter", "prompt", model=model, run_id="old-run")
        assert started.call_args.args[0] == agent
        assert started.call_args.args[3] == expected_model


def _fake_qwen(tmp_path):
    executable = tmp_path / "fake-qwen"
    executable.write_text('#!/usr/bin/env sh\nprintf "%s\\n" "$@"\nprintf "SETTINGS_PATH=%s\\n" "$QWEN_CODE_SYSTEM_SETTINGS_PATH"\n')
    executable.chmod(0o755)
    fake_env = tmp_path / "agent.env"
    fake_env.write_text("OPENROUTER_API_KEY=test-only\n")
    return executable, fake_env


@pytest.mark.parametrize("script, model_env, model", [
    ("start_qwen_agent.sh", "QWEN_MODEL", "qwen/qwen3-coder-next"),
    ("start_grok_agent.sh", "GROK_MODEL", "x-ai/grok-4.3"),
    ("start_deepseek_agent.sh", "DEEPSEEK_MODEL", "deepseek/deepseek-v4.1-flash"),
])
def test_openrouter_launchers_pass_exact_model_to_qwen_cli(tmp_path, script, model_env, model):
    """Grok e DeepSeek usam a CLI qwen pela OpenRouter, como o agente qwen."""
    executable, fake_env = _fake_qwen(tmp_path)
    env = {key: value for key, value in os.environ.items()
           if key not in {"QWEN_MODEL", "GROK_MODEL", "DEEPSEEK_MODEL", "QWEN_PROVIDER"}}
    result = subprocess.run(
        [str(SCRIPTS / script)],
        env={**env, "WORKDEV_ENV_FILE": str(fake_env),
             "QWEN_EXECUTABLE": str(executable), model_env: model},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:2] == ["--model", model]
    settings_path = lines[2].split("=", 1)[1]
    settings = json.loads(Path(settings_path).read_text())
    assert settings["model"]["name"] == model


@pytest.mark.parametrize("script, default", [
    ("start_grok_agent.sh", "x-ai/grok-4.7"),
    ("start_deepseek_agent.sh", "deepseek/deepseek-v4-flash"),
])
def test_launcher_defaults_match_selector_defaults(tmp_path, script, default):
    executable, fake_env = _fake_qwen(tmp_path)
    env = {key: value for key, value in os.environ.items()
           if key not in {"QWEN_MODEL", "GROK_MODEL", "DEEPSEEK_MODEL", "QWEN_PROVIDER"}}
    result = subprocess.run(
        [str(SCRIPTS / script)],
        env={**env, "WORKDEV_ENV_FILE": str(fake_env), "QWEN_EXECUTABLE": str(executable)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:2] == ["--model", default]
    agent = script.removeprefix("start_").removesuffix("_agent.sh")
    assert cli_agent_models.DEFAULTS[agent] == default
