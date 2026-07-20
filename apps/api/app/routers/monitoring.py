import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter


router = APIRouter(prefix="/monitoring", tags=["monitoring"])

VPS2_HOST = os.getenv("WORKDEV_VPS2_HOST", "2.25.201.90")
VPS2_USER = os.getenv("WORKDEV_VPS2_USER", "workdev")
VPS2_KEY = os.getenv("WORKDEV_VPS2_KEY", "/root/.ssh/backup_vps2")


def _run(command: list[str], timeout: int = 6) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _service(name: str, target: str, online: bool, detail: str, latency: int) -> dict:
    return {
        "name": name,
        "target": target,
        "status": "online" if online else "offline",
        "detail": detail,
        "latency_ms": latency,
    }


def _check_vps1() -> dict:
    started = time.monotonic()
    try:
        api = _run(["systemctl", "is-active", "workdev-api"], timeout=3)
        docker = _run(["systemctl", "is-active", "docker"], timeout=3)
        active = api.stdout.strip() == "active" and docker.stdout.strip() == "active"
        detail = f"workdev-api: {api.stdout.strip()}; docker: {docker.stdout.strip()}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        active = False
        detail = f"Falha na checagem: {type(exc).__name__}"
    return _service(
        "VPS 1 Infrastructure",
        "VPS1",
        active,
        detail,
        round((time.monotonic() - started) * 1000),
    )


def _check_postgres() -> dict:
    started = time.monotonic()
    try:
        result = _run(["docker", "inspect", "postgres"], timeout=4)
        container = json.loads(result.stdout)[0] if result.returncode == 0 else {}
        container_state = container.get("State", {})
        state = container_state.get("Status", "")
        health = container_state.get("Health", {}).get("Status", "")
        active = result.returncode == 0 and state == "running" and health in {"healthy", ""}
        detail = f"container: {state or 'indisponível'}; health: {health or 'não configurado'}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        active = False
        detail = f"Falha na checagem: {type(exc).__name__}"
    return _service(
        "PostgreSQL",
        "VPS1 · container postgres",
        active,
        detail,
        round((time.monotonic() - started) * 1000),
    )


def _check_vps2() -> list[dict]:
    started = time.monotonic()
    remote_check = (
        "if pgrep -f '/opt/openclaw/dist/index.js gateway' >/dev/null; "
        "then echo openclaw=active; else echo openclaw=inactive; fi; "
        "printf 'agent='; systemctl is-active agente.service 2>/dev/null || true; "
        "printf 'agent_api='; systemctl is-active agente-api.service 2>/dev/null || true; "
        "if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; "
        "then echo ollama=active; else echo ollama=inactive; fi"
    )
    command = [
        "ssh",
        "-i", VPS2_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=yes",
        f"{VPS2_USER}@{VPS2_HOST}",
        remote_check,
    ]
    try:
        result = _run(command, timeout=9)
        latency = round((time.monotonic() - started) * 1000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        latency = round((time.monotonic() - started) * 1000)
        detail = f"SSH indisponível: {type(exc).__name__}"
        return [
            _service("VPS 2 Intelligence", "VPS2", False, detail, latency),
            _service("OpenClaw", "VPS2", False, "VPS2 indisponível", latency),
            _service("Agente Pessoal", "VPS2", False, "VPS2 indisponível", latency),
            _service("Ollama", "VPS2", False, "VPS2 indisponível", latency),
        ]

    if result.returncode != 0:
        detail = result.stderr.strip() or f"SSH encerrou com código {result.returncode}"
        return [
            _service("VPS 2 Intelligence", "VPS2", False, detail, latency),
            _service("OpenClaw", "VPS2", False, "VPS2 indisponível", latency),
            _service("Agente Pessoal", "VPS2", False, "VPS2 indisponível", latency),
            _service("Ollama", "VPS2", False, "VPS2 indisponível", latency),
        ]

    states = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    agent_active = states.get("agent") == "active" and states.get("agent_api") == "active"
    return [
        _service("VPS 2 Intelligence", "VPS2", True, "SSH acessível", latency),
        _service(
            "OpenClaw", "VPS2 · gateway", states.get("openclaw") == "active",
            f"gateway: {states.get('openclaw', 'desconhecido')}", latency,
        ),
        _service(
            "Agente Pessoal", "VPS2 · systemd", agent_active,
            f"bot: {states.get('agent', 'desconhecido')}; API: {states.get('agent_api', 'desconhecido')}", latency,
        ),
        _service(
            "Ollama", "VPS2 · :11434", states.get("ollama") == "active",
            f"API: {states.get('ollama', 'desconhecido')}", latency,
        ),
    ]


@router.get("/status")
def status():
    with ThreadPoolExecutor(max_workers=3) as executor:
        vps1_future = executor.submit(_check_vps1)
        postgres_future = executor.submit(_check_postgres)
        vps2_future = executor.submit(_check_vps2)
        services = [vps1_future.result(), *vps2_future.result(), postgres_future.result()]

    online = sum(service["status"] == "online" for service in services)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(services), "online": online},
        "services": services,
    }
