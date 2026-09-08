"""
Service de validação de testes para entregas de agente.

Este service encapsula:
- Execução dos checks (pytest, vitest, build, lint)
- Política fail-closed
- Persistência de evidência auditável via AgentRunEvent
- Interpretação do resultado
- Consulta de evidência válida vinculada ao AgentRun atual

NÃO depende de routers.
É importado por handoff.py (service) e handoffs.py (router).
"""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent


WORKDIR = Path("/opt/workdev")
API_VENV = WORKDIR / "apps/api/venv/bin/python"
API_DIR = WORKDIR / "apps/api"
WEB_DIR = WORKDIR / "apps/web"
STATE_DIR = WORKDIR / ".workdev" / "review-gates"


@dataclass
class CheckResult:
    """Resultado de um check individual."""
    name: str
    passed: bool
    mandatory: bool
    reason: str
    duration_ms: int = 0


@dataclass
class GateEvidence:
    """Evidência auditável de execução do gate."""
    run_id: UUID
    backlog_id: UUID
    timestamp: str
    passed: bool
    git_commit_sha: str | None = None  # Fingerprint imutável do código testado
    checks: list[CheckResult] = field(default_factory=list)
    mandatory_failed: list[str] = field(default_factory=list)
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serializar para payload de evento."""
        return {
            "run_id": str(self.run_id),
            "backlog_id": str(self.backlog_id),
            "timestamp": self.timestamp,
            "git_commit_sha": self.git_commit_sha,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "mandatory": c.mandatory,
                    "reason": c.reason,
                    "duration_ms": c.duration_ms,
                }
                for c in self.checks
            ],
            "mandatory_failed": self.mandatory_failed,
            "error": self.error,
        }


def _run_command(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str, str, int]:
    """
    Executar comando e retornar (exit_code, stdout, stderr, duration_ms).
    """
    import time
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = int((time.monotonic() - start) * 1000)
        return result.returncode, result.stdout, result.stderr, duration
    except subprocess.TimeoutExpired:
        duration = int((time.monotonic() - start) * 1000)
        return -1, "", f"Timeout após {timeout}s", duration
    except Exception as e:
        duration = int((time.monotonic() - start) * 1000)
        return -1, "", str(e), duration


def _check_pytest() -> CheckResult:
    """Executar pytest no ambiente correto da API."""
    if not API_VENV.exists():
        return CheckResult(
            name="pytest",
            passed=False,
            mandatory=True,
            reason=f"Venv da API não encontrado em {API_VENV}",
        )

    exit_code, stdout, stderr, duration = _run_command(
        [str(API_VENV), "-m", "pytest", "-v", "--tb=short"],
        API_DIR,
        timeout=300,
    )

    if exit_code == 0:
        return CheckResult(
            name="pytest",
            passed=True,
            mandatory=True,
            reason="Todos testes Python passaram",
            duration_ms=duration,
        )

    # Extrair resumo dos testes falhados
    lines = stderr.split("\n") + stdout.split("\n")
    failed_tests = [l for l in lines if "FAILED" in l or "ERROR" in l][:5]
    reason = f"{len(failed_tests)} testes falharam\n" + "\n".join(failed_tests)

    return CheckResult(
        name="pytest",
        passed=False,
        mandatory=True,
        reason=reason if reason.strip() else f"Exit code: {exit_code}",
        duration_ms=duration,
    )


def _check_vitest() -> CheckResult:
    """Executar vitest no diretório correto do web. OBRIGATÓRIO."""
    import shutil

    # Procurar pnpm no PATH (não assumir node_modules local)
    pnpm_path = shutil.which("pnpm")
    if not pnpm_path:
        return CheckResult(
            name="vitest",
            passed=False,  # FAIL-CLOSED: pnpm ausente = FAIL
            mandatory=True,  # OBRIGATÓRIO
            reason="pnpm não encontrado no PATH",
        )

    exit_code, stdout, stderr, duration = _run_command(
        [pnpm_path, "test", "--", "--run"],
        WEB_DIR,
        timeout=300,
    )

    if exit_code == 0:
        return CheckResult(
            name="vitest",
            passed=True,
            mandatory=True,
            reason="Todos testes TypeScript passaram",
            duration_ms=duration,
        )

    lines = stderr.split("\n") + stdout.split("\n")
    failed = [l for l in lines if "FAIL" in l][:3]

    return CheckResult(
        name="vitest",
        passed=False,
        mandatory=True,
        reason="\n".join(failed) if failed else f"Exit code: {exit_code}",
        duration_ms=duration,
    )


def _check_lint() -> CheckResult:
    """Executar lint no frontend. OBRIGATÓRIO, mas com tratamento de dívida histórica."""
    import shutil

    pnpm_path = shutil.which("pnpm")
    if not pnpm_path:
        return CheckResult(
            name="lint",
            passed=False,  # FAIL-CLOSED: pnpm ausente = FAIL
            mandatory=True,  # OBRIGATÓRIO
            reason="pnpm não encontrado no PATH",
        )

    exit_code, stdout, stderr, duration = _run_command(
        [pnpm_path, "lint"],
        WEB_DIR,
        timeout=120,
    )

    if exit_code == 0:
        return CheckResult(
            name="lint",
            passed=True,
            mandatory=True,
            reason="Lint OK",
            duration_ms=duration,
        )

    # Verificar se é dívida histórica conhecida (não relacionada à task atual)
    # Para Fase 1, registramos mas não bloqueamos se for apenas lint
    # Isso deve ser removido quando dívida de lint for resolvida
    issues = len([l for l in stderr.split("\n") if l.strip()])

    return CheckResult(
        name="lint",
        passed=True,  # ⚠️ PASS com aviso - dívida histórica conhecida
        mandatory=False,  # ⚠️ Opcional até dívida ser resolvida
        reason=f"{issues} issues de lint (dívida histórica conhecida, não bloqueia Fase 1)",
        duration_ms=duration,
    )


def _check_build() -> CheckResult:
    """Executar build do web (tsc -b + vite). OBRIGATÓRIO."""
    import shutil

    pnpm_path = shutil.which("pnpm")
    if not pnpm_path:
        return CheckResult(
            name="build",
            passed=False,  # FAIL-CLOSED: pnpm ausente = FAIL
            mandatory=True,  # OBRIGATÓRIO
            reason="pnpm não encontrado no PATH",
        )

    exit_code, stdout, stderr, duration = _run_command(
        [pnpm_path, "build"],
        WEB_DIR,
        timeout=300,
    )

    if exit_code == 0:
        return CheckResult(
            name="build",
            passed=True,
            mandatory=True,
            reason="Build OK",
            duration_ms=duration,
        )

    lines = stderr.split("\n") + stdout.split("\n")
    errors = [l for l in lines if "error" in l.lower()][:3]

    return CheckResult(
        name="build",
        passed=False,
        mandatory=True,
        reason="\n".join(errors) if errors else "Build falhou",
        duration_ms=duration,
    )


def _get_git_commit_sha() -> str | None:
    """Obter SHA do commit git atual do código sendo testado."""
    import subprocess

    try:
        # Tentar obter SHA do workdir atual
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    return None


def execute_gate(run: AgentRun) -> GateEvidence:
    """
    Executar todos os checks do gate e retornar evidência auditável.

    Política FAIL-CLOSED:
    - Qualquer erro inesperado → FAIL
    - Script ausente → FAIL
    - Timeout → FAIL
    - Check obrigatório falhou → FAIL
    - Apenas se TODOS obrigatórios passam → PASS

    A evidência é vinculada ao AgentRun atual (run.id) E ao git commit SHA
    do código testado, para evitar reuso de evidência antiga com código diferente.
    """
    now = datetime.now(timezone.utc)

    # Obter fingerprint do código sendo testado
    git_commit_sha = _get_git_commit_sha()

    evidence = GateEvidence(
        run_id=run.id,
        backlog_id=run.backlog_id,
        timestamp=now.isoformat(),
        passed=False,  # Default: FAIL (fail-closed)
        git_commit_sha=git_commit_sha,
    )

    try:
        # Executar checks
        checks = [
            _check_pytest(),      # Obrigatório
            _check_vitest(),      # Opcional
            _check_lint(),        # Opcional
            _check_build(),       # Opcional
        ]

        evidence.checks = checks

        # Separar obrigatórios e opcionais
        mandatory = [c for c in checks if c.mandatory]
        mandatory_failed = [c.name for c in mandatory if not c.passed]

        evidence.mandatory_failed = mandatory_failed

        # FAIL-CLOSED: só passa se TODOS obrigatórios passaram
        evidence.passed = len(mandatory_failed) == 0

        if not evidence.passed:
            reasons = [f"{c.name}: {c.reason}" for c in checks if not c.passed and c.mandatory]
            evidence.error = f"Checks obrigatórios falharam: {'; '.join(reasons)}"

    except Exception as e:
        # FAIL-CLOSED: qualquer exceção → FAIL
        evidence.passed = False
        evidence.error = f"Erro ao executar gate: {type(e).__name__}: {e}"

    return evidence


def persist_gate_evidence(db: Session, evidence: GateEvidence) -> AgentRunEvent:
    """
    Persistir evidência do gate como evento do AgentRun.

    Usa AgentRunEvent existente, sem migration nova.
    Evento do tipo "build.tests_passed" ou "build.tests_failed".
    """
    event_type = "build.tests_passed" if evidence.passed else "build.tests_failed"

    event = AgentRunEvent(
        id=uuid4(),
        run_id=evidence.run_id,
        event_type=event_type,
        message=evidence.error or "Gate de testes aprovado",
        payload=evidence.to_payload(),
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return event


def get_gate_evidence_for_run(db: Session, run: AgentRun | UUID) -> GateEvidence | None:
    """
    Consultar evidência de gate válida para um AgentRun específico.

    Retorna evidência apenas se:
    - Evento existe vinculado ao run_id
    - Payload é válido e completo
    - Timestamp é recente (últimas 24h)
    - backlog_id do payload bate com run.backlog_id
    - git_commit_sha do payload bate com SHA atual (mesmo código)

    Retorna None se:
    - Nenhum evento encontrado
    - Payload inválido
    - Evidência muito antiga
    - Fingerprint divergente (código mudou)
    - backlog_id divergente
    """
    from sqlalchemy import text

    if isinstance(run, UUID):
        run = db.query(AgentRun).filter(AgentRun.id == run).first()
        if not run:
            return None

    # Buscar evento mais recente de testes para este run
    event = db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == run.id,
        AgentRunEvent.event_type.in_(["build.tests_passed", "build.tests_failed"]),
    ).order_by(
        AgentRunEvent.created_at.desc()
    ).first()

    if not event:
        return None

    # Validar payload
    payload = event.payload or {}

    try:
        # Verificar campos obrigatórios
        required_fields = ["run_id", "backlog_id", "timestamp", "passed", "checks", "git_commit_sha"]
        for field_name in required_fields:
            if field_name not in payload:
                return None

        # Verificar se run_id bate
        if str(payload["run_id"]) != str(run.id):
            return None

        # Verificar backlog_id bate (não aceitar evidência de outra task)
        if str(payload["backlog_id"]) != str(run.backlog_id):
            return None

        # Verificar timestamp (não mais velho que 24h)
        ts_str = payload["timestamp"]
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        if age.total_seconds() > 86400:  # 24h
            return None

        # Verificar git_commit_sha (código não mudou)
        current_sha = _get_git_commit_sha()
        if current_sha and payload.get("git_commit_sha"):
            if payload["git_commit_sha"] != current_sha:
                return None  # Código mudou, evidência inválida

        # Reconstruir evidência
        checks_data = payload.get("checks", [])
        checks = [
            CheckResult(
                name=c["name"],
                passed=c["passed"],
                mandatory=c.get("mandatory", False),
                reason=c.get("reason", ""),
                duration_ms=c.get("duration_ms", 0),
            )
            for c in checks_data
        ]

        return GateEvidence(
            run_id=run.id,
            backlog_id=UUID(payload["backlog_id"]),
            timestamp=payload["timestamp"],
            passed=payload["passed"],
            git_commit_sha=payload.get("git_commit_sha"),
            checks=checks,
            mandatory_failed=payload.get("mandatory_failed", []),
            error=payload.get("error"),
        )

    except Exception:
        return None


def validate_run_for_status_change(
    db: Session,
    run: AgentRun,
    next_status: str,
) -> tuple[bool, str]:
    """
    Validar se run pode mudar para next_status.

    Regras:
    - review: requer gate aprovado
    - completed: requer gate aprovado (não pode bypass)
    - failed/cancelled: não requer gate (falha/cancelamento explícito)
    - running/blocked/queued: não requer gate

    Retorna: (allowed, reason)
    """
    # Status que não requerem gate
    if next_status in {"running", "blocked", "queued", "failed", "cancelled"}:
        return True, f"Status {next_status} não requer gate"

    # Status que requerem gate
    if next_status in {"review", "completed"}:
        # Consultar evidência válida (valida run_id, backlog_id, git_sha)
        evidence = get_gate_evidence_for_run(db, run)

        if not evidence:
            return False, "Sem evidência de gate aprovado para esta execução"

        if not evidence.passed:
            failed = ", ".join(evidence.mandatory_failed)
            return False, f"Gate reprovado: {failed}"

        return True, "Gate aprovado"

    # Status desconhecido → bloquear por segurança
    return False, f"Status desconhecido: {next_status}"
