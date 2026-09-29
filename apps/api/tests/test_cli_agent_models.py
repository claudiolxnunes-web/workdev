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
        assert models.selected("qwen") == "qwen/qwen3.5-397b-a17b"
        models.choose("qwen", "moonshotai/kimi-k2.7-code")
        assert models.describe("qwen")["selected"] == "moonshotai/kimi-k2.7-code"
        assert models.describe("qwen")["active"] is None
        assert models.launcher("qwen", ["/opt/workdev/scripts/start_qwen_agent.sh"]) == [
            "env", "QWEN_PROVIDER=openrouter", "QWEN_MODEL=moonshotai/kimi-k2.7-code",
            "/opt/workdev/scripts/start_qwen_agent.sh",
        ]
        models.record_active("qwen", "moonshotai/kimi-k2.7-code")
        assert models.describe("qwen")["active"] == "moonshotai/kimi-k2.7-code"
        models.choose("qwen", "x-ai/grok-4.7")
        assert models.describe("qwen")["active"] == "moonshotai/kimi-k2.7-code"


def test_openrouter_catalog_has_five_priced_models_and_expensive_flag():
    options = models.describe("qwen")["options"]
    assert [row["model"] for row in options] == [
        "qwen/qwen3.5-397b-a17b",
        "deepseek/deepseek-v4-flash",
        "moonshotai/kimi-k2.7-code",
        "moonshotai/kimi-k2.6",
        "x-ai/grok-4.7",
    ]
    assert all(row["input_cost_per_million"] is not None for row in options)
    assert all(row["output_cost_per_million"] is not None for row in options)
    assert all(row["expensive"] == (row["output_cost_per_million"] >= 10) for row in options)


def test_kimi_agent_is_exclusive_to_kimi_3():
    assert models.describe("kimi")["options"] == [{
        "model": "moonshotai/kimi-k3", "label": "Kimi K3",
        "input_cost_per_million": None, "output_cost_per_million": None,
        "expensive": False,
    }]
    with pytest.raises(ValueError):
        models.choose("kimi", "moonshotai/kimi-k2.7-code")


@pytest.mark.parametrize("agent, model, expected", [
    ("gemini", "gemini-2.5-flash", ["env", "GEMINI_MODEL=gemini-2.5-flash", "/script"]),
    ("claude", "claude-opus-5-5", ["/script", "--model", "claude-opus-5-5"]),
    ("codex", "gpt-5.6-terra", ["/script", "--model", "gpt-5.6-terra"]),
    ("qwen", "deepseek/deepseek-v4-flash",
     ["env", "QWEN_PROVIDER=openrouter", "QWEN_MODEL=deepseek/deepseek-v4-flash", "/script"]),
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
