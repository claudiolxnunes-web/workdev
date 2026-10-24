"""Vigia da memória disponível dos agentes e da Bancada Local.

Usa MemAvailable (não "used"): o modelo local fica em memória mapeada e conta
como cache, então "used" engana. Alerta só depois de a condição persistir
(sem ruído de pico curto), reenvia enquanto durar e avisa a normalização.
Falha de leitura nunca vira "tudo ok": devolve nível "unknown" e exit 1.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

OK, LOW, CRITICAL, UNKNOWN = "ok", "low", "critical", "unknown"
HOLD_SECONDS = 120        # condição precisa persistir antes do primeiro alerta
REPEAT_SECONDS = 1800     # reenvio enquanto continuar degradado


def _mb(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def thresholds() -> dict[str, int]:
    return {"low": _mb("WORKDEV_MEM_LOW_MB", 6144), "critical": _mb("WORKDEV_MEM_CRITICAL_MB", 3072),
            "swap": _mb("WORKDEV_SWAP_USED_LOW_MB", 8192)}


def read_meminfo(path: str = "/proc/meminfo") -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path(path).read_text().splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name] = int(parts[0]) // 1024  # kB -> MB
    if "MemAvailable" not in values:
        raise ValueError("MemAvailable ausente em /proc/meminfo")
    return values


def classify(meminfo: dict[str, int], limits: dict[str, int] | None = None) -> str:
    limits = limits or thresholds()
    available = meminfo["MemAvailable"]
    swap_used = meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)
    if available < limits["critical"]:
        return CRITICAL
    if available < limits["low"] or swap_used > limits["swap"]:
        return LOW
    return OK


def top_consumers(count: int = 3) -> str:
    try:
        out = subprocess.run(["ps", "-eo", "rss,comm", "--sort=-rss"], capture_output=True,
                             text=True, timeout=3, check=False).stdout.splitlines()[1:count + 1]
        return ", ".join(f"{line.split(None, 1)[1]} {int(line.split()[0]) // 1024} MB" for line in out)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return "indisponível"


def message(level: str, meminfo: dict[str, int], consumers: str) -> str:
    swap_used = meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0)
    detail = f"disponível {meminfo['MemAvailable']} MB, swap em uso {swap_used} MB; maiores: {consumers}"
    if level == OK:
        return f"[memória] normalizada: {detail}."
    return f"[memória] {'CRÍTICA' if level == CRITICAL else 'baixa'}: {detail}."


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        json.dump(state, handle)
        temporary = Path(handle.name)
    temporary.replace(path)


def check(state_file: Path, send_alert: Callable[[str], None], *, now: float | None = None,
          reader: Callable[[], dict[str, int]] = read_meminfo,
          consumers: Callable[[], str] = top_consumers) -> tuple[str, int]:
    """Avalia, alerta se for o caso e devolve (nível, exit_code)."""
    now = time.time() if now is None else now
    try:
        meminfo = reader()
    except (OSError, ValueError) as error:
        send_alert(f"[memória] não foi possível medir a memória disponível: {error}")
        return UNKNOWN, 1
    level = classify(meminfo)
    state = _read_state(state_file)
    if state.get("observed") != level:
        state.update(observed=level, since=now)
    state.setdefault("notified", OK)
    state.setdefault("last_sent", 0)
    held = now - state.get("since", now) >= HOLD_SECONDS
    changed = level != state["notified"]
    repeat = level != OK and now - state["last_sent"] >= REPEAT_SECONDS
    if held and (changed or repeat):
        send_alert(message(level, meminfo, consumers()))
        state.update(notified=level, last_sent=now)
    _write_state(state_file, state)
    return level, int(level == CRITICAL)
