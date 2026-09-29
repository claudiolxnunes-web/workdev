import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers.handoffs import send_to_build
from app.routers import terminal
from app.routers.terminal import (
    CliModelSelection,
    STANDBY_COMMANDS,
    select_cli_agent_model,
)
from app.schemas.handoff import BuildRequest
from app.services import cli_agent_models


def test_ui_selection_is_persisted_and_dispatched_exactly_to_openrouter():
    """Cobre a cadeia usada pela UI: PUT -> estado persistido -> launcher."""
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ), patch(
        "app.routers.terminal.agent_snapshot.read_snapshot",
        return_value={"agents": [{"activity_state": "IDLE"}]},
    ):
        result = select_cli_agent_model(
            "qwen", CliModelSelection(model="x-ai/grok-4.7")
        )

        assert result["selected"] == "x-ai/grok-4.7"
        assert cli_agent_models.launcher(
            "qwen", STANDBY_COMMANDS["qwen"]
        ) == [
            "env",
            "QWEN_PROVIDER=openrouter",
            "QWEN_MODEL=x-ai/grok-4.7",
            "/opt/workdev/scripts/start_qwen_agent.sh",
        ]


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
        select_cli_agent_model("qwen", CliModelSelection(model="moonshotai/kimi-k2.7-code"))
        plan = SimpleNamespace(id="plan-1", backlog_id="task-1", status="approved")
        run = SimpleNamespace(
            id="run-1", plan_id=plan.id, backlog_id=plan.backlog_id,
            agent="qwen", routing_mode="manual", status="queued", model=None,
        )

        def persist_run(_db, _plan, _agent, **kwargs):
            run.model = kwargs["model"]
            return run, SimpleNamespace(id="event-1")

        with patch("app.routers.handoffs._get_plan", return_value=plan), \
             patch("app.routers.handoffs.allowed_models_for_agent", return_value=[
                 SimpleNamespace(provider_model_id="moonshotai/kimi-k2.7-code")
             ]), \
             patch("app.routers.handoffs.queue_build", side_effect=persist_run), \
             patch("app.routers.handoffs._sync_run"), \
             patch("app.routers.handoffs._run_out", side_effect=lambda _db, row: {"model": row.model}):
            result = send_to_build(
                plan.id, BuildRequest(agent="qwen", reviewer="codex"), Mock(), Mock()
            )

        assert result["model"] == "moonshotai/kimi-k2.7-code"
        # O start de uma run recebe run.model, não a seleção global posterior.
        cli_agent_models.choose("qwen", "x-ai/grok-4.7")
        assert cli_agent_models.launcher(
            "qwen", ["/opt/workdev/scripts/start_qwen_agent.sh"], run.model
        )[2] == "QWEN_MODEL=moonshotai/kimi-k2.7-code"


def test_explicit_run_model_is_not_replaced_by_global_selection():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ):
        cli_agent_models.choose("qwen", "x-ai/grok-4.7")
        plan = SimpleNamespace(id="plan-1", backlog_id="task-1", status="approved")
        run = SimpleNamespace(id="run-1", agent="qwen", routing_mode="manual",
                              status="queued", model="qwen/qwen3.5-397b-a17b")
        with patch("app.routers.handoffs._get_plan", return_value=plan), \
             patch("app.routers.handoffs.allowed_models_for_agent", return_value=[
                 SimpleNamespace(provider_model_id=run.model)
             ]), \
             patch("app.routers.handoffs.queue_build", return_value=(run, SimpleNamespace(id="event-1"))) as queued, \
             patch("app.routers.handoffs._sync_run"), \
             patch("app.routers.handoffs._run_out", return_value={"model": run.model}):
            send_to_build(plan.id, BuildRequest(agent="qwen", reviewer="codex", model=run.model), Mock(), Mock())
        assert queued.call_args.kwargs["model"] == run.model


def test_legacy_run_without_model_starts_with_historical_qwen_default():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ,
        {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")},
    ):
        cli_agent_models.choose("qwen", "x-ai/grok-4.7")
        with patch.object(terminal.agent_lifecycle, "run_lock", return_value=nullcontext()), \
             patch.object(terminal.agent_lifecycle, "agent_lock", return_value=nullcontext()), \
             patch.object(terminal.agent_lifecycle, "run_binding", return_value=None), \
             patch.object(terminal, "_start_agent_runtime") as started:
            terminal.start_agent_runtime("qwen", "prompt", model=None, run_id="old-run")
        assert started.call_args.args[3] == "qwen/qwen3.5-397b-a17b"


def test_qwen_launcher_passes_exact_model_to_cli(tmp_path):
    executable = tmp_path / "fake-qwen"
    executable.write_text('#!/usr/bin/env sh\nprintf "%s\\n" "$@"\n')
    executable.chmod(0o755)
    fake_env = tmp_path / "agent.env"
    fake_env.write_text("OPENROUTER_API_KEY=test-only\n")
    result = subprocess.run(
        ["/opt/workdev/scripts/start_qwen_agent.sh"],
        env={**os.environ, "WORKDEV_ENV_FILE": str(fake_env),
             "QWEN_EXECUTABLE": str(executable), "QWEN_PROVIDER": "openrouter",
             "QWEN_MODEL": "x-ai/grok-4.7"},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["--model", "x-ai/grok-4.7"]
