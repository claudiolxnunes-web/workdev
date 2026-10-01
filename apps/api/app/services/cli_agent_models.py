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
    # qwen, grok e deepseek: mesma CLI qwen, via OpenRouter (OPENROUTER_API_KEY).
    "qwen": (("qwen/qwen3.5-397b-a17b", "Qwen Coder (Qwen 3.5)"),
             ("qwen/qwen3-coder-flash", "Qwen3 Coder Flash"),
             ("qwen/qwen3-coder-next", "Qwen3 Coder Next")),
    "grok": (("x-ai/grok-4.7", "Grok 4.7 (premium)"),
             ("x-ai/grok-4.3", "Grok 4.3 (médio)"),
             ("x-ai/grok-build-0.1", "Grok Build 0.1 (barato, código)")),
    "deepseek": (("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash"),
                 ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
                 ("deepseek/deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813")),
}
# Agentes CLI que rodam a CLI qwen contra a OpenRouter.
OPENROUTER_CLI_AGENTS = ("qwen", "grok", "deepseek")
DEFAULTS = {"gemini": "gemini-3.5-flash", "claude": "claude-opus-5",
            "codex": "gpt-5.6-sol", "kimi": "moonshotai/kimi-k3",
            "qwen": "qwen/qwen3.5-397b-a17b",
            "grok": "x-ai/grok-4.7",
            "deepseek": "deepseek/deepseek-v4-flash"}

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
    "qwen/qwen3.5-397b-a17b": (0.55, 3.50),
    "qwen/qwen3-coder-flash": (0.195, 0.975),
    "qwen/qwen3-coder-next": (0.12, 0.80),
    "x-ai/grok-4.7": (2.00, 6.00),
    "x-ai/grok-4.3": (1.25, 2.50),
    "x-ai/grok-build-0.1": (1.00, 2.00),
    "deepseek/deepseek-v4-flash": (0.0419, 0.0837),
    "deepseek/deepseek-v4.1-flash": (0.03, 0.50),
    "deepseek/deepseek-v4-pro-0813": (0.66, 1.98),
    "moonshotai/kimi-k3": (0.6635, 10.00),
    "moonshotai/kimi-k3:batch": (2.28, 11.40),
    "moonshotai/kimi-k2.7-code": (0.6712, 3.35),
    "moonshotai/kimi-k2.6": (0.4341, 1.828),
    "moonshotai/kimi-k2.5": (0.45, 2.25),
    "moonshotai/kimi-k2-thinking": (0.60, 2.50),
    "moonshotai/kimi-k2-0905": (0.60, 2.50),
    "moonshotai/kimi-k2": (0.57, 2.30),
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
    if agent == "qwen":
        return ["env", "QWEN_PROVIDER=openrouter", f"QWEN_MODEL={chosen}", *command]
    if agent == "grok":
        return ["env", f"GROK_MODEL={chosen}", *command]
    if agent == "deepseek":
        return ["env", f"DEEPSEEK_MODEL={chosen}", *command]
    return [*command, "--model", chosen]
