#!/usr/bin/env python3
"""Verificacao pos-deploy do WorkDev, sem promover releases."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from predeploy_checks import listening_pids


CRITICAL_LOG = re.compile(r"traceback|exception|critical|segmentation fault", re.I)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


def system_command(command: list[str]) -> CommandResult:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
    return CommandResult(result.returncode, result.stdout, result.stderr)


def http_status(url: str) -> int:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "WorkDev-PostDeploy/1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0


def run_checks(
    command: Callable[[list[str]], CommandResult] = system_command,
    http: Callable[[str], int] = http_status,
) -> dict:
    checks: dict[str, dict] = {}
    show = command([
        "systemctl", "show", "workdev-api",
        "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "NRestarts",
    ])
    values = dict(
        line.split("=", 1) for line in show.stdout.splitlines() if "=" in line
    ) if show.returncode == 0 else {}
    main_pid = int(values.get("MainPID", "0") or 0)
    checks["service"] = {
        "ok": values.get("ActiveState") == "active" and values.get("SubState") == "running",
        "main_pid": main_pid,
    }
    checks["restarts"] = {"ok": values.get("NRestarts") == "0", "value": values.get("NRestarts")}

    sockets = command(["ss", "-H", "-ltnp", "sport = :8000"])
    pids = listening_pids(sockets.stdout) if sockets.returncode == 0 else set()
    checks["port"] = {"ok": main_pid > 0 and pids == {main_pid}, "pids": sorted(pids)}

    processes = command(["pgrep", "-a", "-f", "uvicorn.*0.0.0.0.*8000"])
    process_pids = {
        int(line.split(maxsplit=1)[0])
        for line in processes.stdout.splitlines()
        if line.split(maxsplit=1) and line.split(maxsplit=1)[0].isdigit()
    }
    checks["orphans"] = {"ok": process_pids == {main_pid}, "pids": sorted(process_pids)}

    journal = command([
        "journalctl", "-u", "workdev-api", "--since", "5 minutes ago", "--no-pager",
    ])
    critical = CRITICAL_LOG.search(journal.stdout or journal.stderr) is not None
    checks["journal"] = {"ok": journal.returncode == 0 and not critical}

    for name, url in {
        "health": "http://127.0.0.1:8000/health",
        "api_projects": "http://127.0.0.1:8000/api/projects",
        "frontend_local": "http://127.0.0.1:8000/",
        "frontend_public": "https://workdev.bpfconsult.com.br/",
    }.items():
        status = http(url)
        route_exists = name == "api_projects" and status in {401, 403}
        checks[name] = {"ok": 200 <= status < 400 or route_exists, "http": status}

    critical_names = {"service", "port", "orphans", "health", "api_projects"}
    failed_critical = [name for name in critical_names if not checks[name]["ok"]]
    failed_secondary = [name for name, value in checks.items() if not value["ok"] and name not in critical_names]
    status = (
        "DEPLOY_FAILED" if failed_critical
        else "DEPLOY_DEGRADED" if failed_secondary
        else "DEPLOY_SUCCEEDED"
    )
    return {"status": status, "checks": checks}


def main() -> int:
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "DEPLOY_SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
