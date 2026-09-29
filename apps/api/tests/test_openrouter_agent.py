import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.routers.terminal import (
    CliModelSelection,
    STANDBY_COMMANDS,
    select_cli_agent_model,
)
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
