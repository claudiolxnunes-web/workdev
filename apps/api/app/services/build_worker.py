"""Consumidor definitivo da fila de Build (ADR 005, fatia 3f).

Substitui o consumidor provisório in-process da fatia 2. A diferença não é só
onde roda: o provisório apenas guardava o texto do modelo como evento; este
transforma o texto em commit num branch isolado, passando pelo gate.

Concorrência: o claim usa `FOR UPDATE SKIP LOCKED`. Dois workers competindo pelo
mesmo job não bloqueiam um ao outro — o segundo simplesmente pula para o
próximo. É o que permite mais de um worker sem mudança de schema.

Segurança: nada aqui executa texto do modelo. O worker chama `execute_build`,
que valida o envelope e só então escreve arquivos, dentro de um worktree.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.handoff import AgentBuildJob, AgentRun
from app.services import build_jobs, context_egress
from app.services.context_egress import EgressDenied
from app.services.build_executor import (
    BuildOutcome,
    build_enabled,
    execute_build,
    max_attempts,
    outcome_payload,
    persist_outcome,
)
from app.services.build_rag import augment_prompt
from app.services.handoff import (
    HandoffError,
    add_run_event,
    build_context,
    update_run,
)
from app.services.ollama_driver import OllamaDispatchError
from app.services.ollama_driver import dispatch as dispatch_to_ollama


# Instrução anexada ao prompt de Build quando o destino é um runtime que
# produz envelope. Sem isto o modelo devolve prosa, e prosa não vira commit.
ENVELOPE_INSTRUCTIONS = """
## FORMATO OBRIGATÓRIO DA RESPOSTA

Responda APENAS com um objeto JSON, sem texto antes ou depois, no formato:

```json
{
  "summary": "resumo de uma linha do que foi feito",
  "files": [
    {"path": "caminho/relativo.py", "action": "update", "content": "conteúdo COMPLETO do arquivo"}
  ],
  "checks": ["pytest"]
}
```

Regras que fazem a resposta ser recusada se violadas:

- `path` é sempre relativo à raiz do repositório. Nunca absoluto, nunca com `..`.
- Não é permitido tocar em: `.env*`, `venv/`, `.git/`, `.github/workflows/`,
  `deploy.sh`, `scripts/*deploy*`, `alembic/versions/`.
- `content` é o conteúdo INTEIRO do arquivo depois da mudança, não um diff.
- `action` é `create`, `update` ou `delete`. Em `delete`, omita `content`.
- `checks` só aceita: `pytest`, `vitest`, `lint`, `build`. Nada mais.
- Você NÃO executa comandos. Quem aplica, testa e commita é o WorkDev.
"""


def claim_next_job(db: Session) -> AgentBuildJob | None:
    """Pega o próximo job da fila sem brigar com outro worker.

    `SKIP LOCKED` é o ponto: sem ele, dois workers serializariam na mesma linha
    e o segundo ficaria parado esperando em vez de pegar outro trabalho.
    """
    linha = db.execute(
        text(
            """
            SELECT id FROM agent_build_jobs
            WHERE state = 'queued'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
    ).first()

    if linha is None:
        return None

    return (
        db.query(AgentBuildJob)
        .filter(AgentBuildJob.id == linha[0])
        .first()
    )


def build_prompt(db: Session, run: AgentRun) -> str:
    """Prompt de Build acrescido do contrato de envelope."""
    contexto = build_context(db, run)
    return augment_prompt(contexto) + "\n" + ENVELOPE_INSTRUCTIONS


