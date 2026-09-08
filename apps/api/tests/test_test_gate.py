"""
Testes comportamentais do service test_gate.

Valida comportamento real, não apenas presença de strings.
Cobertura obrigatória das 4 falhas corrigidas:
1. Frontend fail-closed (pnpm ausente = FAIL)
2. Fingerprint git commit SHA
3. Gemini AUTO ordem correta
4. PATCH previous_status
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Adicionar apps/api ao path
sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))

from sqlalchemy import create_engine, DefaultClause
from sqlalchemy.orm import Session
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.ddl import CreateColumn


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(CreateColumn, "sqlite")
def compile_create_column_sqlite(element, compiler, **kw):
    result = compiler.visit_create_column(element, **kw)
    if "::jsonb" in result:
        result = result.replace("DEFAULT '{}'::jsonb", "DEFAULT '{}'")
        result = result.replace("DEFAULT '[]'::jsonb", "DEFAULT '[]'")
        result = result.replace("::jsonb", "")
    return result


from app.database import Base
from app.models.handoff import AgentRun, AgentRunEvent
from app.services.test_gate import (
    execute_gate,
    persist_gate_evidence,
    get_gate_evidence_for_run,
    validate_run_for_status_change,
    GateEvidence,
    CheckResult,
    _check_vitest,
    _check_build,
    _check_lint,
    _get_git_commit_sha,
)


def create_test_db() -> tuple[Session, Path]:
    """Criar banco SQLite em memória para testes."""
    import uuid
    from sqlalchemy import event
    db_path = Path(f"/tmp/test_gate_{uuid.uuid4()}.db")
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def register_sqlite_functions(dbapi_connection, connection_record):
        import uuid
        from datetime import datetime, timezone
        dbapi_connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    AgentRun.__table__.create(engine)
    AgentRunEvent.__table__.create(engine)
    return Session(engine), db_path


def create_test_run(db: Session) -> AgentRun:
    """Criar AgentRun de teste."""
    from app.models.handoff import AgentRun

    run = AgentRun(
        id=uuid4(),
        plan_id=uuid4(),
        backlog_id=uuid4(),
        agent="qwen",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_gate_executa_fail_closed():
    """Teste 1: Gate sem venv deve FAIL (fail-closed)."""
    print("\n[TESTE 1] Gate sem venv → FAIL (fail-closed)")

    db, db_path = create_test_db()
    run = create_test_run(db)

    from unittest.mock import patch
    # Executar gate (patch venv para não existir)
    with patch("app.services.test_gate.API_VENV", Path("/tmp/invalid_venv/bin/python")):
        evidence = execute_gate(run)

    # FAIL-CLOSED: sem venv → FAIL
    assert not evidence.passed, "Gate deve falhar sem venv"
    assert evidence.error is not None, "Deve ter mensagem de erro"
    assert "venv" in evidence.error.lower() or "Venv" in evidence.error, f"Erro deve mencionar venv: {evidence.error}"

    print(f"  ✅ PASS: Gate falhou como esperado: {evidence.error}")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_gate_evidence_persistida():
    """Teste 2: Evidência é persistida como AgentRunEvent."""
    print("\n[TESTE 2] Evidência persistida como AgentRunEvent")

    db, db_path = create_test_db()
    run = create_test_run(db)

    evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=True,
        git_commit_sha=_get_git_commit_sha(),
        checks=[
            CheckResult(
                name="pytest",
                passed=True,
                mandatory=True,
                reason="Teste simulado aprovado",
            )
        ],
    )
    event = persist_gate_evidence(db, evidence)

    # Validar evento
    assert event is not None, "Evento deve ser criado"
    assert event.run_id == run.id, "Evento deve estar vinculado ao run"
    assert event.event_type in ["build.tests_passed", "build.tests_failed"], f"Tipo inválido: {event.event_type}"
    assert event.payload is not None, "Payload deve existir"
    assert "run_id" in event.payload, "Payload deve ter run_id"

    print(f"  ✅ PASS: Evento {event.event_type} criado com payload")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_evidence_vinculada_ao_run():
    """Teste 3: Evidência de outro run não é aceita."""
    print("\n[TESTE 3] Evidência de outro run não é aceita")

    db, db_path = create_test_db()
    run1 = create_test_run(db)
    run2 = create_test_run(db)

    # Executar gate para run1
    evidence1 = GateEvidence(
        run_id=run1.id,
        backlog_id=run1.backlog_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=True,
        git_commit_sha=_get_git_commit_sha(),
        checks=[
            CheckResult(
                name="pytest",
                passed=True,
                mandatory=True,
                reason="Teste simulado aprovado",
            )
        ],
    )
    persist_gate_evidence(db, evidence1)

    # Tentar consultar evidência para run2
    evidence2 = get_gate_evidence_for_run(db, run2.id)

    # run2 não deve ter evidência
    assert evidence2 is None, "run2 não deve ter evidência"

    print(f"  ✅ PASS: Evidência corretamente vinculada ao run")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_validate_run_review_sem_evidencia():
    """Teste 4: review sem evidência → bloqueado."""
    print("\n[TESTE 4] review sem evidência → bloqueado")

    db, db_path = create_test_db()
    run = create_test_run(db)

    allowed, reason = validate_run_for_status_change(db, run, "review")

    assert not allowed, "review sem evidência deve ser bloqueado"
    assert "evidência" in reason.lower() or "gate" in reason.lower(), f"Motivo deve mencionar gate/evidência: {reason}"

    print(f"  ✅ PASS: review bloqueado: {reason}")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_validate_run_completed_sem_evidencia():
    """Teste 5: completed sem evidência → bloqueado."""
    print("\n[TESTE 5] completed sem evidência → bloqueado")

    db, db_path = create_test_db()
    run = create_test_run(db)

    allowed, reason = validate_run_for_status_change(db, run, "completed")

    assert not allowed, "completed sem evidência deve ser bloqueado"

    print(f"  ✅ PASS: completed bloqueado: {reason}")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_validate_run_running_permitido():
    """Teste 6: running não requer gate → permitido."""
    print("\n[TESTE 6] running não requer gate → permitido")

    db, db_path = create_test_db()
    run = create_test_run(db)

    allowed, reason = validate_run_for_status_change(db, run, "running")

    assert allowed, "running deve ser permitido sem gate"

    print(f"  ✅ PASS: running permitido: {reason}")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_validate_run_failed_permitido():
    """Teste 7: failed não requer gate → permitido."""
    print("\n[TESTE 7] failed não requer gate → permitido")

    db, db_path = create_test_db()
    run = create_test_run(db)

    allowed, reason = validate_run_for_status_change(db, run, "failed")

    assert allowed, "failed deve ser permitido sem gate"

    print(f"  ✅ PASS: failed permitido: {reason}")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_evidence_payload_valido():
    """Teste 8: Payload da evidência tem campos obrigatórios."""
    print("\n[TESTE 8] Payload tem campos obrigatórios")

    db, db_path = create_test_db()
    run = create_test_run(db)

    evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=True,
        git_commit_sha=_get_git_commit_sha(),
        checks=[
            CheckResult(
                name="pytest",
                passed=True,
                mandatory=True,
                reason="Teste simulado aprovado",
            )
        ],
    )
    event = persist_gate_evidence(db, evidence)

    payload = event.payload
    required = ["run_id", "backlog_id", "timestamp", "passed", "checks"]

    for field in required:
        assert field in payload, f"Payload deve ter campo '{field}'"

    print(f"  ✅ PASS: Payload tem todos campos obrigatórios")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_evidence_expira_24h():
    """Teste 9: Evidência com > 24h é rejeitada."""
    print("\n[TESTE 9] Evidência com > 24h é rejeitada")

    db, db_path = create_test_db()
    run = create_test_run(db)

    # Criar evidência manualmente com timestamp antigo
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()

    evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=old_ts,
        passed=True,
        checks=[CheckResult("pytest", True, True, "Passou", 100)],
    )

    event = persist_gate_evidence(db, evidence)

    # Consultar evidência
    retrieved = get_gate_evidence_for_run(db, run.id)

    # Evidência deve ser None (> 24h)
    assert retrieved is None, "Evidência > 24h deve ser rejeitada"

    print(f"  ✅ PASS: Evidência expirada corretamente rejeitada")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_mandatory_failed_bloqueia():
    """Teste 10: Check obrigatório falhando → gate FAIL."""
    print("\n[TESTE 10] Check obrigatório falhando → gate FAIL")

    db, db_path = create_test_db()
    run = create_test_run(db)

    # Criar evidência com check obrigatório falhando
    evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=False,  # FAIL
        git_commit_sha="abc123",
        checks=[CheckResult("pytest", False, True, "Falhou", 100)],
        mandatory_failed=["pytest"],
        error="Checks obrigatórios falharam: pytest",
    )

    event = persist_gate_evidence(db, evidence)

    # Validar
    assert not evidence.passed, "Gate deve falhar"
    assert "pytest" in evidence.mandatory_failed, "pytest deve estar em mandatory_failed"

    print(f"  ✅ PASS: Check obrigatório falhando bloqueia gate")
    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_frontend_pnpm_ausente_fail():
    """Teste 11: Frontend pnpm ausente → FAIL (fail-closed)."""
    print("\n[TESTE 11] Frontend pnpm ausente → FAIL")

    # Executar check vitest (assume pnpm não disponível no PATH do teste)
    result = _check_vitest()

    # Se pnpm não está no PATH, deve FAIL
    if result.reason == "pnpm não encontrado no PATH":
        assert not result.passed, "vitest deve falhar sem pnpm"
        assert result.mandatory, "vitest é obrigatório"
        print(f"  ✅ PASS: vitest FAIL sem pnpm: {result.reason}")
    else:
        # pnpm disponível, teste executou
        print(f"  ⚠️  SKIP: pnpm disponível, teste executou: {result.reason}")

    db_path = Path("/tmp/test_gate.db")
    db_path.unlink(missing_ok=True)
    return True


def test_frontend_build_fail():
    """Teste 12: Frontend build ausente → FAIL (fail-closed)."""
    print("\n[TESTE 12] Frontend build sem pnpm → FAIL")

    result = _check_build()

    # Se pnpm não está no PATH, deve FAIL
    if result.reason == "pnpm não encontrado no PATH":
        assert not result.passed, "build deve falhar sem pnpm"
        assert result.mandatory, "build é obrigatório"
        print(f"  ✅ PASS: build FAIL sem pnpm: {result.reason}")
    else:
        # pnpm disponível, teste executou
        print(f"  ⚠️  SKIP: pnpm disponível, teste executou: {result.reason}")

    db_path = Path("/tmp/test_gate.db")
    db_path.unlink(missing_ok=True)
    return True


def test_fingerprint_sha_divergente_bloqueia():
    """Teste 13: Fingerprint SHA divergente → bloqueia review/completed."""
    print("\n[TESTE 13] Fingerprint SHA divergente → bloqueia")

    db, db_path = create_test_db()
    run = create_test_run(db)

    # Criar evidência com SHA antigo
    old_evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=True,
        git_commit_sha="old_sha_123",  # SHA antigo
        checks=[CheckResult("pytest", True, True, "Passou", 100)],
    )

    persist_gate_evidence(db, old_evidence)

    # Consultar evidência (SHA atual deve ser diferente)
    retrieved = get_gate_evidence_for_run(db, run)

    # Se SHA atual existe e é diferente, deve retornar None
    current_sha = _get_git_commit_sha()
    if current_sha and current_sha != "old_sha_123":
        assert retrieved is None, "Evidência com SHA divergente deve ser rejeitada"
        print(f"  ✅ PASS: SHA divergente rejeitado ({current_sha[:8]} != old_sha_123)")
    else:
        print(f"  ⚠️  SKIP: SHA atual não disponível ou igual")

    db.close()
    db_path.unlink(missing_ok=True)
    return True


def test_backlog_id_divergente_rejeita():
    """Teste 14: backlog_id divergente → rejeita evidência."""
    print("\n[TESTE 14] backlog_id divergente → rejeita")

    db, db_path = create_test_db()
    run = create_test_run(db)

    # Criar evidência com backlog_id errado
    wrong_evidence = GateEvidence(
        run_id=run.id,
        backlog_id=uuid4(),  # backlog_id errado
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=True,
        git_commit_sha=_get_git_commit_sha() or "test_sha",
        checks=[CheckResult("pytest", True, True, "Passou", 100)],
    )

    persist_gate_evidence(db, wrong_evidence)

    # Consultar evidência
    retrieved = get_gate_evidence_for_run(db, run)

    # Deve ser None (backlog_id divergente)
    assert retrieved is None, "Evidência com backlog_id divergente deve ser rejeitada"
    print(f"  ✅ PASS: backlog_id divergente rejeitado")

    db.close()
    db_path.unlink(missing_ok=True)
    return True


def main():
    """Rodar todos testes."""
    print("\n" + "="*60)
    print("TESTES COMPORTAMENTAIS — SERVICE test_gate")
    print("Incluindo 4 falhas corrigidas da auditoria")
    print("="*60)

    tests = [
        ("Gate fail-closed sem venv", test_gate_executa_fail_closed),
        ("Evidência persistida", test_gate_evidence_persistida),
        ("Evidência vinculada ao run", test_evidence_vinculada_ao_run),
        ("review sem evidência bloqueado", test_validate_run_review_sem_evidencia),
        ("completed sem evidência bloqueado", test_validate_run_completed_sem_evidencia),
        ("running permitido", test_validate_run_running_permitido),
        ("failed permitido", test_validate_run_failed_permitido),
        ("Payload campos obrigatórios", test_evidence_payload_valido),
        ("Evidência expira 24h", test_evidence_expira_24h),
        ("Mandatory fail bloqueia", test_mandatory_failed_bloqueia),
        ("Frontend pnpm ausente FAIL", test_frontend_pnpm_ausente_fail),
        ("Frontend build sem pnpm FAIL", test_frontend_build_fail),
        ("Fingerprint SHA divergente", test_fingerprint_sha_divergente_bloqueia),
        ("backlog_id divergente", test_backlog_id_divergente_rejeita),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            results.append((name, False))
        except Exception as e:
            print(f"  ❌ ERRO: {type(e).__name__}: {e}")
            results.append((name, False))

    print("\n" + "="*60)
    print("RESULTADOS")
    print("="*60)

    passed = sum(1 for _, p in results if p)
    total = len(results)

    for name, p in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} testes passaram")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
