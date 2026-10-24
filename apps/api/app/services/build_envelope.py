"""Contrato da proposta de mudança devolvida por um runtime Ollama (ADR 005).

Esta é a fronteira de segurança do Build isolado. O modelo não executa nada: ele
devolve um **envelope** descrevendo o que quer mudar, e este módulo decide se a
descrição é sequer admissível. Nada aqui toca disco, git ou shell — validar e
aplicar são passos separados de propósito, para que a recusa aconteça antes de
qualquer efeito colateral.

Duas invariantes que não podem ser afrouxadas sem novo ADR:

1. **Comando é escolha, não texto.** `checks` só aceita nomes de um allowlist
   fixo, os mesmos do `test_gate`. O modelo escolhe entre comandos
   pré-definidos; não escreve linha de shell. Não existe caminho pelo qual texto
   gerado vire execução.
2. **Caminho é verificado contra a árvore, não contra a string.** Recusar `..`
   por substring é ingênuo (`.env` continua passando de outras formas). A
   verificação real é resolver o caminho e exigir que continue dentro da raiz do
   worktree, além de barrar os padrões sensíveis por nome.
"""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Os mesmos checks que o test_gate sabe rodar. Qualquer outro nome é recusado.
ALLOWED_CHECKS: frozenset[str] = frozenset({"pytest", "vitest", "lint", "build"})

# Caminhos que um patch de agente nunca pode tocar. Migração de banco fica de
# fora por decisão explícita do CLAUDE.md: schema é decisão humana.
DENIED_PATH_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "**/.env*",
    "venv/*",
    "*/venv/*",
    "**/venv/**",
    ".git/*",
    "**/.git/**",
    ".github/workflows/*",
    "**/.github/workflows/**",
    "deploy.sh",
    "scripts/*deploy*",
    "alembic/versions/*",
    "**/alembic/versions/**",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
)

MAX_FILES = 40
MAX_CONTENT_CHARS = 200_000

FileAction = Literal["create", "update", "delete"]


class EnvelopeError(ValueError):
    """Envelope inadmissível. Vira evento da run, nunca exceção crua."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _path_is_denied(path: str) -> str | None:
    """Devolve o padrão violado, ou None. Comparação por segmento e por glob.

    O prefixo `./` é removido por corte de string, não por `lstrip`: `lstrip`
    remove *caracteres*, então `.env` viraria `env` e escaparia da denylist
    inteira. Foi exatamente esse o furo pego pelos testes desta fatia.
    """
    candidato = path

    while candidato.startswith("./"):
        candidato = candidato[2:]

    for pattern in DENIED_PATH_PATTERNS:
        if fnmatch(candidato, pattern):
            return pattern

    # Um segmento chamado `.env`, `venv` ou `.git` em qualquer profundidade —
    # pega o que o glob deixa escapar quando a profundidade varia.
    for segmento in PurePosixPath(candidato).parts:
        if segmento == "venv" or segmento == ".git":
            return f"segmento proibido: {segmento}"
        if segmento == ".env" or segmento.startswith(".env."):
            return f"segmento proibido: {segmento}"

    return None


def normalize_path(raw: str) -> str:
    """Caminho relativo seguro, ou EnvelopeError.

    Recusa: vazio, absoluto, com `..`, com `~`, com NUL, e qualquer padrão da
    denylist. O resultado é sempre relativo à raiz do worktree.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise EnvelopeError("path_empty", "Caminho vazio no envelope")

    path = raw.strip().replace("\\", "/")

    if "\x00" in path:
        raise EnvelopeError("path_invalid", "Caminho contém byte NUL")

    if path.startswith("/"):
        raise EnvelopeError(
            "path_absolute",
            f"Caminho absoluto não é permitido: {path}",
            {"path": path},
        )

    if path.startswith("~"):
        raise EnvelopeError(
            "path_home",
            f"Caminho de home não é permitido: {path}",
            {"path": path},
        )

    partes = PurePosixPath(path).parts

    if any(parte == ".." for parte in partes):
        raise EnvelopeError(
            "path_traversal",
            f"Caminho sai da árvore do worktree: {path}",
            {"path": path},
        )

    violado = _path_is_denied(path)

    if violado:
        raise EnvelopeError(
            "path_denied",
            f"Caminho protegido não pode ser alterado por agente: {path}",
            {"path": path, "pattern": violado},
        )

    return str(PurePosixPath(path))


