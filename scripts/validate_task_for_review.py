#!/usr/bin/env python3
"""
Portão de testes antes da revisão humana.

Integração com o WorkDev:
- Validador standalone usado pelo piloto ponta a ponta e execução manual
- Executa checks nos ambientes corretos
- Não persiste AgentRunEvent; o gate oficial da API faz isso separadamente

Uso:
    python3 /opt/workdev/scripts/validate_task_for_review.py <task-id>
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKDIR = Path("/opt/workdev")
STATE_DIR = WORKDIR / ".workdev" / "review-gates"
LOG_TAG = "review-gate"

# Caminhos CORRETOS dos ambientes
API_VENV = WORKDIR / "apps/api" / "venv" / "bin" / "python"
API_DIR = WORKDIR / "apps/api"
WEB_DIR = WORKDIR / "apps/web"
PNPM = WEB_DIR / "node_modules" / ".bin" / "pnpm"


def run_command(cmd: list[str], cwd: Path, timeout: int = 300, env: dict | None = None) -> tuple[int, str, str]:
    """Executar comando e retornar (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env or os.environ.copy(),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout após {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def check_pytest() -> tuple[bool, str]:
    """Rodar pytest no ambiente correto da API."""
    print(f"[{LOG_TAG}] Executando pytest na API...")
    
    if not API_VENV.exists():
        return False, f"Venv da API não encontrado em {API_VENV}"
    
    exit_code, stdout, stderr = run_command(
        [str(API_VENV), "-m", "pytest", "-v", "--tb=short"],
        API_DIR,
        timeout=300,
    )
    
    if exit_code == 0:
        return True, "Todos testes Python passaram"
    elif exit_code == -1:
        return False, f"Timeout ou erro: {stderr}"
    else:
        lines = stderr.split("\n") + stdout.split("\n")
        failed_tests = [l for l in lines if "FAILED" in l or "ERROR" in l][:10]
        return False, f"{len(failed_tests)} testes falharam\n" + "\n".join(failed_tests)


def check_vitest() -> tuple[bool, str]:
    """Rodar vitest no diretório correto do web."""
    print(f"[{LOG_TAG}] Executando vitest no web...")
    
    if not PNPM.exists():
        return True, "pnpm não instalado no web (opcional)"
    
    exit_code, stdout, stderr = run_command(
        [str(PNPM), "test", "--", "--run"],
        WEB_DIR,
        timeout=300,
    )
    
    if exit_code == 0:
        return True, "Todos testes TypeScript passaram"
    elif exit_code == -1:
        return False, f"Timeout ou erro: {stderr}"
    else:
        return False, "Testes TypeScript falharam"


def check_linting() -> tuple[bool, str]:
    """Verificar linting nos ambientes corretos."""
    print(f"[{LOG_TAG}] Executando linting...")
    
    # ESLint para TypeScript (no web)
    if not PNPM.exists():
        return True, "pnpm não disponível (lint skipado)"
    
    exit_code, stdout, stderr = run_command(
        [str(PNPM), "lint"],
        WEB_DIR,
        timeout=120,
    )
    if exit_code != 0:
        return False, "ESLint encontrou issues"
    
    return True, "Linting OK"


def check_build() -> tuple[bool, str]:
    """Verificar se build do web funciona (tsc -b + vite)."""
    print(f"[{LOG_TAG}] Executando build do web (tsc -b + vite)...")
    
    if not PNPM.exists():
        return True, "pnpm não disponível (build skipado)"
    
    exit_code, stdout, stderr = run_command(
        [str(PNPM), "build"],
        WEB_DIR,
        timeout=300,
    )
    
    if exit_code == 0:
        return True, "Build OK"
    elif exit_code == -1:
        return False, f"Timeout no build"
    else:
        return False, "Build falhou"


def main() -> int:
    """Executar portão de revisão."""
    started_at = datetime.now(timezone.utc)
    task_id = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    
    print(f"[{LOG_TAG}] started_at={started_at.isoformat()}")
    print(f"[{LOG_TAG}] task_id={task_id}")
    print()
    
    # Checks obrigatórios
    mandatory_checks = [
        ("pytest", check_pytest, True),  # (nome, função, obrigatório)
    ]
    
    # Checks opcionais (não bloqueiam sozinhos)
    optional_checks = [
        ("vitest", check_vitest, False),
        ("linting", check_linting, False),
        ("build", check_build, False),
    ]
    
    results = {}
    mandatory_failed = []
    
    print("=== CHECKS OBRIGATÓRIOS ===")
    for name, check_fn, _ in mandatory_checks:
        print(f"\n--- {name.upper()} ---")
        passed, reason = check_fn()
        results[name] = {"passed": passed, "reason": reason, "mandatory": True}
        print(f"Status: {'✅ PASS' if passed else '❌ FAIL'}")
        print(f"Motivo: {reason}")
        if not passed:
            mandatory_failed.append(name)
    
    print("\n=== CHECKS OPCIONAIS ===")
    for name, check_fn, _ in optional_checks:
        print(f"\n--- {name.upper()} ---")
        passed, reason = check_fn()
        results[name] = {"passed": passed, "reason": reason, "mandatory": False}
        print(f"Status: {'✅ PASS' if passed else '⚠️  SKIP'}")
        print(f"Motivo: {reason}")
    
    # Consolidar resultado
    all_mandatory_passed = len(mandatory_failed) == 0
    
    gate_result = {
        "task_id": task_id,
        "timestamp": started_at.isoformat(),
        "passed": all_mandatory_passed,
        "mandatory_failed": mandatory_failed,
        "checks": results,
    }
    
    # Persistir resultado
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    result_file = STATE_DIR / f"{task_id}-{started_at.strftime('%Y%m%d-%H%M%S')}.json"
    result_file.write_text(json.dumps(gate_result, indent=2, ensure_ascii=False))
    
    print()
    print("=" * 60)
    if all_mandatory_passed:
        print(f"✅ GATE APROVADO — Task {task_id} pode ir para revisão")
    else:
        print(f"❌ GATE REPROVADO — Task {task_id} NÃO pode ir para revisão")
        print(f"   Checks obrigatórios falharam: {', '.join(mandatory_failed)}")
    
    print()
    print(f"Resultado persistido em: {result_file}")
    
    return 0 if all_mandatory_passed else 1


if __name__ == "__main__":
    sys.exit(main())
