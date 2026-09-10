"""Estado persistido do despacho de uma run para runtime Ollama (fatia 2).

Antes desta camada, `POST /runs/{id}/dispatch` lia a run, via `status in
{queued, running}` e chamava o driver. Dois POSTs simultâneos passavam os dois:
duas inferências, dois eventos, custo dobrado, e nada no banco registrando que
houve uma primeira. Era o achado 5 do plano de correção.

Aqui o despacho vira linha. Quem garante unicidade é o índice parcial
`uq_agent_build_jobs_active_run`, criado na migração `c3f9a5b28d41`: no máximo
um job em `queued`/`running` por run. A corrida é resolvida pelo banco no
INSERT, não por um `if` na aplicação — dois processos distintos, dois workers,
duas réplicas: o perdedor recebe IntegrityError e vira 409.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.handoff import AgentBuildJob, AgentRun


PARTIAL_FLUSH_SECONDS = 5.0
PARTIAL_MAX_CHARS = 60_000

ACTIVE_STATES = ("queued", "running")
FINAL_STATES = ("done", "failed", "cancelled")

DISPATCH_IDLE = "idle"
DISPATCH_QUEUED = "queued"
DISPATCH_RUNNING = "dispatching"
DISPATCH_DONE = "dispatched"
DISPATCH_FAILED = "failed"


class DispatchConflict(RuntimeError):
    """Já existe um despacho ativo para esta run."""

    def __init__(self, job: AgentBuildJob):
        self.job = job
        super().__init__(
            f"Despacho {job.id} já está {job.state} para esta run"
        )


def prompt_fingerprint(prompt: str) -> str:
    """Identidade do que foi mandado, sem guardar o prompt inteiro na linha."""
    return sha256(prompt.encode("utf-8")).hexdigest()


def active_job(db: Session, run_id: UUID) -> AgentBuildJob | None:
    return (
        db.query(AgentBuildJob)
        .filter(
            AgentBuildJob.run_id == run_id,
            AgentBuildJob.state.in_(ACTIVE_STATES),
        )
        .order_by(AgentBuildJob.created_at.desc())
        .first()
    )


def get_job(db: Session, run_id: UUID, job_id: UUID) -> AgentBuildJob | None:
    return (
        db.query(AgentBuildJob)
        .filter(
            AgentBuildJob.id == job_id,
            AgentBuildJob.run_id == run_id,
        )
        .first()
    )


def open_job(
    db: Session,
    run: AgentRun,
    *,
    runtime_id: str,
    model: str | None,
    prompt_sha256: str | None = None,
) -> AgentBuildJob:
    """Abre o job de despacho da run, sob lock, ou levanta DispatchConflict.

    O `with_for_update()` serializa duas requisições que chegam juntas para a
    MESMA run; o índice parcial cobre o resto (processos diferentes, banco
    replicado, worker que tenta reabrir). Os dois juntos, e não cada um
    sozinho, é que dão a garantia.
    """
    locked = (
        db.query(AgentRun)
        .filter(AgentRun.id == run.id)
        .with_for_update()
        .first()
    )

    if locked is None:  # pragma: no cover - run apagada entre leitura e lock
        raise RuntimeError("Execução desapareceu entre a leitura e o lock")

    existente = active_job(db, locked.id)

    if existente is not None:
        raise DispatchConflict(existente)

    attempt = (locked.dispatch_attempts or 0) + 1

    job = AgentBuildJob(
        run_id=locked.id,
        runtime_id=runtime_id,
        model=model,
        state="queued",
        attempt=attempt,
        prompt_sha256=prompt_sha256,
        payload={},
    )
    db.add(job)

    try:
        db.flush()
    except IntegrityError as error:
        # Perdemos a corrida no banco. A linha do vencedor é a resposta certa.
        db.rollback()
        vencedor = active_job(db, run.id)
        if vencedor is None:  # pragma: no cover - violação de outra constraint
            raise
        raise DispatchConflict(vencedor) from error

    locked.dispatch_state = DISPATCH_QUEUED
    locked.dispatch_attempts = attempt
    locked.last_dispatch_at = datetime.now(timezone.utc)
    locked.dispatch_token = uuid4()

    return job


def start_job(db: Session, job: AgentBuildJob) -> AgentBuildJob:
    job.state = "running"
    job.started_at = datetime.now(timezone.utc)
    run = db.query(AgentRun).filter(AgentRun.id == job.run_id).first()
    if run is not None:
        run.dispatch_state = DISPATCH_RUNNING
    db.flush()
    return job


def finish_job(
    db: Session,
    job: AgentBuildJob,
    *,
    payload: dict | None = None,
) -> AgentBuildJob:
    job.state = "done"
    job.finished_at = datetime.now(timezone.utc)
    job.payload = {**(job.payload or {}), **(payload or {})}
    run = db.query(AgentRun).filter(AgentRun.id == job.run_id).first()
    if run is not None:
        run.dispatch_state = DISPATCH_DONE
    db.flush()
    return job


def fail_job(
    db: Session,
    job: AgentBuildJob,
    *,
    error: str,
    payload: dict | None = None,
) -> AgentBuildJob:
    job.state = "failed"
    job.error = error
    job.finished_at = datetime.now(timezone.utc)
    job.payload = {**(job.payload or {}), **(payload or {})}
    run = db.query(AgentRun).filter(AgentRun.id == job.run_id).first()
    if run is not None:
        run.dispatch_state = DISPATCH_FAILED
    db.flush()
    return job


def partial_writer(job_id: UUID):
    """Devolve o `on_chunk` que grava o parcial da geração no Postgres.

    A sessão é própria e efêmera de propósito: a sessão do worker fica dentro
    de uma transação durante toda a inferência, e escrever o parcial por ela
    só o tornaria visível no commit final — ou seja, tarde demais para servir
    de parcial.

    Falha aqui nunca derruba a geração: perder o parcial é ruim, perder a
    resposta inteira porque o parcial não gravou seria pior.
    """
    ultimo_flush = 0.0

    async def _gravar(texto: str, raciocinio: str) -> None:
        nonlocal ultimo_flush
        agora = time.monotonic()
        if agora - ultimo_flush < PARTIAL_FLUSH_SECONDS:
            return
        ultimo_flush = agora

        sessao = SessionLocal()
        try:
            atual = (
                sessao.query(AgentBuildJob)
                .filter(AgentBuildJob.id == job_id)
                .first()
            )
            if atual is None:
                return
            atual.payload = {
                **(atual.payload or {}),
                "partial_response": texto[-PARTIAL_MAX_CHARS:],
                "partial_chars": len(texto),
                "partial_thinking_chars": len(raciocinio),
            }
            sessao.commit()
        except Exception:  # pragma: no cover - parcial nunca derruba a geração
            sessao.rollback()
        finally:
            sessao.close()

    return _gravar


def job_out(job: AgentBuildJob) -> dict:
    return {
        "job_id": str(job.id),
        "run_id": str(job.run_id),
        "runtime_id": job.runtime_id,
        "model": job.model,
        "state": job.state,
        "attempt": job.attempt,
        "prompt_sha256": job.prompt_sha256,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": (
            job.finished_at.isoformat() if job.finished_at else None
        ),
        # O que já foi gerado até agora. É isto que a tela mostra enquanto o
        # modelo pensa, e é o que sobra se a geração morrer no meio.
        "partial_response": (job.payload or {}).get("partial_response") or "",
        "partial_chars": (job.payload or {}).get("partial_chars") or 0,
        # Resultado do build isolado (ADR 005). Preenchido pelo worker quando o
        # envelope vira commit; nulo enquanto o job só trocou texto. Sem isto a
        # tela sabia que o job terminou mas não o que ele produziu — e o branch,
        # que é o entregável, ficava só no log do worker.
        "branch": (job.payload or {}).get("branch"),
        "commit_sha": (job.payload or {}).get("commit_sha"),
        "gate_passed": (job.payload or {}).get("gate_passed"),
        "files": (job.payload or {}).get("files") or [],
        "diffstat": (job.payload or {}).get("diffstat"),
    }