class EnvelopeFile(BaseModel):
    """Uma mudança de arquivo proposta."""

    model_config = ConfigDict(extra="forbid")

    path: str
    action: FileAction = "update"
    content: str | None = None

    @field_validator("path")
    @classmethod
    def _validar_path(cls, valor: str) -> str:
        return normalize_path(valor)

    @field_validator("content")
    @classmethod
    def _limitar_conteudo(cls, valor: str | None) -> str | None:
        if valor is not None and len(valor) > MAX_CONTENT_CHARS:
            raise EnvelopeError(
                "content_too_large",
                f"Conteúdo acima de {MAX_CONTENT_CHARS} caracteres",
            )
        return valor


class BuildEnvelope(BaseModel):
    """Proposta completa de mudança, já validada."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    files: list[EnvelopeFile] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)

    @field_validator("files")
    @classmethod
    def _limitar_arquivos(cls, valor: list[EnvelopeFile]) -> list[EnvelopeFile]:
        if len(valor) > MAX_FILES:
            raise EnvelopeError(
                "too_many_files",
                f"Envelope propõe {len(valor)} arquivos (máximo {MAX_FILES})",
            )

        vistos: set[str] = set()
        for arquivo in valor:
            if arquivo.path in vistos:
                raise EnvelopeError(
                    "duplicate_path",
                    f"Caminho repetido no envelope: {arquivo.path}",
                    {"path": arquivo.path},
                )
            vistos.add(arquivo.path)

        return valor

    @field_validator("checks")
    @classmethod
    def _validar_checks(cls, valor: list[str]) -> list[str]:
        for check in valor:
            if check not in ALLOWED_CHECKS:
                raise EnvelopeError(
                    "check_not_allowed",
                    (
                        f"Check '{check}' não está no allowlist; "
                        f"permitidos: {', '.join(sorted(ALLOWED_CHECKS))}"
                    ),
                    {"check": check},
                )
        # Ordem estável e sem repetição: o gate roda cada check uma vez.
        return sorted(set(valor))


_JSON_BLOCK = re.compile(
    r"```(?:json)?\s*(?P<corpo>\{.*?\})\s*```",
    re.DOTALL,
)


def _extrair_json(texto: str) -> str:
    """Acha o objeto JSON dentro de uma resposta que pode vir com prosa.

    Modelos locais raramente devolvem JSON puro: vem cercado de explicação, de
    bloco markdown, ou de um "Claro! Aqui está:". Em vez de exigir disciplina do
    modelo, extraímos — mas sem `eval`, sem regex frouxa que aceite qualquer
    coisa, e falhando explicitamente quando não há objeto.
    """
    if not texto or not texto.strip():
        raise EnvelopeError("empty_response", "Runtime devolveu resposta vazia")

    bloco = _JSON_BLOCK.search(texto)

    if bloco:
        return bloco.group("corpo")

    inicio = texto.find("{")
    fim = texto.rfind("}")

    if inicio == -1 or fim == -1 or fim <= inicio:
        raise EnvelopeError(
            "no_json_found",
            "Resposta do runtime não contém objeto JSON",
            {"preview": texto[:200]},
        )

    return texto[inicio:fim + 1]


def parse_envelope(texto: str) -> BuildEnvelope:
    """Texto do modelo → envelope validado, ou EnvelopeError.

    Qualquer falha vira erro de domínio com código: quem chama registra o
    evento e conta a tentativa, sem stack trace vazando para a run.
    """
    bruto = _extrair_json(texto)

    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as error:
        raise EnvelopeError(
            "invalid_json",
            f"JSON malformado na resposta do runtime: {error.msg}",
            {"preview": bruto[:200]},
        ) from error

    if not isinstance(dados, dict):
        raise EnvelopeError(
            "not_an_object",
            "Envelope precisa ser um objeto JSON",
        )

    try:
        return BuildEnvelope(**dados)
    except EnvelopeError:
        raise
    except Exception as error:
        # Pydantic embrulha o EnvelopeError levantado nos validators; se o
        # original estiver na cadeia, ele é a mensagem útil.
        original = error.__cause__ or error.__context__
        if isinstance(original, EnvelopeError):
            raise original from error

        for candidato in getattr(error, "errors", lambda: [])():
            causa = candidato.get("ctx", {}).get("error")
            if isinstance(causa, EnvelopeError):
                raise causa from error

        raise EnvelopeError(
            "schema_invalid",
            f"Envelope não bate com o contrato: {error}",
        ) from error