async def process_job(db: Session, job: AgentBuildJob) -> BuildOutcome | None:
    """Ciclo completo de um job: prompt → modelo → envelope → commit → estado.

    Devolve o `BuildOutcome`, ou `None` quando o job nem chegou a executar
    (run sumiu, contexto inválido, falha de despacho).
    """
    run = db.query(AgentRun).filter(AgentRun.id == job.run_id).first()

    if run is None:  # pragma: no cover - run apagada entre enfileirar e rodar
        build_jobs.fail_job(db, job, error="Execução não existe mais")
        db.commit()
        return None

    build_jobs.start_job(db, job)
    db.commit()

    try:
        prompt = build_prompt(db, run)
    except HandoffError as error:
        return _falhar(db, run, job, "build.dispatch_failed", str(error))

    # Política de egresso ANTES do envio: para runtime remoto, o texto só sai
    # com projeto não-restrito, consentimento registrado e depois de redaction.
    # Recusar aqui e não no driver é deliberado — depois que o prompt entra no
    # cliente HTTP, já saiu.
    try:
        decisao = context_egress.prepare(db, run, job.runtime_id, prompt)
    except EgressDenied as error:
        return _falhar(
            db, run, job, "build.egress_denied", error.message,
            {"code": error.code, **error.details},
        )

    if decisao.remote:
        add_run_event(
            db,
            run,
            "build.context_redacted",
            decisao.redaction_summary,
            {
                "runtime_id": job.runtime_id,
                "classification": decisao.classification,
                # Contagem por tipo, jamais o valor encontrado.
                "counts": dict(decisao.redaction.counts),
            },
        )
        db.commit()

    try:
        resultado = await dispatch_to_ollama(
            job.runtime_id,
            decisao.prompt,
            model=job.model,
        )
    except OllamaDispatchError as error:
        return _falhar(
            db, run, job, "build.dispatch_failed", error.message,
            {"code": error.code, **error.details},
        )

    outcome = execute_build(run, resultado.get("response") or "")

    if not outcome.ok:
        esgotou = (run.dispatch_attempts or 0) >= max_attempts()

        _falhar(
            db,
            run,
            job,
            "build.envelope_rejected",
            outcome.message,
            outcome_payload(outcome),
            transicionar=esgotou,
        )
        return outcome

    persist_outcome(db, run, outcome)

    evento = add_run_event(
        db,
        run,
        "build.committed",
        outcome.message,
        outcome_payload(outcome),
    )

    build_jobs.finish_job(db, job, payload=outcome_payload(outcome))

    _transicionar(db, run, outcome)
    db.commit()

    return outcome


def _transicionar(db: Session, run: AgentRun, outcome: BuildOutcome) -> None:
    """Leva a run ao estado que o resultado justifica — nunca a `completed`.

    Gate aprovado entrega ao revisor (`review`); reprovado bloqueia. Concluir é
    prerrogativa da revisão independente (ADR 004), e o worker não a usurpa.
    """
    alvo = outcome.next_status

    if run.status == alvo:
        return

    try:
        update_run(
            db,
            run,
            {
                "status": alvo,
                "summary": outcome.message,
                "message": (
                    f"Build isolado em {outcome.branch}: {outcome.message}"
                ),
            },
        )
    except HandoffError:
        # Transição recusada pelo contrato (ex.: gate exigido e ausente). O
        # commit e os eventos já estão gravados; o estado fica como está, e a
        # trilha explica o porquê. Falhar aqui apagaria trabalho válido.
        add_run_event(
            db,
            run,
            "build.transition_refused",
            f"Transição para '{alvo}' recusada pelo contrato de estados",
            {"branch": outcome.branch, "target": alvo},
        )


def _falhar(
    db: Session,
    run: AgentRun,
    job: AgentBuildJob,
    tipo: str,
    mensagem: str,
    payload: dict | None = None,
    *,
    transicionar: bool = True,
) -> None:
    add_run_event(db, run, tipo, mensagem, {"job_id": str(job.id), **(payload or {})})
    build_jobs.fail_job(db, job, error=mensagem, payload=payload or {})

    if transicionar and run.status in {"queued", "running"}:
        try:
            update_run(
                db,
                run,
                {
                    "status": "blocked",
                    "error": mensagem,
                    "message": f"Build isolado falhou: {mensagem}",
                },
            )
        except HandoffError:  # pragma: no cover - contrato recusou
            pass

    db.commit()
    return None


def worker_should_run() -> tuple[bool, str]:
    """Diz se o worker pode operar, e por quê não, quando não pode."""
    if not build_enabled():
        return False, (
            "WORKDEV_OLLAMA_BUILD_ENABLED não está ligada; o worker não "
            "consome a fila"
        )
    return True, "habilitado"
