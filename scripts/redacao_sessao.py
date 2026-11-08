"""Redação de segredos para arquivos de sessão dos agentes CLI.

Por que um módulo próprio, e não o `context_redaction` da API
------------------------------------------------------------
O `context_redaction` é feito para o *contexto que sai da VPS* (plano de
correção do achado 7): ali, redigir demais custa quase nada, porque o
contexto é reescrito a cada prompt. Num arquivo de sessão o custo é o
oposto — o arquivo é o **histórico** do trabalho, e redigir `MAX_TOKENS`
ou `API_KEY_ENV` degrada o registro sem proteger nada.

Medido em 2026-11-08: o `context_redaction` marcava 18.670 ocorrências nos
arquivos de sessão, das quais 16.219 eram falsos positivos — `email` (8.117),
`assigned_secret` (8.102,Mostly `MAX_TOKENS`, `INPUT_TOKENS`,
`TOKENS_ESTIMATE`) e `url_with_credentials` (2.330, quase todas URLs do
próprio WorkDev).

A distinção que este módulo faz:

- **Só valor que tem cara de credencial.** Um segredo é reconhecido pelo
  *formato* do valor (prefixo conhecido, entropia, JWT, bloco PEM), não pelo
  nome da variável que o contém. `TOKEN=ghp_...` é segredo; `MAX_TOKENS=8192`
  não é.
- **Atribuição só quando o valor também é suspeito.** O nome ajuda a
  identificar, mas não basta: `API_KEY=<hash de 32 hex>` conta; `API_KEY_ENV=
  workdev-agents` não.
- **Email não é redigido.** Não é credencial, e apagá-lo quebra a trilha de
  auditoria.

O que redige: token de API com prefixo conhecido, chave de bot, JWT, chave
privada em bloco PEM, token do GitHub (todas as variantes), chave de acesso
AWS, URL com credencial embutida, e atribuição cujo valor tem cara de
segredo.

Postura: fail-safe na dúvida quanto ao *formato*; fail-closed quanto ao
*nome* (só redige por nome quando o valor também é suspeito).
"""
from __future__ import annotations

import math
import re
from collections import Counter

MARCA = "[REDIGIDO]"

# ---------------------------------------------------------------- por formato

