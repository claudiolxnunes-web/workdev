"""Varredura de segredos, aplicada a tudo que sai do Supervisor.

Postura fail-closed: na dúvida, redige. É preferível estragar um título que
por acaso parecia uma chave a publicar uma chave no Telegram ou no journald.

Nenhum check lê `.env`, imprime connection string ou inclui corpo de
documento — esta camada é a segunda linha de defesa, não a primeira.
"""

from __future__ import annotations

import re
from typing import Any

from .modelo import Fato


MARCA = "[REDIGIDO]"

# Ordem importa: padrões específicos antes dos genéricos.
PADROES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credenciais dentro de URL de conexão: preserva o esquema para leitura.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s:/@]+:[^\s@]+@"), r"\1" + MARCA + "@"),
    # Anthropic / OpenAI / OpenRouter
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), MARCA),
    (re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{10,}"), MARCA),
    (re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{10,}"), MARCA),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), MARCA),
    # Supabase (sistema novo, não-JWT)
    (re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_\-]{10,}"), MARCA),
    # JWT (anon/service_role legadas e afins)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.?[A-Za-z0-9_\-]*"), MARCA),
    # GitHub
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), MARCA),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), MARCA),
    # Token de bot do Telegram
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}"), MARCA),
    # DashScope / Moonshot e afins
    (re.compile(r"\bsk_[A-Za-z0-9]{24,}"), MARCA),
)


def redigir(texto: str) -> str:
    """Substitui qualquer segredo aparente pela marca de redação."""
    resultado = texto
    for padrao, substituto in PADROES:
        resultado = padrao.sub(substituto, resultado)
    return resultado


def redigir_valor(valor: Any) -> Any:
    """Aplica a redação recursivamente em estruturas serializáveis."""
    if isinstance(valor, str):
        return redigir(valor)
    if isinstance(valor, dict):
        return {chave: redigir_valor(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        tipo = type(valor)
        return tipo(redigir_valor(item) for item in valor)
    return valor


def redigir_fato(fato: Fato) -> Fato:
    """Devolve uma cópia do Fato com todo texto livre redigido.

    Campos de identidade (check, entity_id, bucket) não passam pela redação:
    são UUIDs e rótulos internos, e alterá-los mudaria o fingerprint.
    """
    from dataclasses import replace

    return replace(
        fato,
        titulo=redigir(fato.titulo),
        medidas=redigir_valor(dict(fato.medidas)),
        evidencia=tuple(redigir(item) for item in fato.evidencia),
        project_name=redigir(fato.project_name) if fato.project_name else None,
    )


def contem_segredo(texto: str) -> bool:
    """Usado em teste e em asserção defensiva antes da entrega."""
    return any(padrao.search(texto) for padrao, _ in PADROES)
