"""Leitura do repositório: git e mtimes.

Todos os comandos git aqui são de leitura, e `--no-optional-locks` impede que
`git status` atualize o cache de stat do índice — sem ele, "somente leitura"
já não seria verdade no nível do arquivo.

Limitação assumida: **não há `git fetch`**. Fetch é rede e escrita em `.git`.
A contagem de commits não enviados é medida contra o `origin/develop` local,
ou seja, contra o último fetch que alguém fez. O check mede divergência
conhecida, não divergência real com o GitHub.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .. import config


TIMEOUT = 10


def _git(raiz: Path, *argumentos: str) -> tuple[int, str]:
    resultado = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(raiz), *argumentos],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )
    return resultado.returncode, resultado.stdout.strip()


class LeitorRepositorio:
    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = Path(raiz or config.WORKDEV_DIR)

    # ------------------------------------------------------------------ git

    def branch_atual(self) -> str | None:
        codigo, saida = _git(self.raiz, "rev-parse", "--abbrev-ref", "HEAD")
        return saida or None if codigo == 0 else None

    def modificados_rastreados(self) -> list[str]:
        """Arquivos rastreados e alterados — ou seja, já rodando em produção.

        `deploy.sh` builda a árvore de trabalho, não um commit. Arquivo
        modificado aqui é código em produção que não existe em lugar nenhum
        além desta VPS.
        """
        codigo, saida = _git(self.raiz, "status", "--porcelain")
        if codigo != 0:
            return []
        arquivos = []
        for linha in saida.splitlines():
            if len(linha) < 4:
                continue
            marca, caminho = linha[:2], linha[3:]
            if marca[0] in "MARCD" or marca[1] in "MD":
                arquivos.append(caminho)
        return arquivos

    def contar_commits(self, intervalo: str) -> int | None:
        codigo, saida = _git(self.raiz, "rev-list", "--count", intervalo)
        if codigo != 0 or not saida.isdigit():
            return None
        return int(saida)

    def data_commit_mais_antigo(self, intervalo: str) -> datetime | None:
        codigo, saida = _git(self.raiz, "log", "--format=%cI", intervalo)
        if codigo != 0 or not saida:
            return None
        try:
            return datetime.fromisoformat(saida.splitlines()[-1])
        except ValueError:
            return None

    def referencia_existe(self, referencia: str) -> bool:
        codigo, _ = _git(self.raiz, "rev-parse", "--verify", "--quiet", referencia)
        return codigo == 0

    def ultimo_commit_de(self, caminho: str) -> datetime | None:
        codigo, saida = _git(self.raiz, "log", "-1", "--format=%cI", "--", caminho)
        if codigo != 0 or not saida:
            return None
        try:
            return datetime.fromisoformat(saida)
        except ValueError:
            return None

    # ----------------------------------------------------------- filesystem

    def mtime(self, caminho: str) -> datetime | None:
        alvo = self.raiz / caminho
        try:
            return datetime.fromtimestamp(alvo.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    def mtime_mais_recente(
        self, subdiretorio: str, sufixos: Sequence[str] = (".py", ".ts", ".tsx", ".css")
    ) -> tuple[datetime | None, str | None]:
        """mtime do arquivo-fonte mais novo, ignorando artefato derivado."""
        base = self.raiz / subdiretorio
        mais_novo: tuple[float, str] | None = None
        try:
            for arquivo in base.rglob("*"):
                if not arquivo.is_file() or arquivo.suffix not in sufixos:
                    continue
                if "__pycache__" in arquivo.parts or "node_modules" in arquivo.parts:
                    continue
                marca = arquivo.stat().st_mtime
                if mais_novo is None or marca > mais_novo[0]:
                    mais_novo = (marca, str(arquivo.relative_to(self.raiz)))
        except OSError:
            return None, None
        if mais_novo is None:
            return None, None
        return datetime.fromtimestamp(mais_novo[0], tz=timezone.utc), mais_novo[1]

    def arquivos_markdown(self, subcaminho: str, e_diretorio: bool) -> list[str]:
        """Caminhos relativos dos .md e .txt aceitos pelo ingestor do RAG.

        O nome histórico é preservado para não quebrar consumidores externos.
        """
        alvo = self.raiz / subcaminho
        try:
            if not e_diretorio:
                return [subcaminho] if alvo.is_file() else []
            return sorted(
                str(arquivo.relative_to(self.raiz))
                for arquivo in alvo.rglob("*")
                if arquivo.is_file() and arquivo.suffix in {".md", ".txt"}
            )
        except OSError:
            return []

    def revisoes_alembic(self, subdiretorio: str) -> tuple[set[str], set[str]]:
        """Devolve (todas as revisões, heads) lendo os arquivos de migration.

        Sem importar alembic: `alembic.config` puxa o engine da aplicação, que
        depende de DATABASE_URL e do cwd. Aqui os arquivos são lidos com `ast`,
        sem executar nada. Head é a revisão que ninguém declara como
        `down_revision`.
        """
        import ast

        revisoes: set[str] = set()
        anteriores: set[str] = set()
        base = self.raiz / subdiretorio
        try:
            arquivos = sorted(base.glob("*.py"))
        except OSError:
            return set(), set()

        for arquivo in arquivos:
            try:
                arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            for no in arvore.body:
                alvo = None
                if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
                    alvo, valor = no.target.id, no.value
                elif isinstance(no, ast.Assign) and len(no.targets) == 1:
                    if isinstance(no.targets[0], ast.Name):
                        alvo, valor = no.targets[0].id, no.value
                if alvo not in ("revision", "down_revision") or valor is None:
                    continue
                try:
                    conteudo = ast.literal_eval(valor)
                except (ValueError, TypeError):
                    continue
                if alvo == "revision" and isinstance(conteudo, str):
                    revisoes.add(conteudo)
                elif alvo == "down_revision":
                    if isinstance(conteudo, str):
                        anteriores.add(conteudo)
                    elif isinstance(conteudo, (list, tuple)):
                        anteriores.update(c for c in conteudo if isinstance(c, str))

        return revisoes, revisoes - anteriores

    def titulo_markdown(self, subcaminho: str) -> str:
        """Título calculado do mesmo modo que o ingestor para .md e .txt."""
        for linha in self.ler_texto(subcaminho, limite=2000).splitlines():
            limpa = linha.strip()
            if limpa.startswith("# "):
                return limpa[2:].strip()
        return Path(subcaminho).stem

    def ler_texto(self, subcaminho: str, limite: int = 4000) -> str:
        try:
            with (self.raiz / subcaminho).open("r", encoding="utf-8") as arquivo:
                return arquivo.read(limite)
        except OSError:
            return ""