# Valores que tem cara de credencial pelo prefixo. Formatos publicos e
# reconheciveis — nao dependem do nome da variavel.
FORMATOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Anthropic
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    # OpenAI (sk-...), OpenRouter (sk-or-v1-...), e o resto com prefixo sk_
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("openrouter_key", re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{20,}")),
    # GitHub: PAT fino, e as variantes do OAuth/app
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    # Supabase
    ("supabase_secret", re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{16,}")),
    # AWS
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # Token de bot do Telegram
    ("telegram_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}")),
    # JWT (anon/service_role do Supabase e afins). O ultimo segmento (assinatura)
    # pode ser curto em JWT de teste, entao o minimo e 4 — o que ainda diferencia
    # de um dominio com ponto.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}")),
    # Chave privada em bloco PEM
    ("private_key", re.compile(
        r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----",
        re.DOTALL)),
    # Token de servico do Google
    ("google_token", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # Slack
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
)

# URL com credencial embutida: esquema://usuario:senha@host
URL_COM_CREDENCIAL = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://)([^\s/:@]+):([^\s/@]+)(@[^\s]+)")

# Senha curta na URL e placeholder de exemplo (`postgresql://u:p@host`), nao
# credencial. Medido em 2026-11-08: 372 das 445 URLs casadas tinham senha de
# 1 caractere — todas de documentacao. A senha real tem 40+ (o formato do
# WorkDev).
SENHA_MINIMA_URL = 12

# ---------------------------------------------------------------- por atribuicao

# Nomes que sugerem segredo. So conta se o VALOR tambem for suspeito.
NOMES_SEGREDO = re.compile(
    r"(?:^|_)(?:SECRET|SECRETS|PASSWORD|PASSWD|SENHA|PASS|TOKEN|APIKEY|API_KEY"
    r"|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL|KEY)(?:$|_)", re.IGNORECASE)

# Valor que parece credencial: muito longo, ou hexadecimal de tamanho de chave.
VALOR_LONGO = re.compile(r"^[^\s]{16,}$")
VALOR_HEX = re.compile(r"^[0-9a-fA-F]{32,}$")
VALOR_BASE64_LONGO = re.compile(r"^[A-Za-z0-9+/=_\-]{24,}$")

# Valor que claramente NAO e segredo, mesmo com nome suspeito.
# So valores curtos/estruturais: um hex de 32 chars ou base64 de 24+ NAO
# entram aqui — sao justamente o formato de uma chave.
VALOR_NAO_SEGREDO = re.compile(
    r"^(?:\d+|true|false|null|none|yes|no|"
    r"\$\{[^}]+\}|<[^>]+>|\{\{[^}]+\}\}|"
    r"[a-z0-9_\-]{1,15})$", re.IGNORECASE)

# Caminho de arquivo ou pasta: `configuracao.producao.py`,
# `/etc/workdev/workdev-api.env`. Medido em 2026-11-08: das atribuicoes
# apontadas, as de 28 chars com ponto eram nome de arquivo, nao chave.
EH_CAMINHO = re.compile(r"[/\\]|[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,6}$")

# Identificador, nao credencial: `WORKDEV_AGENT_API_KEY`, `configKey`.
# Medido em 2026-11-08: as atribuicoes que restavam com 28 chars eram nomes
# de variavel em SCREAMING_CASE — o valor apontado era outro nome, nao a chave.
EH_IDENTIFICADOR = re.compile(
    r"^(?:[A-Z][A-Z0-9_]{10,}|[a-z][A-Za-z0-9]{10,})$")


def _valor_suspeito(valor: str) -> bool:
    """O valor tem cara de credencial?"""
    valor = valor.strip().strip('"').strip("'")
    if not valor or VALOR_NAO_SEGREDO.match(valor):
        return False
    if EH_CAMINHO.search(valor):
        return False  # nome de arquivo ou caminho, nao credencial
    if VALOR_HEX.match(valor):
        return True  # hex de 32+ e formato de chave; nao e identificador
    if EH_IDENTIFICADOR.match(valor):
        return False  # nome de variavel, nao valor de credencial
    if VALOR_LONGO.match(valor):
        # Exige alguma diversity de caracteres: "aaaaaaaaaaaa" nao e chave.
        return len(set(valor)) >= 8
    if VALOR_BASE64_LONGO.match(valor):
        return len(set(valor)) >= 10
    return False


# ---------------------------------------------------------------- aplicacao

def redigir(texto: str) -> tuple[str, dict[str, int]]:
    """Substitui segredos pela marca. Devolve (texto, contagem por tipo)."""
    if not texto:
        return texto, {}

    contagem: Counter[str] = Counter()
    resultado = texto

    # 1. Por formato (independente do nome da variavel).
    for tipo, padrao in FORMATOS:
        resultado, n = padrao.subn(MARCA, resultado)
        if n:
            contagem[tipo] += n

    # 2. URL com credencial embutida — preserva o esquema, como a aplicacao faz.
    def _url(match: "re.Match") -> str:
        senha = match.group(3)
        if len(senha) < SENHA_MINIMA_URL:
            return match.group(0)  # placeholder de documentacao, nao credencial
        contagem["url_with_credentials"] += 1
        return f"{match.group(1)}{match.group(2)}:{MARCA}{match.group(4)}"

    resultado = URL_COM_CREDENCIAL.sub(_url, resultado)

    # 3. Atribuicao: so quando o nome E o valor indicam segredo.
    def _atribuicao(match: "re.Match") -> str:
        nome, operador, valor = match.group(1), match.group(2), match.group(3)
        if not NOMES_SEGREDO.search(nome):
            return match.group(0)
        if not _valor_suspeito(valor):
            return match.group(0)
        contagem["assigned_secret"] += 1
        return f"{nome}{operador}{MARCA}"

    resultado = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*([:=])\s*[\"']?([^\s\"'\n,;)\]}]+)[\"']?",
        _atribuicao, resultado)

    return resultado, dict(contagem)


def contem_segredo(texto: str) -> bool:
    """Algum segredo reconhecivel no texto?"""
    _, contagem = redigir(texto)
    return bool(contagem)
