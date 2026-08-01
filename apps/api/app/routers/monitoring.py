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


def _proc_metrics(pid: int) -> dict:
    if not pid:
        return {}
    try:
        result = _run(["ps", "-o", "%cpu,%mem,etime", "-p", str(pid)], timeout=3)
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return {}
        cpu, mem, etime = lines[1].split(None, 2)
        return {"cpu_percent": float(cpu), "mem_percent": float(mem), "uptime": etime}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def _local_systemd_metrics(unit: str, log_lines: int = 15) -> dict:
    try:
        show = _run(
            ["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveState", "-p", "SubState"],
            timeout=3,
        )
        props = dict(line.split("=", 1) for line in show.stdout.splitlines() if "=" in line)
        pid = int(props.get("MainPID", "0") or 0)
        logs = _run(["journalctl", "-u", unit, "-n", str(log_lines), "--no-pager", "-o", "short-iso"], timeout=4)
        return {
            "active_state": props.get("ActiveState"),
            "sub_state": props.get("SubState"),
            **_proc_metrics(pid),
            "logs": logs.stdout.strip().splitlines() if logs.returncode == 0 else [],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"Falha na checagem: {type(exc).__name__}"}


def _vps2_ssh(remote_command: str, timeout: int = 9) -> subprocess.CompletedProcess[str] | None:
    command = [
        "ssh",
        "-i", VPS2_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=yes",
        f"{VPS2_USER}@{VPS2_HOST}",
        remote_command,
    ]
    try:
        return _run(command, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _vps2_systemd_metrics(unit: str, log_lines: int = 15) -> dict:
    remote = (
        f"systemctl show {unit} -p MainPID -p ActiveState -p SubState; "
        "echo ===METRICS===; "
        f"pid=$(systemctl show {unit} -p MainPID --value); "
        "if [ \"$pid\" != \"0\" ] && [ -n \"$pid\" ]; then ps -o %cpu,%mem,etime -p \"$pid\" | tail -1; fi; "
        "echo ===LOGS===; "
        f"journalctl -u {unit} -n {log_lines} --no-pager -o short-iso"
    )
    result = _vps2_ssh(remote)
    if result is None:
        return {"error": "SSH indisponível para VPS2"}
    if result.returncode != 0:
        return {"error": result.stderr.strip() or f"SSH código {result.returncode}"}
    props_part, _, rest = result.stdout.partition("===METRICS===\n")
    metrics_part, _, logs_part = rest.partition("===LOGS===\n")
    props = dict(line.split("=", 1) for line in props_part.splitlines() if "=" in line)
    metrics: dict = {"active_state": props.get("ActiveState"), "sub_state": props.get("SubState")}
    metrics_line = metrics_part.strip().splitlines()
    if metrics_line:
        try:
            cpu, mem, etime = metrics_line[-1].split(None, 2)
            metrics["cpu_percent"] = float(cpu)
            metrics["mem_percent"] = float(mem)
            metrics["uptime"] = etime
        except ValueError:
            pass
    metrics["logs"] = logs_part.strip().splitlines()
    return metrics


def _vps2_process_metrics(pattern: str) -> dict:
    remote = (
        f"pid=$(pgrep -f '{pattern}' | head -1); "
        "if [ -n \"$pid\" ]; then ps -o %cpu,%mem,etime -p \"$pid\" | tail -1; else echo NOPID; fi"
    )
    result = _vps2_ssh(remote, timeout=8)
    if result is None:
        return {"error": "SSH indisponível para VPS2"}
    if result.returncode != 0 or "NOPID" in result.stdout:
        return {"active_state": "inactive", "logs": []}
    try:
        cpu, mem, etime = result.stdout.strip().split(None, 2)
        return {
            "active_state": "active",
            "cpu_percent": float(cpu),
            "mem_percent": float(mem),
            "uptime": etime,
            "logs": [],
        }
    except ValueError:
        return {"active_state": "active", "logs": []}


PROJECT_INFRA = {
    "workdev-core": {"kind": "local_systemd", "unit": "workdev-api"},
    "agente-pessoal": {"kind": "vps2_systemd", "unit": "agente-api.service"},
    "openclaw": {"kind": "vps2_process", "pattern": "/opt/openclaw/dist/index.js gateway"},
}


@router.get("/status/{slug}")
def status_by_slug(slug: str):
    infra = PROJECT_INFRA.get(slug)
    checked_at = datetime.now(timezone.utc).isoformat()
    if infra is None:
        return {
            "slug": slug,
            "checked_at": checked_at,
            "monitored": False,
            "reason": (
                "Este projeto não roda como serviço systemd/docker sob controle do "
                "WorkDev (hospedagem externa — Vercel/Netlify/Supabase). Sem métricas "
                "de CPU/RAM/uptime a coletar aqui."
            ),
        }
    if infra["kind"] == "local_systemd":
        metrics = _local_systemd_metrics(infra["unit"])
    elif infra["kind"] == "vps2_systemd":
        metrics = _vps2_systemd_metrics(infra["unit"])
    else:
        metrics = _vps2_process_metrics(infra["pattern"])
    return {
        "slug": slug,
        "checked_at": checked_at,
        "monitored": True,
        "service": infra.get("unit") or infra.get("pattern"),
        **metrics,
    }


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
