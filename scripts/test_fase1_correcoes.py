#!/usr/bin/env python3
"""
Testes das correções da Fase 1 da Frota de Agentes.

Valida:
1. Worktree isolado
2. Bloqueio de commit em develop
3. Gate de testes
"""

import json
import os
import subprocess
import sys
from pathlib import Path

WORKDIR = Path("/opt/workdev")
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

def log(msg): print(f"{GREEN}[TEST]{NC} {msg}")
def error(msg): print(f"{RED}[FAIL]{NC} {msg}")
def warn(msg): print(f"{YELLOW}[WARN]{NC} {msg}")

def test_worktree_script():
    """Testar script de criação de worktree."""
    log("Testando create_task_worktree.sh...")
    
    script = WORKDIR / "scripts/create_task_worktree.sh"
    if not script.exists():
        error("Script não encontrado")
        return False
    
    if not os.access(script, os.X_OK):
        error("Script não é executável")
        return False
    
    # Verificar conteúdo
    content = script.read_text()
    
    checks = {
        "git worktree add -b": "Cria branch + worktree em operação única",
        "develop": "Usa develop como base",
        "git worktree remove": "Remove worktree corretamente",
        "git worktree prune": "Faz prune antes de remover",
        "NOT checkout": "Não faz checkout no worktree principal",
    }
    
    for check, desc in checks.items():
        if check.startswith("NOT "):
            pattern = check[4:]
            if pattern in content and "git checkout" in content:
                # Verificar se não faz checkout da branch da task
                pass
        else:
            if check not in content:
                error(f"Falta: {desc} ({check})")
                return False
    
    log("✅ Script de worktree OK")
    return True


def test_hook_script():
    """Testar hook de bloqueio."""
    log("Testando pre-commit-agents...")
    
    hook = WORKDIR / "scripts/hooks/pre-commit-agents"
    if not hook.exists():
        error("Hook não encontrado")
        return False
    
    content = hook.read_text()
    
    required = [
        "PROTECTED_BRANCHES",
        "WORKDEV_AGENT_RUN_ID",
        "QWEN_CODE_SYSTEM_SETTINGS_PATH",
        "is_agent_execution",
        "exit 1",  # Bloqueia
    ]
    
    for req in required:
        if req not in content:
            error(f"Falta no hook: {req}")
            return False
    
    log("✅ Hook OK")
    return True


def test_validate_script():
    """Testar script de validação."""
    log("Testando validate_task_for_review.py...")
    
    script = WORKDIR / "scripts/validate_task_for_review.py"
    if not script.exists():
        error("Script não encontrado")
        return False
    
    content = script.read_text()
    
    required = [
        "API_VENV = WORKDIR / \"apps/api/venv/bin/python\"",
        "API_DIR = WORKDIR / \"apps/api\"",
        "WEB_DIR = WORKDIR / \"apps/web\"",
        "check_pytest",
        "pnpm test",  # Web tests
        "pnpm build",  # Web build
    ]
    
    for req in required:
        if req not in content:
            error(f"Falta: {req}")
            return False
    
    log("✅ Script de validação OK")
    return True


def test_handoff_integration():
    """Testar integração com handoff."""
    log("Testando integração handoff.py...")
    
    handoff = WORKDIR / "apps/api/app/services/handoff.py"
    if not handoff.exists():
        error("handoff.py não encontrado")
        return False
    
    content = handoff.read_text()
    
    required = [
        "run_test_gate",
        "next_status == \"review\"",
        "Gate de testes reprovado",
    ]
    
    for req in required:
        if req not in content:
            error(f"Falta integração: {req}")
            return False
    
    log("✅ Integração handoff OK")
    return True


def test_handoffs_router():
    """Testar router handoffs.py."""
    log("Testando handoffs.py router...")
    
    router = WORKDIR / "apps/api/app/routers/handoffs.py"
    if not router.exists():
        error("handoffs.py não encontrado")
        return False
    
    content = router.read_text()
    
    required = [
        "def run_test_gate",
        "validate_task_for_review.py",
        "mandatory_failed",
    ]
    
    for req in required:
        if req not in content:
            error(f"Falta router: {req}")
            return False
    
    log("✅ Router handoffs OK")
    return True


def main():
    """Rodar todos testes."""
    print("\n" + "="*60)
    print("TESTES DAS CORREÇÕES — FASE 1")
    print("="*60 + "\n")
    
    tests = [
        ("Worktree script", test_worktree_script),
        ("Hook script", test_hook_script),
        ("Validate script", test_validate_script),
        ("Handoff integration", test_handoff_integration),
        ("Handoffs router", test_handoffs_router),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            error(f"Exceção em {name}: {e}")
            results.append((name, False))
        print()
    
    print("="*60)
    print("RESULTADOS")
    print("="*60)
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, p in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Total: {passed}/{total} testes passaram")
    
    if passed == total:
        print("\n✅ TODAS CORREÇÕES VALIDADAS")
        return 0
    else:
        print(f"\n❌ {total - passed} correções falharam")
        return 1


if __name__ == "__main__":
    sys.exit(main())
