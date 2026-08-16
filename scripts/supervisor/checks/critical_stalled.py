"""Check: tarefas críticas ou de alta prioridade paradas tempo demais.

Fonte: backlog ⨝ projects, com backlog_subtasks, execution_plans e agent_runs
para contexto. O SQL faz o filtro grosso (a menor janela configurada); o
limiar por prioridade e a severidade são decididos em Python, onde dá para
testar sem banco.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config
from ..modelo import Fato, classificar, dias_desde


NOME = "critical_stalled"

SQL = """
SELECT p.name                    AS projeto,
       p.id::text                AS project_id,
       b.id::text                AS backlog_id,
       b.title                   AS titulo,
       b.priority                AS prioridade,
       b.status                  AS status,
       b.owner                   AS owner,
       b.updated_at              AS updated_at,
       (SELECT count(*) FROM backlog_subtasks s
         WHERE s.backlog_id = b.id AND s.status <> 'done')      AS subtasks_abertas,
       (SELECT count(*) FROM execution_plans ep
         WHERE ep.backlog_id = b.id AND ep.status = 'approved') AS planos_aprovados,
       (SELECT max(ar.updated_at) FROM agent_runs ar
         WHERE ar.backlog_id = b.id)                            AS ultima_execucao
  FROM backlog b
  JOIN projects p ON p.id = b.project_id
 WHERE b.status = ANY(%(status_abertos)s)
   AND p.status <> ALL(%(projetos_ignorados)s)
   -- backlog.updated_at é `timestamp without time zone`; o servidor roda em
   -- UTC, mas a conversão fica explícita para não depender disso.
   AND b.updated_at < (now() AT TIME ZONE 'UTC')
                      - (%(limite_dias)s::text || ' days')::interval
 ORDER BY b.updated_at ASC
"""


def coletar(leitor: Any, agora: datetime) -> list[Fato]:
    linhas = leitor.consultar(
        SQL,
        {
            "status_abertos": list(config.STATUS_ABERTOS),
            "projetos_ignorados": list(config.PROJETOS_IGNORADOS),
            "limite_dias": min(config.CRITICAL_STALLED_DIAS.values()),
        },
    )
    return avaliar(linhas, agora)


def avaliar(linhas: list[dict], agora: datetime) -> list[Fato]:
    detectado_em = agora.isoformat()
    fatos: list[Fato] = []

    for linha in linhas:
        prioridade = config.normalizar_prioridade(linha.get("prioridade"))
        limite = config.CRITICAL_STALLED_DIAS.get(prioridade or "")
        if limite is None:
            continue  # medium/low/desconhecida não são vigiadas por este check

        dias = dias_desde(linha.get("updated_at"), agora)
        if dias is None or dias < limite:
            continue

        severidade = (
            "critical"
            if prioridade == "critical" or dias >= config.CRITICAL_STALLED_ESCALA_DIAS
            else "high"
        )
        bucket, bucket_ordem = classificar(dias, config.FAIXAS_IDADE_TASK)

        fatos.append(
            Fato(
                check=NOME,
                entity_type="backlog",
                entity_id=linha["backlog_id"],
                project_id=linha.get("project_id"),
                project_name=linha.get("projeto"),
                severity=severidade,
                bucket=bucket,
                bucket_ordem=bucket_ordem,
                titulo=_titulo(linha, prioridade, dias),
                detected_at=detectado_em,
                medidas={
                    "dias_parado": dias,
                    "prioridade": prioridade,
                    "prioridade_original": linha.get("prioridade"),
                    "status": linha.get("status"),
                    "owner": linha.get("owner"),
                    "subtasks_abertas": int(linha.get("subtasks_abertas") or 0),
                    "planos_aprovados": int(linha.get("planos_aprovados") or 0),
                    "dias_desde_execucao": dias_desde(linha.get("ultima_execucao"), agora),
                },
                evidencia=(
                    "SELECT title, status, priority, owner, updated_at "
                    f"FROM backlog WHERE id = '{linha['backlog_id']}';",
                    "SELECT status, agent, updated_at FROM agent_runs "
                    f"WHERE backlog_id = '{linha['backlog_id']}' ORDER BY created_at DESC;",
                ),
            )
        )

    return fatos


def _titulo(linha: dict, prioridade: str, dias: int) -> str:
    titulo = (linha.get("titulo") or "").strip()
    if len(titulo) > 80:
        titulo = titulo[:77] + "..."
    projeto = linha.get("projeto") or "sem projeto"
    return f"{projeto} — task {prioridade} parada há {dias} dias: {titulo}"
