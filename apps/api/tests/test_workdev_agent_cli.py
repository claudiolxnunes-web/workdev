import importlib.util
import os
from pathlib import Path


SCRIPT = Path(__file__).parents[3] / "scripts" / "workdev_agent.py"


def load_cli():
    spec = importlib.util.spec_from_file_location("workdev_agent_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_file_defaults_to_protected_service_environment(monkeypatch):
    monkeypatch.delenv("WORKDEV_API_ENV_FILE", raising=False)

    cli = load_cli()

    assert cli.ENV_FILE == Path("/etc/workdev/workdev-api.env")


def test_env_file_honors_runtime_override(monkeypatch, tmp_path):
    env_file = tmp_path / "workdev-api.env"
    env_file.write_text("WORKDEV_API_KEY=chave-de-teste\n", encoding="utf-8")
    monkeypatch.setenv("WORKDEV_API_ENV_FILE", str(env_file))
    monkeypatch.delenv("WORKDEV_API_KEY", raising=False)

    cli = load_cli()

    assert cli.ENV_FILE == env_file
    assert cli.api_key() == "chave-de-teste"
