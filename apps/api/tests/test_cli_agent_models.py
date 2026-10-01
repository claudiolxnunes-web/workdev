import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.services import cli_agent_models as models


NEW_AGENTS = ("qwen", "grok", "deepseek")


@pytest.fixture(autouse=True)
def isolated_selection_file(tmp_path, monkeypatch):
    # Nunca ler a seleção real de produção em /var/lib/agents-healthcheck.
    monkeypatch.setenv("WORKDEV_CLI_AGENT_MODELS_FILE", str(tmp_path / "models.json"))


def test_selection_is_persisted_and_launcher_uses_exact_model():
    with TemporaryDirectory() as directory, patch.dict(
        os.environ, {"WORKDEV_CLI_AGENT_MODELS_FILE": str(Path(directory) / "models.json")}
    ):
        for agent in NEW_AGENTS:
            default = models.selected(agent)
            assert default == models.DEFAULTS[agent]

        models.choose("qwen", "qwen/qwen3-coder-next")
        assert models.describe("qwen")["selected"] == "qwen/qwen3-coder-next"
        assert models.describe("qwen")["active"] is None

        models.choose("grok", "x-ai/grok-build-0.1")
        assert models.launcher("grok", ["/script"]) == [
            "env", "GROK_MODEL=x-ai/grok-build-0.1", "/script",
        ]

        models.record_active("deepseek", "deepseek/deepseek-v4-flash")
        models.choose("deepseek", "deepseek/deepseek-v4-pro-0813")
        assert models.describe("deepseek")["active"] == "deepseek/deepseek-v4-flash"


def test_new_agents_catalog_has_three_priced_models_and_expensive_flag():
    for agent in NEW_AGENTS:
        options = models.describe(agent)["options"]
        assert len(options) >= 3, agent
        assert all(row["input_cost_per_million"] is not None for row in options), agent
        assert all(row["output_cost_per_million"] is not None for row in options), agent
        assert all(row["expensive"] == (row["output_cost_per_million"] >= 10) for row in options), agent


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
    for agent in ("claude", "codex", "gemini", "kimi", "qwen", "grok", "deepseek"):
        options = models.describe(agent)["options"]
        assert all(row["input_cost_per_million"] is not None for row in options), agent
        assert all(row["output_cost_per_million"] is not None for row in options), agent


@pytest.mark.parametrize("agent, model, expected", [
    ("gemini", "gemini-2.5-flash", ["env", "GEMINI_MODEL=gemini-2.5-flash", "/script"]),
    ("claude", "claude-opus-5-5", ["/script", "--model", "claude-opus-5-5"]),
    ("codex", "gpt-5.6-terra", ["/script", "--model", "gpt-5.6-terra"]),
    ("qwen", "qwen/qwen3.5-397b-a17b",
     ["env", "QWEN_PROVIDER=openrouter", "QWEN_MODEL=qwen/qwen3.5-397b-a17b", "/script"]),
    ("grok", "x-ai/grok-4.3",
     ["env", "GROK_MODEL=x-ai/grok-4.3", "/script"]),
    ("deepseek", "deepseek/deepseek-v4.1-flash",
     ["env", "DEEPSEEK_MODEL=deepseek/deepseek-v4.1-flash", "/script"]),
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


def test_grok_has_premium_medium_and_cheap_tiers():
    options = models.describe("grok")["options"]
    assert [row["model"] for row in options] == [
        "x-ai/grok-4.7", "x-ai/grok-4.3", "x-ai/grok-build-0.1",
    ]
    assert models.DEFAULTS["grok"] == "x-ai/grok-4.7"
    outputs = [row["output_cost_per_million"] for row in options]
    assert outputs == sorted(outputs, reverse=True)


def test_openrouter_cli_agents_are_in_the_shared_qwen_catalog():
    import json
    catalog = json.loads((Path(__file__).resolve().parents[3]
                          / "scripts/qwen-agent-settings.json").read_text())
    ids = {row["id"] for row in catalog["modelProviders"]["openai"]}
    for agent in models.OPENROUTER_CLI_AGENTS:
        for model, _label in models.MODELS[agent]:
            assert model in ids, (agent, model)
