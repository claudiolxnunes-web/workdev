"""Cache determinístico para resultados de gate do Workspace Local.

O cache permite reaproveitar resultados de testes, lint e build quando o HEAD
da sessão e o conjunto de arquivos tocados não mudaram. A chave é um sha256
de (head + caminhos ordenados + comandos), tornando o cache determinístico e
invalidável automaticamente por qualquer mudança de código.

O cache fica fora do repositório em
`/opt/workdev-builds/workspace/.gate-cache/`. Cada entrada guarda o resultado
(passou/não passou), a lista de checks e o stdout, com TTL padrão de 7 dias.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services import build_worktree
from app.services.test_gate import CheckResult


DEFAULT_TTL_DIAS = 7
CACHE_DIR = build_worktree.builds_root() / "workspace" / ".gate-cache"


@dataclass(frozen=True)
class CacheKey:
    """Componentes que formam a chave de cache."""

    head: str
    caminhos: tuple[str, ...]
    comandos: tuple[str, ...]

    def sha256(self) -> str:
        payload = json.dumps(
            {"head": self.head, "caminhos": self.caminhos, "comandos": self.comandos},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CachedResult:
    """Resultado de gate armazenado em cache."""

    passou: bool
    checks: list[dict[str, Any]]
    stdout: str
    gravado_em: str

    def to_check_results(self) -> list[CheckResult]:
        return [CheckResult(**c) for c in self.checks]


def _diretorio() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _arquivo(chave: str) -> Path:
    return _diretorio() / f"{chave[:32]}.json"


def chave(head: str, caminhos: list[str], comandos: list[str]) -> str:
    """Gera chave determinística para um conjunto de gate."""
    return CacheKey(
        head=head,
        caminhos=tuple(sorted(set(caminhos))),
        comandos=tuple(comandos),
    ).sha256()


def buscar(head: str, caminhos: list[str], comandos: list[str]) -> CachedResult | None:
    """Busca resultado em cache. Retorna None se não existir ou estiver expirado."""
    caminho = _arquivo(chave(head, caminhos, comandos))
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        gravado = datetime.fromisoformat(dados["gravado_em"])
        if datetime.now(timezone.utc) - gravado > timedelta(days=DEFAULT_TTL_DIAS):
            caminho.unlink(missing_ok=True)
            return None
        return CachedResult(
            passou=dados["passou"],
            checks=dados["checks"],
            stdout=dados.get("stdout", ""),
            gravado_em=dados["gravado_em"],
        )
    except (OSError, ValueError, KeyError):
        caminho.unlink(missing_ok=True)
        return None


def gravar(
    head: str,
    caminhos: list[str],
    comandos: list[str],
    passou: bool,
    checks: list[CheckResult],
    stdout: str = "",
) -> None:
    """Grava resultado no cache e remove entradas expiradas."""
    _limpar_expirados()
    caminho = _arquivo(chave(head, caminhos, comandos))
    dados = {
        "passou": passou,
        "checks": [asdict(c) for c in checks],
        "stdout": stdout,
        "gravado_em": datetime.now(timezone.utc).isoformat(),
    }
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    temporario.replace(caminho)


def _limpar_expirados() -> None:
    """Remove arquivos de cache com mais de TTL_DIAS."""
    limite = datetime.now(timezone.utc) - timedelta(days=DEFAULT_TTL_DIAS)
    diretorio = _diretorio()
    for caminho in diretorio.glob("*.json"):
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            gravado = datetime.fromisoformat(dados["gravado_em"])
            if gravado < limite:
                caminho.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            caminho.unlink(missing_ok=True)


def limpar_tudo() -> None:
    """Limpa todo o cache. Útil em testes."""
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
