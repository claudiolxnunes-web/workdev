"""Check: consumo de tokens dos agentes e limites atingidos.

Motivação (2026-09-16): houve uma janela em que a assinatura ficou inativa, o
Claude Code pediu login numa execução e a cobrança podia estar saindo por
token sem que nada na UI mostrasse a diferença — o agente roda igual, só que
cada turno passa a custar dinheiro em vez de consumir assinatura.

**Limite desta fonte:** `oauthAccount` em `~/.claude.json` é um cache com data
em `profileFetchedAt`. Em 2026-09-16 o cache era de 2026-09-14 e dizia
`prepaid`/`seatTier: None`, enquanto a conta já era Pro ativa — a modalidade
real vem de `/status` no cliente, não deste arquivo. Por isso o subcheck
`modalidade` só afirma cobrança por token com cache dentro da validade
(`TOKEN_USAGE_CACHE_VALIDO_HORAS`); fora dela, pede reconferência.

Três subchecks, com fingerprints distintos porque exigem ações diferentes:

  modalidade      — indício de cobrança por token, com a ressalva de cache
                    acima. Não é erro, é um estado que o Cláudio quer ver.
  volume_diario   — tokens de escrita do dia acima do teto.
  limite_atingido — o cliente registrou recusa por limite nas últimas 24h.

Por que a métrica principal é "tokens de escrita" (`input + output +
cache_creation`) e não o total: `cache_read` domina o volume por uma ordem de
grandeza (52M contra 5M em 2026-09-16) e é a parte mais barata. Somar tudo
num número só faria o teto disparar por causa de cache barato e esconder o
que realmente pesa. `cache_read` vai em `medidas`, como informação.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .. import config
from ..contexto import Contexto
from ..modelo import Fato, classificar


NOME = "token_usage"

# Chaves de `usage` que somamos. `cache_read_input_tokens` é lido mas fica
# fora do total de escrita (ver docstring).
CAMPOS_ESCRITA = ("input_tokens", "output_tokens", "cache_creation_input_tokens")
CAMPO_CACHE_LIDO = "cache_read_input_tokens"

# Marcas de recusa por limite. Ficam propositalmente restritas: um padrão
# amplo como "429" casa com `total_tokens_reminder` e com qualquer log que
# cite o número, e o check nasceria com falso positivo garantido.
MARCAS_LIMITE = (
    "rate_limit_error",
    "usage limit reached",
    "you've reached your usage limit",
    "quota exceeded",
    "credit balance is too low",
)


def coletar(contexto: Contexto) -> list[Fato]:
    agora = contexto.agora
    transcripts = _ler_transcripts(config.TOKEN_USAGE_TRANSCRIPTS_DIR, agora)
    conta = _ler_conta(config.TOKEN_USAGE_CONTA_FILE)
    return avaliar({"uso": transcripts["uso"], "limites": transcripts["limites"],
                    "conta": conta}, agora)


def avaliar(dados: dict[str, Any], agora: datetime) -> list[Fato]:
    fatos: list[Fato] = []
    fatos.extend(_modalidade(dados.get("conta") or {}, agora))
    fatos.extend(_volume_diario(dados.get("uso") or {}, agora))
    fatos.extend(_limite_atingido(dados.get("limites") or [], agora))
    return fatos


# --------------------------------------------------------------------------
# subcheck: modalidade de cobrança
# --------------------------------------------------------------------------

def _modalidade(conta: dict[str, Any], agora: datetime) -> list[Fato]:
    """Avisa sobre cobrança por token — mas nunca em cima de cache velho.

    `oauthAccount` é um **cache** do perfil, com a data em `profileFetchedAt`
    (epoch em milissegundos). Em 2026-09-16 esse cache era de 2026-09-14,
    buscado justamente na janela em que a assinatura estava inativa: afirmar
    `prepaid` a partir dele produziria um alerta falso sobre uma conta Pro
    ativa. Foi o que aconteceu na primeira versão deste check.

    Com cache dentro da validade, o achado é `high` (ação: relogar/reativar).
    Fora da validade, vira `info` pedindo reconferência via `/status` — o
    supervisor não tem como saber a modalidade atual sozinho.
    """
    if not conta:
        return []
    billing = conta.get("billingType")
    assento = conta.get("seatTier")
    if billing not in config.TOKEN_USAGE_BILLING_PAGO and assento:
        return []

    idade_horas = _idade_do_cache_horas(conta.get("profileFetchedAt"), agora)
    obsoleto = idade_horas is None or idade_horas > config.TOKEN_USAGE_CACHE_VALIDO_HORAS
    if obsoleto:
        severidade = "info"
        idade_txt = f"{idade_horas:.0f}h" if idade_horas is not None else "sem data"
        titulo = (
            f"Modalidade de cobrança não confirmada: cache do perfil tem {idade_txt} "
            f"(diz billingType={billing!r}). Conferir com /status no Claude Code"
        )
    else:
        severidade = "high"
        titulo = (
            f"Agentes cobrando por token (billingType={billing!r}, seatTier={assento!r}) "
            "— a intenção registrada é usar a assinatura"
        )
    return [Fato(
        check=NOME, subcheck="modalidade",
        entity_type="conta", entity_id=str(conta.get("accountUuid") or "conta-claude"),
        severity=severidade, bucket=str(billing or "desconhecido"), bucket_ordem=0,
        titulo=titulo, detected_at=agora.isoformat(),
        medidas={"billing_type": billing, "seat_tier": assento,
                 "extra_usage": conta.get("hasExtraUsageEnabled"),
                 "cache_horas": None if idade_horas is None else round(idade_horas, 1)},
        evidencia=(str(config.TOKEN_USAGE_CONTA_FILE),),
    )]


def _idade_do_cache_horas(buscado_em: Any, agora: datetime) -> float | None:
    """`profileFetchedAt` vem em epoch de milissegundos, não ISO."""
    if not isinstance(buscado_em, (int, float)) or buscado_em <= 0:
        return None
    try:
        quando = datetime.fromtimestamp(buscado_em / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return (agora - quando).total_seconds() / 3600


# --------------------------------------------------------------------------
# subcheck: volume diário
# --------------------------------------------------------------------------

def _volume_diario(uso: dict[str, dict[str, int]], agora: datetime) -> list[Fato]:
    dia = agora.date().isoformat()
    do_dia = uso.get(dia)
    if not do_dia:
        return []
    escrita = sum(do_dia.get(campo, 0) for campo in CAMPOS_ESCRITA)
    if escrita < config.TOKEN_USAGE_PISO_DIARIO:
        return []
    rotulo, ordem = classificar(escrita, config.TOKEN_USAGE_TETO_DIARIO)
    severidade = "critical" if ordem >= len(config.TOKEN_USAGE_TETO_DIARIO) - 1 else "high"
    return [Fato(
        check=NOME, subcheck="volume_diario",
        entity_type="dia", entity_id=dia,
        severity=severidade, bucket=rotulo, bucket_ordem=ordem,
        titulo=f"Consumo de {escrita:,} tokens de escrita hoje ({rotulo})".replace(",", "."),
        detected_at=agora.isoformat(),
        medidas={
            "tokens_escrita": escrita,
            "input": do_dia.get("input_tokens", 0),
            "output": do_dia.get("output_tokens", 0),
            "cache_write": do_dia.get("cache_creation_input_tokens", 0),
            "cache_read": do_dia.get(CAMPO_CACHE_LIDO, 0),
        },
        evidencia=(f"{dia}: {escrita} tokens de escrita",),
    )]


# --------------------------------------------------------------------------
# subcheck: limite atingido
# --------------------------------------------------------------------------

def _limite_atingido(limites: list[dict[str, Any]], agora: datetime) -> list[Fato]:
    recentes = [item for item in limites
                if _dentro_da_janela(item.get("timestamp"), agora)]
    if not recentes:
        return []
    marcas = sorted({item["marca"] for item in recentes})
    return [Fato(
        check=NOME, subcheck="limite_atingido",
        entity_type="janela", entity_id=agora.date().isoformat(),
        severity="critical", bucket=marcas[0], bucket_ordem=0,
        titulo=f"{len(recentes)} recusa(s) por limite nas últimas 24h ({', '.join(marcas)})",
        detected_at=agora.isoformat(),
        medidas={"ocorrencias": len(recentes), "marcas": marcas},
        evidencia=tuple(str(item.get("arquivo", "")) for item in recentes[:3]),
    )]


def _dentro_da_janela(timestamp: str | None, agora: datetime) -> bool:
    if not timestamp:
        return False
    try:
        momento = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return momento >= agora - timedelta(hours=24)


# --------------------------------------------------------------------------
# leitura das fontes (só `coletar` conhece I/O)
# --------------------------------------------------------------------------

def _ler_transcripts(diretorio: Path, agora: datetime) -> dict[str, Any]:
    uso: dict[str, dict[str, int]] = {}
    limites: list[dict[str, Any]] = []
    corte = agora - timedelta(days=config.TOKEN_USAGE_DIAS)
    for arquivo in _arquivos_recentes(diretorio, corte):
        try:
            linhas = arquivo.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for linha in linhas:
            evento = _json_ou_nada(linha)
            if evento is None:
                continue
            _somar_uso(evento, uso)
            marca = _marca_de_limite(evento)
            if marca:
                limites.append({"timestamp": evento.get("timestamp"),
                                "marca": marca, "arquivo": arquivo.name})
    return {"uso": uso, "limites": limites}


def _arquivos_recentes(diretorio: Path, corte: datetime) -> Iterable[Path]:
    if not diretorio.exists():
        return []
    recentes = []
    for arquivo in diretorio.glob("*/*.jsonl"):
        try:
            modificado = datetime.fromtimestamp(arquivo.stat().st_mtime, tz=corte.tzinfo)
        except OSError:
            continue
        if modificado >= corte:
            recentes.append(arquivo)
    return recentes


def _json_ou_nada(linha: str) -> dict[str, Any] | None:
    linha = linha.strip()
    if not linha.startswith("{"):
        return None
    try:
        evento = json.loads(linha)
    except (ValueError, TypeError):
        return None
    return evento if isinstance(evento, dict) else None


def _somar_uso(evento: dict[str, Any], uso: dict[str, dict[str, int]]) -> None:
    dia = str(evento.get("timestamp") or "")[:10]
    mensagem = evento.get("message")
    if not dia or not isinstance(mensagem, dict):
        return
    usage = mensagem.get("usage")
    if not isinstance(usage, dict):
        return
    do_dia = uso.setdefault(dia, {})
    for campo in (*CAMPOS_ESCRITA, CAMPO_CACHE_LIDO):
        valor = usage.get(campo)
        if isinstance(valor, int):
            do_dia[campo] = do_dia.get(campo, 0) + valor


def _marca_de_limite(evento: dict[str, Any]) -> str | None:
    """Procura recusa por limite apenas no texto da mensagem.

    Varrer o evento inteiro casaria com o `total_tokens_reminder` que o
    próprio cliente injeta — foi o que produziu 33 falsos positivos quando
    esta fonte foi medida pela primeira vez.
    """
    mensagem = evento.get("message")
    if not isinstance(mensagem, dict):
        return None
    conteudo = mensagem.get("content")
    if isinstance(conteudo, list):
        texto = " ".join(
            bloco.get("text", "") for bloco in conteudo
            if isinstance(bloco, dict) and bloco.get("type") == "text"
        )
    elif isinstance(conteudo, str):
        texto = conteudo
    else:
        return None
    baixo = texto.lower()
    for marca in MARCAS_LIMITE:
        if marca in baixo:
            return marca
    return None


def _ler_conta(caminho: Path) -> dict[str, Any]:
    """Lê só os metadados de plano. Nenhum campo de credencial é tocado."""
    try:
        dados = json.loads(caminho.read_text())
    except (OSError, ValueError):
        return {}
    conta = dados.get("oauthAccount")
    if not isinstance(conta, dict):
        return {}
    return {chave: conta.get(chave) for chave in
            ("accountUuid", "billingType", "seatTier", "hasExtraUsageEnabled",
             "profileFetchedAt")}
