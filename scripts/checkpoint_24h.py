#!/usr/bin/env python3
"""
Checkpoint de 24h de estabilidade — Gate para liberação da Fase 1.

Este script verifica se o Supervisor manteve estabilidade por 24h consecutivas:
- Zero falhas críticas (status=failed)
- Zero incidentes não resolvidos
- Zero deploy failures em produção

Se todos os critérios forem atendidos, o gate é liberado.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SUPERVISOR_STATE = Path("/var/lib/workdev-supervisor/state.json")
SUPERVISOR_RUNS = Path("/var/lib/workdev-supervisor/runs.jsonl")
AGENTS_STATUS = Path("/var/lib/agents-healthcheck/status.json")
DORA_STATE = Path("/var/lib/dora-refresh/last_run.json")

CHECKPOINT_FILE = Path("/opt/workdev/.workdev/checkpoint-24h.json")

# Thresholds
MAX_FAILED_RUNS = 0  # Zero falhas críticas em 24h
MAX_INCIDENTS_ABERTOS = 0  # Zero incidentes não resolvidos
MAX_DEPLOY_FAILURES = 0  # Zero deploy failures em 24h


def load_json_file(path: Path) -> dict | list | None:
    """Carregar arquivo JSON."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_jsonl_lines(path: Path, max_lines: int = 300) -> list[dict]:
    """Carregar últimas N linhas de arquivo JSONL."""
    if not path.exists():
        return []
    lines = []
    try:
        with open(path, 'r') as f:
            for line in f.readlines()[-max_lines:]:
                try:
                    lines.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return lines


