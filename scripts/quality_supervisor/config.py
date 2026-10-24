"""Configuração do WorkDev Quality Supervisor.

Mesmo princípio do scripts/supervisor/config.py: todo limiar vive aqui, não
embutido em check.
"""

from __future__ import annotations

import os
from pathlib import Path


# --------------------------------------------------------------------------
# GlitchTip
# --------------------------------------------------------------------------

ENV_FILE = Path(
    os.environ.get(
        "QUALITY_SUPERVISOR_ENV_FILE", "/etc/workdev/workdev-quality-supervisor.env"
    )
)

GLITCHTIP_BASE_URL = os.environ.get("GLITCHTIP_BASE_URL", "https://erros.bpfconsult.com.br")
GLITCHTIP_ORG = os.environ.get("GLITCHTIP_ORG", "bpfconsult")
GLITCHTIP_TIMEOUT_SEGUNDOS = 15

# slug do projeto no GlitchTip -> rótulo amigável usado no relatório.
PROJETOS = {
    "workdev-api": "backend",
    "workdev-web": "frontend",
}

# --------------------------------------------------------------------------
# Estado e execução
# --------------------------------------------------------------------------

ESTADO_DIR = Path(
    os.environ.get("QUALITY_SUPERVISOR_STATE_DIR", "/var/lib/workdev-quality-supervisor")
)

APPLICATION_NAME = "workdev-quality-supervisor"

CHECKS_ATIVOS = (
    "backend_errors",
    "frontend_errors",
)

# --------------------------------------------------------------------------
# Limiares
# --------------------------------------------------------------------------

# Faixas de contagem de ocorrências. O bucket entra no fingerprint: uma issue
# que passa de faixa (ex.: 1 -> 2-5) é reportada de novo como "agravado"; só
# envelhecer no mesmo patamar não gera ruído.
FAIXAS_CONTAGEM = ((2, "1"), (6, "2-5"), (21, "6-20"), (51, "21-50"), (None, "50+"))

# GlitchTip 'level' -> severidade nossa.
SEVERIDADE_POR_NIVEL = {
    "fatal": "critical",
    "error": "high",
    "warning": "medium",
    "info": "info",
    "debug": "info",
}
SEVERIDADE_PADRAO = "high"

# --------------------------------------------------------------------------
# Relatório e entrega
# --------------------------------------------------------------------------

RELATORIO_MAX_DETALHADOS = 3
RELATORIO_SEVERIDADE_SEM_LIMITE = "critical"

# Mesmo bot/chat do supervisor de processo -- mensagens usam prefixo próprio
# para não se confundir no feed do Telegram (decisão registrada:
# simplicidade agora, canal dedicado se o volume justificar depois).
ALERTA_ENV_FILE = Path(os.environ.get("SUPERVISOR_ALERTA_ENV", "/opt/scripts/alerta.env"))
TELEGRAM_TIMEOUT_SEGUNDOS = 10
TELEGRAM_LIMITE_CARACTERES = 3800
PREFIXO_TELEGRAM = "🐛 Qualidade"

# --------------------------------------------------------------------------
# Deduplicação e estado
#
# scripts.supervisor.estado.Estado importa scripts.supervisor.config
# internamente (não a nossa) -- RESOLVIDO_TTL_DIAS, REFORCO_DIAS,
# SEVERIDADES_COM_REFORCO e VERSAO_ESTADO de lá é que valem aqui também.
# Definir esses nomes neste módulo seria enganoso: pareceria configurável
# e não seria. O que muda por processo é o ESTADO_DIR (acima), passado
# explicitamente ao construtor de Estado.
# --------------------------------------------------------------------------

METRICAS_OBRIGATORIAS = (
    "started_at",
    "finished_at",
    "duration_seconds",
    "checks_executed",
    "facts_detected",
    "new_findings",
    "persistent_findings",
    "resolved_findings",
    "status",
)

RETENCAO_EXECUCOES_DIAS = 90
