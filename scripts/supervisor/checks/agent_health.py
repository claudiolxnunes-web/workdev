"""Check: estado dos agentes CLI, segundo a política vigente.

Este check **consome** o `status.json` de `scripts/agents_healthcheck.py`. Não
abre tmux, não captura painel, não reinicia sessão e não reclassifica nada.

A política importa tanto quanto o dado: Kimi e Qwen offline é decisão
registrada (ADR de 2026-08-15 e commit `0d63fee`), não incidente. Um check que
lesse o `status.json` sem a política reportaria dois falsos positivos por dia,
todos os dias.

O subcheck mais valioso é `supervisao_parada`: se o timer do healthcheck
morrer, o `status.json` congela e o silêncio fica indistinguível de "tudo
bem". Hoje nada mais no sistema detecta isso.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..contexto import Contexto
from ..modelo import Fato, classificar, como_utc
from ..readers import agentes as leitor_agentes


NOME = "agent_health"

SQL_FILA = """
SELECT count(*)        AS ativos,
       min(updated_at) AS mais_antigo
  FROM agent_runs
 WHERE status = ANY(%(ativos)s)
"""

FAIXAS_ATRASO = ((60, "20-59min"), (360, "1-6h"), (1441, "6-24h"), (None, "24h+"))


def coletar(contexto: Contexto) -> list[Fato]:
    estado = leitor_agentes.ler_estado(contexto.estado_agentes)
    fila = contexto.workdev.consultar(
        SQL_FILA, {"ativos": list(config.FILA_STATUS)}
    )
    return avaliar(estado, fila[0] if fila else {}, contexto.agora)


def avaliar(estado: dict, fila: dict, agora: datetime) -> list[Fato]:
    fatos: list[Fato] = []
    agentes = estado.get("agents") or {}

    fatos += _supervisao_parada(estado, agora)
    for nome in sorted(agentes):
        dados = agentes[nome] or {}
        fatos += _agente_fora(nome, dados, agora)
        fatos += _credencial_recusada(nome, dados, agora)
    fatos += _fila_parada(agentes, fila, agora)
    return fatos


def _fato(subcheck, entidade, severidade, bucket, ordem, titulo, agora, medidas, evidencia):
    return Fato(
        check=NOME,
        subcheck=subcheck,
        entity_type="agente",
        entity_id=entidade,
        project_name="WorkDev Core",
        severity=severidade,
        bucket=bucket,
        bucket_ordem=ordem,
        titulo=titulo,
        detected_at=agora.isoformat(),
        medidas=medidas,
        evidencia=evidencia,
    )


def _supervisao_parada(estado: dict, agora: datetime) -> list[Fato]:
    atualizado = estado.get("updated_at")
    momento = None
    if atualizado:
        try:
            momento = como_utc(datetime.fromisoformat(atualizado))
        except (TypeError, ValueError):
            momento = None
    if momento is None:
        minutos = None
    else:
        minutos = int((como_utc(agora) - momento).total_seconds() // 60)

    if minutos is not None and minutos < config.IDADE_MAXIMA_ESTADO_MINUTOS:
        return []

    bucket, ordem = classificar(minutos if minutos is not None else 10**6, FAIXAS_ATRASO)
    descricao = (
        f"há {minutos} min" if minutos is not None else "com carimbo de tempo ilegível"
    )
    return [
        _fato(
            "supervisao_parada",
            "agents-healthcheck",
            "critical",
            bucket,
            ordem,
            f"o healthcheck dos agentes não atualiza o estado {descricao} — "
            "o silêncio dele não significa que os agentes estão bem",
            agora,
            {"minutos_sem_atualizar": minutos, "updated_at": atualizado},
            (
                "systemctl list-timers workdev-agents-health.timer",
                "journalctl -u workdev-agents-health -n 30",
                f"ls -l {config.AGENTS_STATUS_FILE}",
            ),
        )
    ]


def _agente_fora(nome: str, dados: dict, agora: datetime) -> list[Fato]:
    if nome not in config.AGENTES_SEMPRE_ATIVOS:
        return []  # standby é política, não incidente
    situacao = dados.get("status")
    if situacao not in ("offline", "blocked"):
        return []
    motivo = dados.get("reason")
    return [
        _fato(
            "agente_fora",
            nome,
            "critical",
            situacao,
            0,
            f"agente {nome} (always-on) está {situacao}"
            + (f" por {motivo}" if motivo else ""),
            agora,
            {"status": situacao, "reason": motivo, "process": dados.get("process")},
            (
                f"tmux has-session -t {dados.get('session', nome)}",
                f"ls -l {config.AGENTS_STATUS_FILE}",
            ),
        )
    ]


def _credencial_recusada(nome: str, dados: dict, agora: datetime) -> list[Fato]:
    motivo = dados.get("reason")
    if motivo not in config.MOTIVOS_DE_CREDENCIAL:
        return []
    if nome in config.AGENTES_SEMPRE_ATIVOS and dados.get("status") in ("offline", "blocked"):
        return []  # já reportado por agente_fora, com mais contexto
    return [
        _fato(
            "credencial_recusada",
            nome,
            "high",
            motivo,
            0,
            f"agente {nome} com credencial recusada ({motivo}) — chave inválida não é "
            "decisão de standby",
            agora,
            {"status": dados.get("status"), "reason": motivo},
            (f"journalctl -t agents-healthcheck -n 30 | grep {nome}",),
        )
    ]


def _fila_parada(agentes: dict, fila: dict, agora: datetime) -> list[Fato]:
    ativos = int(fila.get("ativos") or 0)
    if not ativos:
        return []
    mais_antigo = como_utc(fila.get("mais_antigo"))
    if mais_antigo is None:
        return []
    horas = (como_utc(agora) - mais_antigo).total_seconds() / 3600
    if horas < config.FILA_PARADA_HORAS:
        return []

    ociosos = sorted(
        nome
        for nome in config.AGENTES_SEMPRE_ATIVOS
        if (agentes.get(nome) or {}).get("status") == "idle"
    )
    if not ociosos:
        return []

    bucket, ordem = classificar(int(horas * 60), FAIXAS_ATRASO)
    return [
        _fato(
            "fila_parada",
            "fila",
            "high",
            bucket,
            ordem,
            f"{ativos} execução(ões) na fila há {int(horas)}h enquanto "
            f"{', '.join(ociosos)} está(ão) ocioso(s)",
            agora,
            {
                "runs_ativos": ativos,
                "horas_parado": round(horas, 1),
                "agentes_ociosos": ociosos,
            },
            (
                "SELECT id, agent, status, updated_at FROM agent_runs "
                "WHERE status = 'queued';",
            ),
        )
    ]
