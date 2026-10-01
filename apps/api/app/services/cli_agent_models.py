"""Persisted model selection for remote CLI agents.

The selected model applies to new processes only. The active model is recorded
separately so an existing tmux session is never mislabeled after a selection.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile


MODELS = {
    "gemini": (("gemini-3.5-flash", "Gemini 3.5 Flash"), ("gemini-2.5-flash", "Gemini 2.5 Flash")),
    "claude": (("claude-opus-5-5", "Claude Opus 5.5"), ("claude-opus-5", "Claude Opus 5"),
               ("claude-opus-4-8", "Claude Opus 4.8"), ("claude-sonnet-5", "Claude Sonnet 5"),
               ("claude-haiku-4-5", "Claude Haiku 4.5")),
    "codex": (("gpt-5.6-sol", "Codex Sol"), ("gpt-5.6-terra", "Codex Terra"),
              ("gpt-5.6-luna", "Codex Luna")),
    "kimi": (("moonshotai/kimi-k3", "Kimi K3"),
             ("moonshotai/kimi-k3:batch", "Kimi K3 (Batch)"),
             ("moonshotai/kimi-k2.7-code", "Kimi K2.7 Code"),
             ("moonshotai/kimi-k2.6", "Kimi K2.6"),
             ("moonshotai/kimi-k2.5", "Kimi K2.5"),
             ("moonshotai/kimi-k2-thinking", "Kimi K2 Thinking"),
             ("moonshotai/kimi-k2-0905", "Kimi K2 0905"),
             ("moonshotai/kimi-k2", "Kimi K2")),
    "openrouter": (("qwen/qwen3.5-397b-a17b", "Qwen Coder (Qwen 3.5)"),
             ("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash"),
             ("x-ai/grok-4.7", "Grok 4.7")),
}
DEFAULTS = {"gemini": "gemini-3.5-flash", "claude": "claude-opus-5",
            "codex": "gpt-5.6-sol", "kimi": "moonshotai/kimi-k3",
            "openrouter": "qwen/qwen3.5-397b-a17b"}

# USD por 1M tokens, conferidos no catálogo público da OpenRouter em
# 2026-10-01. O frontend deriva ``expensive`` do threshold aprovado de output.
PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-5.6-sol": (2.00, 10.00),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna": (0.20, 1.20),
    "qwen/qwen3.5-397b-a17b": (0.39, 2.34),
    "deepseek/deepseek-v4-flash": (0.0679, 0.168),
    "moonshotai/kimi-k3": (0.677, 10.00),
    "moonshotai/kimi-k3:batch": (2.28, 11.40),
    "moonshotai/kimi-k2.7-code": (0.6712, 3.35),
    "moonshotai/kimi-k2.6": (0.65, 3.41),
    "moonshotai/kimi-k2.5": (0.45, 2.25),
    "moonshotai/kimi-k2-thinking": (0.60, 2.50),
    "moonshotai/kimi-k2-0905": (0.60, 2.50),
    "moonshotai/kimi-k2": (0.57, 2.30),
    "x-ai/grok-4.7": (1.60, 4.80),
}


def _path() -> Path:
    return Path(os.getenv("WORKDEV_CLI_AGENT_MODELS_FILE", "/var/lib/agents-healthcheck/cli-models.json"))


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


def _valid(agent: str, model: str) -> bool:
    return agent in MODELS and model in dict(MODELS[agent])


def selected(agent: str) -> str | None:
    if agent not in MODELS:
        return None
    value = _read(_path()).get(agent, {}).get("selected")
    return value if isinstance(value, str) and _valid(agent, value) else DEFAULTS[agent]


def describe(agent: str) -> dict:
    if agent not in MODELS:
        raise ValueError("Agente sem seleção de modelo")
    data = _read(_path()).get(agent, {})
    chosen = selected(agent)
    active = data.get("active")
    options = []
    for model, label in MODELS[agent]:
        pricing = PRICING.get(model)
        options.append({
            "model": model,
            "label": label,
            "input_cost_per_million": pricing[0] if pricing else None,
            "output_cost_per_million": pricing[1] if pricing else None,
            "expensive": bool(pricing and pricing[1] >= 10),
        })
    return {"agent": agent, "selected": chosen,
            "active": active if isinstance(active, str) and _valid(agent, active) else None,
            "options": options}


def _update(agent: str, field: str, model: str) -> None:
    if not _valid(agent, model):
        raise ValueError("Modelo inválido para este agente")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(path)
        row = data.setdefault(agent, {})
        row[field] = model
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def choose(agent: str, model: str) -> None:
    _update(agent, "selected", model)


def record_active(agent: str, model: str) -> None:
    _update(agent, "active", model)


def launcher(agent: str, command: list[str], model: str | None = None) -> list[str]:
    chosen = model or selected(agent)
    if agent not in MODELS or chosen is None:
        return command
    if not _valid(agent, chosen):
        raise ValueError("Modelo inválido para este agente")
    if agent == "gemini":
        return ["env", f"GEMINI_MODEL={chosen}", *command]
    if agent == "kimi":
        return ["env", "KIMI_PROVIDER=openrouter", f"KIMI_MODEL={chosen}", *command]
    if agent == "openrouter":
        return ["env", "QWEN_PROVIDER=openrouter", f"QWEN_MODEL={chosen}", *command]
    return [*command, "--model", chosen]
