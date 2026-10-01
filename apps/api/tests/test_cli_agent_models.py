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
        assert models.selected("openrouter") == "qwen/qwen3.5-397b-a17b"
        models.choose("openrouter", "x-ai/grok-4.7")
        assert models.describe("openrouter")["selected"] == "x-ai/grok-4.7"
        assert models.describe("openrouter")["active"] is None
        assert models.launcher("openrouter", ["/opt/workdev/scripts/start_openrouter_agent.sh"]) == [
            "env", "QWEN_PROVIDER=openrouter", "QWEN_MODEL=x-ai/grok-4.7",
            "/opt/workdev/scripts/start_openrouter_agent.sh",
        ]
        models.record_active("openrouter", "x-ai/grok-4.7")
        assert models.describe("openrouter")["active"] == "x-ai/grok-4.7"
        models.choose("openrouter", "deepseek/deepseek-v4-flash")
        assert models.describe("openrouter")["active"] == "x-ai/grok-4.7"


def test_openrouter_catalog_has_three_priced_models_and_expensive_flag():
    options = models.describe("openrouter")["options"]
    assert [row["model"] for row in options] == [
        "qwen/qwen3.5-397b-a17b",
        "deepseek/deepseek-v4-flash",
        "x-ai/grok-4.7",
    ]
    assert all(row["input_cost_per_million"] is not None for row in options)
    assert all(row["output_cost_per_million"] is not None for row in options)
    assert all(row["expensive"] == (row["output_cost_per_million"] >= 10) for row in options)


def test_kimi_agent_has_all_models_and_pricing():
    options = models.describe("kimi")["options"]
    assert [row["model"] for row in options] == [
        "moonshotai/kimi-k3",
        "moonshotai/kimi-k3:batch",
        "moonshotai/kimi-k2.7-code",
        "moonshotai/kimi-k2.6",
        "moonshotai/kimi-k2.5",
        "moonshotai/kimi-k2-thinking",
        "moonshotai/kimi-k2-0905",
        "moonshotai/kimi-k2",
    ]
    assert all(row["input_cost_per_million"] is not None for row in options)
    assert all(row["output_cost_per_million"] is not None for row in options)
    assert models.launcher("kimi", ["/script"], "moonshotai/kimi-k2.7-code") == [
        "env", "KIMI_PROVIDER=openrouter", "KIMI_MODEL=moonshotai/kimi-k2.7-code", "/script",
    ]


def test_all_agents_have_priced_models():
    for agent in ("claude", "codex", "gemini", "kimi", "openrouter"):
        options = models.describe(agent)["options"]
        assert all(row["input_cost_per_million"] is not None for row in options), agent
        assert all(row["output_cost_per_million"] is not None for row in options), agent


@pytest.mark.parametrize("agent, model, expected", [
    ("gemini", "gemini-2.5-flash", ["env", "GEMINI_MODEL=gemini-2.5-flash", "/script"]),
    ("claude", "claude-opus-5-5", ["/script", "--model", "claude-opus-5-5"]),
    ("codex", "gpt-5.6-terra", ["/script", "--model", "gpt-5.6-terra"]),
    ("openrouter", "deepseek/deepseek-v4-flash",
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
