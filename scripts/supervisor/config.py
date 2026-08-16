"""Configuração e limiares do WorkDev Supervisor.

Todo número que decide "isto merece atenção" vive aqui. Nenhum check deve
conter limiar embutido: calibrá-los contra o ruído real é a atividade da
semana de sombra (etapa E7 do plano), e isso só é barato se estiverem juntos.

CRITÉRIO DE DESLIGAMENTO (condição 3 do plano aprovado)
-------------------------------------------------------
Se, após 3 semanas de uso, o Supervisor não produzir pelo menos 1 achado novo
e útil por semana — que resulte em descoberta de risco, correção de
prioridade, prevenção de erro, economia de trabalho ou melhoria de decisão —
ele deve ser desligado ou redesenhado. Um supervisor que ninguém lê é pior
que nenhum: consome atenção e dá falsa sensação de cobertura.
"""

from __future__ import annotations

import os
from pathlib import Path


# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------

WORKDEV_DIR = Path(os.environ.get("WORKDEV_DIR", "/opt/workdev"))
ENV_FILE = Path(os.environ.get("SUPERVISOR_ENV_FILE", WORKDEV_DIR / "apps/api/.env"))
ESTADO_DIR = Path(os.environ.get("SUPERVISOR_STATE_DIR", "/var/lib/workdev-supervisor"))
ESTADO_FILE = ESTADO_DIR / "state.json"
RUNS_FILE = ESTADO_DIR / "runs.jsonl"

# Identifica a origem das conexões no pg_stat_activity.
APPLICATION_NAME = "workdev-supervisor"
TIMEOUT_CONEXAO_SEGUNDOS = 10


# --------------------------------------------------------------------------
# Domínios do banco (medidos em 2026-08-16, não presumidos)
# --------------------------------------------------------------------------

# A coluna backlog.priority é texto livre e está suja: convivem 'critical',
# 'high', 'medium', 'low' com 'Alta' e 'High'. Filtrar sem normalizar perde
# itens em silêncio.
PRIORIDADES = {
    "critical": "critical",
    "critica": "critical",
    "crítica": "critical",
    "high": "high",
    "alta": "high",
    "medium": "medium",
    "media": "medium",
    "média": "medium",
    "low": "low",
    "baixa": "low",
}

# backlog.status ∈ {todo, doing, blocked, done}
STATUS_ABERTOS = ("todo", "doing", "blocked")

# projects.status: projeto suspenso não gera achado (hoje: Ngrep BPF).
PROJETOS_IGNORADOS = ("Suspended",)

# Espelha ACTIVE_RUN_STATUSES de apps/api/app/services/handoff.py.
# Não é importado em tempo de execução porque app.database cria um engine na
# importação e depende do cwd; a paridade é garantida por teste
# (test_supervisor_checks.ParidadeComHandoffTest).
ACTIVE_RUN_STATUSES = ("queued", "running", "blocked", "review")


# --------------------------------------------------------------------------
# Limiares dos checks
# --------------------------------------------------------------------------

# critical_stalled: dias sem toque a partir dos quais a task vira achado.
# 'high' em 21 dias (e não 14) para que a carga inicial não estoure: em
# 2026-08-16 isso significa ~7 críticas + ~8 altas em vez de 29 achados.
CRITICAL_STALLED_DIAS = {"critical": 7, "high": 21}

# Uma 'high' parada tempo demais deixa de ser 'high'.
CRITICAL_STALLED_ESCALA_DIAS = 45

# plan_without_execution: plano aprovado que nunca virou execução.
PLANO_SEM_RUN_DIAS = 3

# plan_without_execution: execução ativa sem nenhum evento novo.
RUN_TRAVADO_DIAS = 2

# Faixas de bucket. O bucket — e não o valor exato — entra no fingerprint,
# para que envelhecer um dia não gere achado novo mas piorar de faixa gere.
# Formato: ((limite_superior_exclusivo | None, rótulo), ...)
FAIXAS_IDADE_TASK = ((15, "7-14"), (31, "15-30"), (61, "31-60"), (None, "60+"))
FAIXAS_IDADE_PLANO = ((8, "3-7"), (22, "8-21"), (None, "22+"))

CHECKS_ATIVOS = ("critical_stalled", "plan_without_execution")


# --------------------------------------------------------------------------
# Deduplicação e estado (etapa E2)
# --------------------------------------------------------------------------

# Um achado resolvido é reportado uma vez e fica no estado por este prazo,
# para que um problema intermitente não apareça como "novo" a cada volta.
RESOLVIDO_TTL_DIAS = 7

# Um achado persistente e grave volta ao relatório de tempos em tempos. Sem
# isso, "silêncio" e "resolvido" ficam indistinguíveis — a mesma classe de
# falha do EXCEPTION WHEN OTHERS, na camada de notificação.
REFORCO_DIAS = 14
SEVERIDADES_COM_REFORCO = ("critical", "high")

# Versão do formato de state.json. Divergiu, o estado é descartado e a
# execução recomeça semeando — nunca tenta migrar em silêncio.
VERSAO_ESTADO = 1


def normalizar_prioridade(valor: str | None) -> str | None:
    """Reduz o texto livre de backlog.priority ao domínio canônico."""
    if not valor:
        return None
    return PRIORIDADES.get(valor.strip().lower())
