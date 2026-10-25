"""Leitura do checkout de trabalho para modelos: listar pasta, buscar texto, ler arquivo.

Uma implementação só para o supervisor do Workspace (tools do AI Hub) e para o
modelo local do Workspace (function calling no llama-server). Tudo somente
leitura, dentro de WORKDEV_BANCADA_REPO — o mesmo checkout que o Explorer e o
`ler_trecho` mostram, não a release —, com a trava de caminhos da Bancada
(`bancada_local.caminho_seguro`: realpath, raiz e lista de bloqueados).

A busca usa `git grep`: respeita o .gitignore (tmp/, dist/, venv) e pula
binários sem precisar percorrer a árvore em Python.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.services import bancada_runner

MAX_ITENS_PASTA = 300
MAX_OCORRENCIAS = 80
MAX_TEXTO_BUSCA = 200
MAX_CHARS_LINHA = 200
MAX_LINHAS_ARQUIVO = 200
MAX_BYTES_ARQUIVO = 1_000_000
# Pastas que a listagem esconde: enormes ou geradas, nunca o que se quer editar.
PULAR = {"venv", ".venv", "__pycache__", "dist", "build", ".pytest_cache", ".turbo"}


class Recusado(Exception):
    pass


def raiz() -> Path:
    return bancada_runner.REPO_TRABALHO.resolve()


def caminho_seguro(relativo: str) -> Path:
    local = bancada_runner._modulo("bancada_local")
    try:
        return local.caminho_seguro(relativo, raiz())
    except local.Recusado as erro:
        raise Recusado(str(erro)) from erro


def _bloqueado(relativo: str) -> bool:
    texto = relativo.lower()
    return any(proibido in texto for proibido in bancada_runner.BLOQUEADOS)


def _rel(alvo: Path) -> str:
    return alvo.relative_to(raiz()).as_posix() or "."


def listar_pasta(caminho: str = ".") -> dict:
    alvo = caminho_seguro(caminho or ".")
    if not alvo.is_dir():
        raise Recusado(f"não é pasta: {caminho}")
    itens = []
    for item in sorted(alvo.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        nome = _rel(item)
        if item.name in PULAR or item.name == "node_modules" or _bloqueado(nome):
            continue
        itens.append(nome + ("/" if item.is_dir() else ""))
    saida = {"caminho": _rel(alvo), "itens": itens[:MAX_ITENS_PASTA]}
    if len(itens) > MAX_ITENS_PASTA:
        saida["truncado"] = True
    return saida


def buscar_texto(texto: str, caminho: str = ".") -> dict:
    if not isinstance(texto, str) or not texto.strip():
        raise Recusado("texto vazio")
    if len(texto) > MAX_TEXTO_BUSCA:
        raise Recusado(f"texto acima de {MAX_TEXTO_BUSCA} caracteres")
    alvo = caminho_seguro(caminho or ".")
    # -F literal, -I pula binário, --untracked inclui arquivo novo ainda não
    # commitado (o ignorado continua fora). -e protege texto que começa com "-".
    comando = ["git", "-C", str(raiz()), "grep", "-n", "-I", "-F", "--untracked", "--no-color",
               "-e", texto, "--", _rel(alvo)]
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as erro:
        raise Recusado("busca demorou demais; restrinja a pasta") from erro
    if resultado.returncode not in (0, 1):
        raise Recusado(f"busca falhou: {resultado.stderr.strip()[:200]}")
    ocorrencias, truncado = [], False
    for linha in resultado.stdout.splitlines():
        arquivo, _, resto = linha.partition(":")
        numero, _, conteudo = resto.partition(":")
        if _bloqueado(arquivo) or not numero.isdigit():
            continue
        if len(ocorrencias) >= MAX_OCORRENCIAS:
            truncado = True
            break
        ocorrencias.append({"caminho": arquivo, "linha": int(numero),
                            "texto": conteudo.strip()[:MAX_CHARS_LINHA]})
    saida = {"texto": texto, "caminho": _rel(alvo), "ocorrencias": ocorrencias}
    if truncado:
        saida["truncado"] = True
    return saida


def ler_arquivo(caminho: str, inicio: int = 1, fim: int = MAX_LINHAS_ARQUIVO) -> dict:
    alvo = caminho_seguro(caminho)
    if not alvo.is_file():
        raise Recusado(f"não é arquivo: {caminho}")
    # Tamanho por stat antes de ler: um GGUF em models/ tem 9 GB.
    if alvo.stat().st_size > MAX_BYTES_ARQUIVO:
        raise Recusado(f"arquivo acima de {MAX_BYTES_ARQUIVO} bytes: {caminho}")
    conteudo = alvo.read_text(encoding="utf-8", errors="replace")
    if "\x00" in conteudo:
        raise Recusado(f"arquivo binário: {caminho}")
    linhas = conteudo.splitlines()
    inicio = max(1, int(inicio))
    pedido_fim = int(fim)
    fim = min(len(linhas), pedido_fim, inicio + MAX_LINHAS_ARQUIVO - 1)
    if fim < inicio:
        raise Recusado(f"intervalo vazio {inicio}-{pedido_fim} em {caminho} ({len(linhas)} linhas)")
    saida = {"caminho": _rel(alvo), "inicio": inicio, "fim": fim, "total_linhas": len(linhas),
             "texto": "\n".join(linhas[inicio - 1:fim])}
    if fim < min(pedido_fim, len(linhas)):
        saida["truncado"] = True
    return saida
