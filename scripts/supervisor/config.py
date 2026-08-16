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

CHECKS_ATIVOS = (
    "critical_stalled",
    "plan_without_execution",
    "deploy_drift",
    "knowledge_drift",
    "agent_health",
)


# --------------------------------------------------------------------------
# deploy_drift
# --------------------------------------------------------------------------

BRANCH_TRABALHO = "develop"
BRANCH_PRODUCAO = "main"
REMOTO = "origin"

# Commits que só existem nesta VPS: risco de perda, não de qualidade. Só
# vira achado depois de passar da janela — commitar e empurrar no mesmo dia
# é fluxo normal.
COMMITS_NAO_ENVIADOS_DIAS = 2

UNIT_API = "workdev-api"
PORTA_API = 8000
DIRETORIO_MIGRATIONS = "apps/api/alembic/versions"

# Onde o build e o serviço leem o código. `deploy.sh` builda a partir da
# árvore de trabalho, não de um commit — por isso arquivo modificado e não
# commitado já está em produção.
CAMINHO_BUILD = "apps/web/dist/index.html"
FONTES_FRONTEND = "apps/web/src"
FONTES_BACKEND = "apps/api/app"

FAIXAS_CONTAGEM = ((2, "1"), (6, "2-5"), (21, "6-20"), (51, "21-50"), (None, "50+"))


# --------------------------------------------------------------------------
# knowledge_drift
# --------------------------------------------------------------------------

RAG_ENV_FILE = Path(os.environ.get("SUPERVISOR_RAG_ENV", "/opt/rag-postgres/.env"))
RAG_HOST = os.environ.get("SUPERVISOR_RAG_HOST", "127.0.0.1")
RAG_PORTA = int(os.environ.get("SUPERVISOR_RAG_PORTA", "5433"))
RAG_FONTE = "workdev"

# Espelha ALVOS de /opt/rag-postgres/ingestor.py: (subcaminho, tipo, é_diretório).
# Cópia com detector de divergência, como ACTIVE_RUN_STATUSES — o ingestor
# não é importável daqui sem arrastar dependências e credenciais.
RAG_RAIZES = (
    ("docs/adr", "adr", True),
    ("decisions", "decision", True),
    ("backlog.md", "backlog", False),
    ("knowledge", "knowledge", True),
)

ARQUIVO_BACKLOG_EXPORTADO = "backlog.md"

# Tabelas com endpoint ativo e nenhuma linha: estrutura que compete com
# outra sem ser usada. Achado informativo, reportado uma vez.
TABELAS_VIGIADAS_VAZIAS = ("decisions", "rfcs")

FAIXAS_REGISTROS = ((6, "1-5"), (21, "6-20"), (101, "21-100"), (None, "100+"))
BACKLOG_MD_TOLERANCIA_ITENS = 5
BACKLOG_MD_TOLERANCIA_DIAS = 7


# --------------------------------------------------------------------------
# agent_health
# --------------------------------------------------------------------------

AGENTS_STATUS_FILE = Path(
    os.environ.get("SUPERVISOR_AGENTS_STATUS", "/var/lib/agents-healthcheck/status.json")
)

# Política vigente. Kimi e Qwen offline são decisão, não incidente.
AGENTES_SEMPRE_ATIVOS = ("claude", "codex")
AGENTES_STANDBY_PERMITIDO = ("kimi", "qwen")

# O healthcheck roda a cada 5 min. Estado mais velho que isto significa que
# a supervisão parou — hoje o único sinal disso no sistema inteiro.
IDADE_MAXIMA_ESTADO_MINUTOS = 20

# Motivos que são problema mesmo em agente de standby: chave recusada não é
# decisão de política.
MOTIVOS_DE_CREDENCIAL = ("authentication", "billing", "api_key")

# Agente sempre-ativo ocioso enquanto existe fila parada.
#
# Só `queued` conta como fila: é o estado de quem espera alguém pegar. Um run
# `blocked` espera intervenção humana e já é reportado por
# plan_without_execution.run_stalled; `running` sem evento também. Incluir os
# três faria o mesmo problema aparecer em dois checks — verificado contra os
# dois runs `blocked` do codex de 05-06/08.
FILA_STATUS = ("queued",)
FILA_PARADA_HORAS = 6


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
