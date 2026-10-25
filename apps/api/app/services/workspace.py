"""Workspace: leitura do checkout (ou da cópia da sessão) para o explorer/editor.

A lista de arquivos vem do git (rastreados + não rastreados não ignorados), não
do disco: .env, node_modules, venv, models/, dist e tmp/ ficam de fora porque o
.gitignore já os exclui. Por cima, a mesma lista de bloqueio da Bancada, realpath
preso ao checkout, limites de tamanho e máscara de chaves em todo conteúdo.
Nenhuma função aqui escreve em disco ou altera o repositório; o salvar do
editor é do workspace_sessao, e só na cópia da sessão.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from app.services.bancada_runner import BLOQUEADOS

REPO = Path(os.environ.get("WORKDEV_BANCADA_REPO", "/opt/workdev"))
LIMITE_ARQUIVO = 200_000
LIMITE_DIFF = 200_000
LIMITE_ITENS = 500
TIMEOUT_GIT = 10
# tmp/ guarda propostas e pareceres; .github e .gitignore não têm nada sensível,
# mas ".git" de BLOQUEADOS já os recusa — preferimos errar para o lado seguro.
# .workdev-recovery/ guarda patches e tarballs de recuperação: conteúdo arbitrário.
BLOQUEADOS_WORKSPACE = (*BLOQUEADOS, "tmp/", "__pycache__", "id_ecdsa", ".ssh/", ".workdev-recovery")
CHAVE = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|sb_secret_[A-Za-z0-9_-]+|sb_publishable_[A-Za-z0-9_-]+"
    r"|Bearer\s+[A-Za-z0-9._-]{12,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})"
)


class WorkspaceErro(Exception):
    def __init__(self, status: int, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.status, self.codigo, self.mensagem = status, codigo, mensagem


def mascarar(texto: str) -> str:
    return CHAVE.sub("[mascarado]", texto)


def _git(*args: str, ok_codes: tuple[int, ...] = (0,), raiz: Path | None = None) -> str:
    """`raiz`: a cópia da sessão do Workspace; sem ela, o checkout (REPO)."""
    try:
        saida = subprocess.run(
            ["git", "-C", str(raiz or REPO), "-c", "core.quotepath=off", *args],
            capture_output=True, timeout=TIMEOUT_GIT, check=False,
        )
    except subprocess.TimeoutExpired as erro:
        raise WorkspaceErro(504, "git_lento", "o git demorou demais") from erro
    if saida.returncode not in ok_codes:
        raise WorkspaceErro(502, "git_falhou", "o git não respondeu como esperado")
    return saida.stdout.decode("utf-8", errors="replace")


def bloqueado(caminho: str) -> bool:
    baixo = caminho.lower()
    return any(p in baixo for p in BLOQUEADOS_WORKSPACE) or baixo.startswith("tmp")


def arquivos(raiz: Path | None = None) -> list[str]:
    """Rastreados + não rastreados não ignorados, já sem os bloqueados."""
    lista = _git("ls-files", "-co", "--exclude-standard", "-z", raiz=raiz).split("\0")
    return sorted({c for c in lista if c and not bloqueado(c)})


def _normalizar(caminho: str, base: Path | None = None) -> str:
    if not isinstance(caminho, str):
        raise WorkspaceErro(422, "caminho_invalido", "caminho inválido")
    caminho = caminho.strip().strip("/")
    if "\0" in caminho or caminho.startswith("~"):
        raise WorkspaceErro(422, "caminho_invalido", "caminho inválido")
    if not caminho:
        return ""
    raiz = (base or REPO).resolve()
    alvo = Path(os.path.realpath(raiz / caminho))
    if alvo != raiz and raiz not in alvo.parents:
        raise WorkspaceErro(422, "caminho_invalido", "fora do repositório")
    relativo = alvo.relative_to(raiz).as_posix()
    if bloqueado(caminho) or bloqueado(relativo):
        raise WorkspaceErro(403, "caminho_bloqueado", "caminho bloqueado")
    return relativo


def arvore(pasta: str = "", raiz: Path | None = None) -> dict:
    """Filhos imediatos de uma pasta (carga preguiçosa, uma pasta por vez)."""
    pasta = _normalizar(pasta, raiz)
    prefixo = f"{pasta}/" if pasta else ""
    pastas: set[str] = set()
    itens: list[dict] = []
    for caminho in arquivos(raiz):
        if not caminho.startswith(prefixo):
            continue
        resto = caminho[len(prefixo):]
        if "/" in resto:
            pastas.add(resto.split("/", 1)[0])
        else:
            itens.append({"nome": resto, "caminho": caminho, "tipo": "arquivo"})
    if pasta and not pastas and not itens:
        raise WorkspaceErro(404, "pasta_inexistente", "pasta não encontrada")
    todos = [{"nome": p, "caminho": f"{prefixo}{p}", "tipo": "pasta"} for p in sorted(pastas)] + itens
    return {"pasta": pasta, "itens": todos[:LIMITE_ITENS], "truncado": len(todos) > LIMITE_ITENS}


def ler_arquivo(caminho: str, raiz: Path | None = None) -> dict:
    caminho = _normalizar(caminho, raiz)
    if caminho not in set(arquivos(raiz)):
        raise WorkspaceErro(404, "arquivo_fora_do_git", "arquivo não está no repositório")
    alvo = (raiz or REPO).resolve() / caminho
    if not alvo.is_file():
        raise WorkspaceErro(404, "arquivo_inexistente", "arquivo não encontrado")
    tamanho = alvo.stat().st_size
    with alvo.open("rb") as arquivo:
        bruto = arquivo.read(LIMITE_ARQUIVO + 1)
    if b"\0" in bruto[:8192]:
        return {"caminho": caminho, "binario": True, "tamanho": tamanho, "texto": "", "linhas": 0, "truncado": False}
    truncado = len(bruto) > LIMITE_ARQUIVO
    original = bruto[:LIMITE_ARQUIVO].decode("utf-8", errors="replace")
    texto = mascarar(original)
    # `sha256` é do conteúdo inteiro em disco: o salvar recusa se o arquivo mudou
    # depois de aberto. `mascarado` diz que o texto mostrado não é o do disco —
    # editar e salvar trocaria a chave real por "[mascarado]".
    return {"caminho": caminho, "binario": False, "tamanho": tamanho, "texto": texto,
            "linhas": texto.count("\n") + (0 if texto.endswith("\n") or not texto else 1), "truncado": truncado,
            "sha256": hashlib.sha256(bruto).hexdigest() if not truncado else None, "mascarado": texto != original}


def alteracoes(raiz: Path | None = None) -> dict:
    """Arquivos alterados em relação ao HEAD, com +/− por arquivo."""
    base = raiz or REPO
    numstat: dict[str, tuple[int | None, int | None]] = {}
    for linha in _git("diff", "HEAD", "--numstat", "-z", raiz=raiz).split("\0"):
        partes = linha.split("\t")
        if len(partes) == 3 and partes[2]:
            mais, menos, caminho = partes
            numstat[caminho] = (int(mais) if mais.isdigit() else None, int(menos) if menos.isdigit() else None)
    itens = []
    registros = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", raiz=raiz).split("\0")
    i = 0
    while i < len(registros):
        registro = registros[i]
        i += 1
        if len(registro) < 4:
            continue
        estado, caminho = registro[:2], registro[3:]
        if estado[0] in "RC":
            i += 1  # o caminho de origem vem no próximo campo
        if bloqueado(caminho):
            continue
        mais, menos = numstat.get(caminho, (None, None))
        if estado == "??":
            try:
                if (base / caminho).stat().st_size > LIMITE_ARQUIVO:
                    mais = None
                else:
                    mais = (base / caminho).read_text(encoding="utf-8", errors="replace").count("\n")
            except OSError:
                mais = None
            menos = 0
        itens.append({"caminho": caminho, "estado": "novo" if estado == "??" else estado.strip() or "M",
                      "mais": mais, "menos": menos})
    return {"base": _git("rev-parse", "--short", "HEAD", raiz=raiz).strip(), "itens": itens[:LIMITE_ITENS],
            "truncado": len(itens) > LIMITE_ITENS}


def diff_arquivo(caminho: str, raiz: Path | None = None) -> dict:
    caminho = _normalizar(caminho, raiz)
    if caminho not in {item["caminho"] for item in alteracoes(raiz)["itens"]}:
        raise WorkspaceErro(404, "sem_alteracao", "arquivo sem alteração")
    rastreado = bool(_git("ls-files", "--", caminho, raiz=raiz).strip())
    if rastreado:
        texto = _git("diff", "HEAD", "--", caminho, raiz=raiz)
    else:
        # --no-index devolve 1 quando há diferença; o arquivo novo inteiro vira "+".
        texto = _git("diff", "--no-index", "--", "/dev/null", caminho, ok_codes=(0, 1), raiz=raiz)
    truncado = len(texto) > LIMITE_DIFF
    return {"caminho": caminho, "diff": mascarar(texto[:LIMITE_DIFF]), "truncado": truncado}
