"""Redaction do contexto antes de sair da VPS (plano de correção, achado 7).

O prompt de Build carrega ADRs, knowledge e decisions — texto que o operador
escreveu ao longo de meses e que perfeitamente pode conter uma chave colada num
troubleshooting. Enquanto o destino era `local-code` (loopback), isso era
irrelevante. Com `gpu-hostinger`/`gpu-runpod` o mesmo texto atravessa a internet
para infraestrutura de terceiro.

Duas decisões de projeto:

1. **Fail-safe, não fail-clever.** Na dúvida, redige. Um falso positivo estraga
   um trecho de contexto; um falso negativo vaza credencial.
2. **O que se registra é a contagem, nunca o achado.** Logar "encontrei
   `sk-abc...`" recria o vazamento no log — que foi o motivo de existir a
   preferência global de redigir antes de imprimir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def redacted(self) -> bool:
        return self.total > 0


# Ordem importa: padrões mais específicos primeiro, senão um genérico consome o
# texto e o rótulo do achado fica errado.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # JWT (as anon/service_role legadas do Supabase têm esta cara)
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
    ),
    # Chaves novas do Supabase
    ("supabase_secret", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{8,}")),
    ("supabase_publishable", re.compile(r"\bsb_publishable_[A-Za-z0-9_-]{8,}")),
    # GitHub
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    ),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    # OpenAI / Anthropic / genéricos com prefixo
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("api_key_prefixed", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    # AWS
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # URL com credencial embutida (postgres://user:senha@host, https://u:p@h)
    (
        "url_with_credentials",
        re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s]+"),
    ),
    # Chave privada em bloco PEM
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    # Atribuição explícita de segredo: SENHA=..., API_KEY: "...", token = '...'
    (
        "assigned_secret",
        re.compile(
            r"\b([A-Z0-9_]*(?:SECRET|PASSWORD|SENHA|TOKEN|APIKEY|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
            r"\s*[:=]\s*[\"']?([^\s\"'\n]{6,})[\"']?",
            re.IGNORECASE,
        ),
    ),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
)


def _marcador(tipo: str) -> str:
    return f"[REDACTED:{tipo}]"


def redact(texto: str) -> RedactionResult:
    """Remove segredos reconhecíveis, devolvendo o texto e a contagem por tipo."""
    if not texto:
        return RedactionResult(text=texto or "", counts={})

    resultado = texto
    contagem: dict[str, int] = {}

    for tipo, padrao in PATTERNS:
        if tipo == "assigned_secret":
            # Preserva o NOME da variável e substitui só o valor: perder o nome
            # tornaria o contexto inútil ("配置 [REDACTED] = [REDACTED]").
            def _troca(match: re.Match) -> str:
                return f"{match.group(1)}={_marcador('assigned_secret')}"

            resultado, n = padrao.subn(_troca, resultado)
        else:
            resultado, n = padrao.subn(_marcador(tipo), resultado)

        if n:
            contagem[tipo] = contagem.get(tipo, 0) + n

    return RedactionResult(text=resultado, counts=contagem)


def summary(result: RedactionResult) -> str:
    """Frase curta para evento/log. Nunca contém o valor redigido."""
    if not result.redacted:
        return "nenhum segredo reconhecido no contexto"

    partes = ", ".join(
        f"{quantidade}× {tipo}"
        for tipo, quantidade in sorted(result.counts.items())
    )
    return f"{result.total} ocorrência(s) redigida(s): {partes}"
