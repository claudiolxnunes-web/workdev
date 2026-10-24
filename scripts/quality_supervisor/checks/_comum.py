"""Lógica compartilhada entre backend_errors e frontend_errors.

Um Fato por issue não resolvida. entity_id é o id da issue no GlitchTip --
estável entre execuções, é o que permite a reconciliação (novo vs.
persistente vs. agravado) funcionar sem reimplementar nada disso aqui.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config
from ...supervisor.modelo import Fato, classificar


def avaliar(project_slug: str, check_nome: str, issues: list[dict], agora: datetime) -> list[Fato]:
    rotulo = config.PROJETOS.get(project_slug, project_slug)
    fatos: list[Fato] = []
    for issue in issues:
        fatos.append(_fato(check_nome, rotulo, issue, agora))
    return fatos


def _fato(check_nome: str, rotulo_projeto: str, issue: dict[str, Any], agora: datetime) -> Fato:
    nivel = (issue.get("level") or "").lower()
    severidade = config.SEVERIDADE_POR_NIVEL.get(nivel, config.SEVERIDADE_PADRAO)

    contagem = int(issue.get("count") or 0)
    bucket, ordem = classificar(contagem, config.FAIXAS_CONTAGEM)

    titulo = issue.get("title") or issue.get("metadata", {}).get("type") or "erro sem título"
    issue_id = str(issue.get("id") or "")

    return Fato(
        check=check_nome,
        entity_type="issue",
        entity_id=issue_id,
        project_name=rotulo_projeto,
        severity=severidade,
        bucket=bucket,
        bucket_ordem=ordem,
        titulo=f"[{rotulo_projeto}] {titulo}",
        detected_at=agora.isoformat(),
        medidas={
            "ocorrencias": contagem,
            "level": nivel or None,
            "first_seen": issue.get("firstSeen"),
            "last_seen": issue.get("lastSeen"),
        },
        evidencia=(
            f"{config.GLITCHTIP_BASE_URL}/{config.GLITCHTIP_ORG}/issues/{issue_id}/"
            if issue_id
            else "",
        ),
    )
