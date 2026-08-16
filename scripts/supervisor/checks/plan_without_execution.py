"""Check: planos aprovados que não viraram execução, e execuções travadas.

Dois subchecks, com fingerprints distintos porque são problemas diferentes:

  never_dispatched — plano `approved`, task ainda aberta, nenhum agent_run.
  run_stalled      — existe run em estado ativo, mas sem evento novo há dias.

O filtro `b.status <> 'done'` não é detalhe: dos 2 planos aprovados sem run
em 2026-08-16, um pertence a uma task já concluída. Sem ele o check nasce com
50% de falso positivo.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..contexto import Contexto
from ..modelo import Fato, classificar, dias_desde


NOME = "plan_without_execution"

SQL = """
SELECT pr.name              AS projeto,
       pr.id::text          AS project_id,
       b.id::text           AS backlog_id,
       b.title              AS task,
       b.status             AS task_status,
       b.priority           AS task_priority,
       ep.id::text          AS plano_id,
       ep.title             AS plano,
       ep.version           AS versao,
       ep.approved_at       AS approved_at,
       ar.id::text          AS run_id,
       ar.agent             AS agente,
       ar.status            AS run_status,
       ar.updated_at        AS run_updated_at
  FROM execution_plans ep
  JOIN backlog  b  ON b.id  = ep.backlog_id
  JOIN projects pr ON pr.id = b.project_id
  LEFT JOIN LATERAL (
       SELECT a.* FROM agent_runs a
        WHERE a.plan_id = ep.id
        ORDER BY a.created_at DESC
        LIMIT 1
  ) ar ON true
 WHERE ep.status = 'approved'
   AND b.status <> 'done'
   AND pr.status <> ALL(%(projetos_ignorados)s)
   AND (ar.id IS NULL OR ar.status = ANY(%(ativos)s))
 ORDER BY ep.approved_at ASC NULLS FIRST
"""


def coletar(contexto: Contexto) -> list[Fato]:
    linhas = contexto.workdev.consultar(
        SQL,
        {
            "projetos_ignorados": list(config.PROJETOS_IGNORADOS),
            "ativos": list(config.ACTIVE_RUN_STATUSES),
        },
    )
    return avaliar(linhas, contexto.agora)


def avaliar(linhas: list[dict], agora: datetime) -> list[Fato]:
    detectado_em = agora.isoformat()
    fatos: list[Fato] = []

    for linha in linhas:
        severidade = (
            "critical"
            if config.normalizar_prioridade(linha.get("task_priority")) == "critical"
            else "high"
        )
        comum = {
            "check": NOME,
            "project_id": linha.get("project_id"),
            "project_name": linha.get("projeto"),
            "severity": severidade,
            "detected_at": detectado_em,
        }

        if linha.get("run_id") is None:
            dias = dias_desde(linha.get("approved_at"), agora)
            if dias is None or dias < config.PLANO_SEM_RUN_DIAS:
                continue
            bucket, bucket_ordem = classificar(dias, config.FAIXAS_IDADE_PLANO)
            fatos.append(
                Fato(
                    **comum,
                    subcheck="never_dispatched",
                    entity_type="execution_plan",
                    entity_id=linha["plano_id"],
                    bucket=bucket,
                    bucket_ordem=bucket_ordem,
                    titulo=_titulo_sem_run(linha, dias),
                    medidas={
                        "dias": dias,
                        "dias_desde_aprovacao": dias,
                        "versao": linha.get("versao"),
                        "task_status": linha.get("task_status"),
                        "task_priority": linha.get("task_priority"),
                    },
                    evidencia=(
                        "SELECT id, status, version, approved_at FROM execution_plans "
                        f"WHERE id = '{linha['plano_id']}';",
                        "SELECT count(*) FROM agent_runs "
                        f"WHERE plan_id = '{linha['plano_id']}';",
                    ),
                )
            )
            continue

        dias = dias_desde(linha.get("run_updated_at"), agora)
        if dias is None or dias < config.RUN_TRAVADO_DIAS:
            continue
        bucket, bucket_ordem = classificar(dias, config.FAIXAS_IDADE_PLANO)
        fatos.append(
            Fato(
                **comum,
                subcheck="run_stalled",
                entity_type="agent_run",
                entity_id=linha["run_id"],
                bucket=bucket,
                bucket_ordem=bucket_ordem,
                titulo=_titulo_run_travado(linha, dias),
                medidas={
                    "dias": dias,
                    "dias_sem_evento": dias,
                    "run_status": linha.get("run_status"),
                    "agente": linha.get("agente"),
                    "plano_id": linha.get("plano_id"),
                    "task_status": linha.get("task_status"),
                },
                evidencia=(
                    "SELECT status, agent, started_at, updated_at FROM agent_runs "
                    f"WHERE id = '{linha['run_id']}';",
                    "SELECT event_type, created_at FROM agent_run_events "
                    f"WHERE run_id = '{linha['run_id']}' ORDER BY created_at DESC LIMIT 5;",
                ),
            )
        )

    return fatos


def _resumir(texto: str | None, limite: int = 70) -> str:
    texto = (texto or "").strip()
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."


def _titulo_sem_run(linha: dict, dias: int) -> str:
    projeto = linha.get("projeto") or "sem projeto"
    return (
        f"{projeto} — plano aprovado há {dias} dias sem nenhuma execução: "
        f"{_resumir(linha.get('plano') or linha.get('task'))}"
    )


def _titulo_run_travado(linha: dict, dias: int) -> str:
    projeto = linha.get("projeto") or "sem projeto"
    return (
        f"{projeto} — execução em '{linha.get('run_status')}' ({linha.get('agente')}) "
        f"sem evento há {dias} dias: {_resumir(linha.get('task'))}"
    )