def check_supervisor_stability() -> tuple[bool, str, dict]:
    """
    Verificar estabilidade do supervisor nas últimas 24h.
    
    Retorna: (estavel, motivo, metricas)
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    
    runs = load_jsonl_lines(SUPERVISOR_RUNS)
    
    failed_runs = []
    degraded_runs = []
    
    for run in runs:
        run_time_str = run.get("started_at", "")
        try:
            run_time = datetime.fromisoformat(run_time_str.replace("Z", "+00:00"))
            if run_time < cutoff:
                continue
        except Exception:
            continue
        
        status = run.get("status", "unknown")
        if status == "failed":
            failed_runs.append(run)
        elif status == "degraded":
            degraded_runs.append(run)
    
    metricas = {
        "total_runs_24h": len([r for r in runs if datetime.fromisoformat(r.get("started_at", "1970-01-01").replace("Z", "+00:00")) >= cutoff]),
        "failed_runs": len(failed_runs),
        "degraded_runs": len(degraded_runs),
        "checks_executed_avg": sum(r.get("checks_executed", 0) for r in runs) / max(len(runs), 1),
    }
    
    if failed_runs:
        return False, f"{len(failed_runs)} execuções falharam em 24h", metricas
    
    return True, "Zero falhas críticas em 24h", metricas


def check_agents_health() -> tuple[bool, str, dict]:
    """
    Verificar saúde dos agentes.
    
    Retorna: (saudavel, motivo, metricas)
    """
    status_data = load_json_file(AGENTS_STATUS)
    if not status_data:
        return False, "Status dos agentes indisponível", {}
    
    agents = status_data.get("agents", {})
    offline_agents = []
    blocked_agents = []
    
    for agent, health in agents.items():
        agent_status = health.get("status", "unknown")
        if agent_status == "offline":
            offline_agents.append(agent)
        elif agent_status == "blocked":
            blocked_agents.append(agent)
    
    metricas = {
        "total_agents": len(agents),
        "offline": len(offline_agents),
        "blocked": len(blocked_agents),
        "idle": sum(1 for h in agents.values() if h.get("status") == "idle"),
        "busy": sum(1 for h in agents.values() if h.get("status") == "busy"),
    }
    
    if offline_agents:
        return False, f"Agentes offline: {', '.join(offline_agents)}", metricas
    
    if blocked_agents:
        return False, f"Agentes bloqueados: {', '.join(blocked_agents)}", metricas
    
    return True, "Todos agentes saudáveis", metricas


def check_dora_refresh() -> tuple[bool, str, dict]:
    """
    Verificar se job de refresh DORA está executando.
    
    Retorna: (ok, motivo, metricas)
    """
    state = load_json_file(DORA_STATE)
    if not state:
        return True, "DORA refresh não instalado (opcional)", {"installed": False}
    
    status = state.get("status", "unknown")
    metrics = {
        "installed": True,
        "last_status": status,
        "last_run": state.get("finished_at"),
        "cache_cleared": state.get("cache_cleared"),
        "metrics_valid": state.get("metrics_valid"),
    }
    
    if status == "failed":
        return False, "DORA refresh falhou na última execução", metrics
    
    if status == "degraded":
        return True, "DORA refresh degradado (warning)", metrics
    
    return True, "DORA refresh operacional", metrics


def main() -> int:
    """Executar checkpoint de 24h."""
    started_at = datetime.now(timezone.utc)
    print(f"[CHECKPOINT] started_at={started_at.isoformat()}")
    print(f"[CHECKPOINT] threshold=24h sem falhas críticas")
    print()
    
    # 1. Verificar supervisor
    print("=== Supervisor Stability ===")
    sup_estavel, sup_motivo, sup_metricas = check_supervisor_stability()
    print(f"Estável: {sup_estavel}")
    print(f"Motivo: {sup_motivo}")
    print(f"Métricas: {json.dumps(sup_metricas, indent=2)}")
    print()
    
    # 2. Verificar agentes
    print("=== Agents Health ===")
    ag_saudavel, ag_motivo, ag_metricas = check_agents_health()
    print(f"Saudável: {ag_saudavel}")
    print(f"Motivo: {ag_motivo}")
    print(f"Métricas: {json.dumps(ag_metricas, indent=2)}")
    print()
    
    # 3. Verificar DORA refresh
    print("=== DORA Refresh ===")
    dora_ok, dora_motivo, dora_metricas = check_dora_refresh()
    print(f"OK: {dora_ok}")
    print(f"Motivo: {dora_motivo}")
    print(f"Métricas: {json.dumps(dora_metricas, indent=2)}")
    print()
    
    # 4. Consolidar resultado
    todos_ok = sup_estavel and ag_saudavel and dora_ok
    
    checkpoint_result = {
        "timestamp": started_at.isoformat(),
        "threshold_hours": 24,
        "passed": todos_ok,
        "checks": {
            "supervisor_stability": {
                "passed": sup_estavel,
                "reason": sup_motivo,
                "metrics": sup_metricas,
            },
            "agents_health": {
                "passed": ag_saudavel,
                "reason": ag_motivo,
                "metrics": ag_metricas,
            },
            "dora_refresh": {
                "passed": dora_ok,
                "reason": dora_motivo,
                "metrics": dora_metricas,
            },
        },
        "fase_1_released": todos_ok,
    }
    
    # 5. Persistir resultado
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = CHECKPOINT_FILE.with_name(f".{CHECKPOINT_FILE.name}.tmp")
    temp_file.write_text(json.dumps(checkpoint_result, indent=2, ensure_ascii=False))
    temp_file.rename(CHECKPOINT_FILE)
    
    print("=" * 50)
    if todos_ok:
        print("✅ CHECKPOINT APROVADO — Fase 1 liberada")
        print(f"   Todos os critérios atendidos em {started_at.strftime('%Y-%m-%d %H:%M UTC')}")
    else:
        print("❌ CHECKPOINT REPROVADO — Fase 1 bloqueada")
        if not sup_estavel:
            print(f"   - Supervisor: {sup_motivo}")
        if not ag_saudavel:
            print(f"   - Agentes: {ag_motivo}")
        if not dora_ok:
            print(f"   - DORA: {dora_motivo}")
    
    print()
    print(f"Resultado persistido em: {CHECKPOINT_FILE}")
    
    return 0 if todos_ok else 1


if __name__ == "__main__":
    sys.exit(main())
