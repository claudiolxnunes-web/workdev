import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.services import cli_agent_models as models


def test_selection_is_persisted_and_launcher_uses_exact_model():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ, {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")}
    ):
        assert models.selected("kimi") == "moonshotai/kimi-k3"
        models.choose("kimi", "moonshotai/kimi-k2.7-code")
        assert models.describe("kimi")["selected"] == "moonshotai/kimi-k2.7-code"
        assert models.describe("kimi")["active"] is None
        assert models.launcher("kimi", ["/opt/workdev/scripts/start_kimi_agent.sh"]) == [
            "env", "KIMI_PROVIDER=openrouter", "KIMI_MODEL=moonshotai/kimi-k2.7-code",
            "/opt/workdev/scripts/start_kimi_agent.sh",
        ]
        models.record_active("kimi", "moonshotai/kimi-k2.7-code")
        assert models.describe("kimi")["active"] == "moonshotai/kimi-k2.7-code"
        models.choose("kimi", "moonshotai/kimi-k3")
        assert models.describe("kimi")["active"] == "moonshotai/kimi-k2.7-code"


@pytest.mark.parametrize("agent, model, expected", [
    ("gemini", "gemini-2.5-flash", ["env", "GEMINI_MODEL=gemini-2.5-flash", "/script"]),
    ("claude", "claude-opus-5-5", ["/script", "--model", "claude-opus-5-5"]),
    ("codex", "gpt-5.6-terra", ["/script", "--model", "gpt-5.6-terra"]),
])
def test_launchers_use_requested_model(agent, model, expected):
    assert models.launcher(agent, ["/script"], model) == expected


def test_unlisted_model_is_rejected_without_writing():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ, {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")}
    ):
        with pytest.raises(ValueError):
            models.choose("codex", "claude-opus-5")
        assert not (Path(directory) / "models.json").exists()
