"""Validação de hunks de diff: nenhum patch é aplicado sem âncora verificável.

Por que este módulo existe
--------------------------
Um hunk unidiff tem a forma `@@ -antigo,inicio[,contagem] +novo,inicio[,contagem] @@`.
Quando o hunk **traz linhas de contexto** (as linhas ` ` do arquivo original), o
`git apply` ancora a mudança pelo *conteúdo*: ele procura o trecho no arquivo e
só aplica se ele estiver lá. Se a posição declarada estiver errada, o `--check`
reprova — é a âncora que protege.

Quando o hunk **não traz contexto** (`@@ -172,0 +173 @@`, ou `@@ -10 +11 @@`),
não existe âncora: o git aplica a linha na posição que der, e na prática
**joga o conteúdo no fim do arquivo**. Medido em 2026-11-04: hunks declarados
nas linhas 10, 50 e 90 de um arquivo de 100 linhas caíram todos na linha 101.

Foi exatamente o que aconteceu num exercício do Workspace Local: a docstring de
uma função foi parar no fim do arquivo, depois do `return` — código morto. O
`git apply --check` passou, o `exige` passou (a string existia, só que no
lugar errado), o pytest passou (string morta não quebra nada) e a auditoria do
observer aprovou. Quatro camadas verdes sobre uma mudança errada.

Este módulo recusa o patch **antes** de qualquer `git apply`, com um erro que
diz o que fazer: pedir diff com contexto, ou aplicar com `--unidiff-zero`
(também ancorado, na posição declarada).

Contrato
--------
`validar_hunks(diff)` devolve a lista de problemas encontrados. Lista vazia =
patch aplicável com segurança. Cada problema traz: código estável, mensagem
para o operador e o hunk infrator.

O módulo é usado pelos dois caminhos que aplicam patch:
- `apps/api/app/services/workspace_execucao.py` (execução da fatia);
- `scripts/bancada_checks.py` (checagem mecânica da proposta).
"""
from __future__ import annotations

import re
from typing import NamedTuple

# "--- a/arquivo", "+++ b/arquivo" ou "diff --git a/... b/..."
CABECALHO_ARQUIVO = re.compile(r"^\+\+\+ b/(\S+)")
# "@@ -12,3 +12,4 @@" ou "@@ -12 +12 @@" ou "@@ -12,0 +13 @@"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

# Prefixos de linha dentro de um hunk.
CONTEXTO = " "
REMOVIDO = "-"
ADICIONADO = "+"


class ProblemaHunk(NamedTuple):
    """Um patch que não pode ser aplicado com segurança."""

    codigo: str
    mensagem: str
    hunk: str
    arquivo: str | None = None

    def __str__(self) -> str:  # pragma: no cover - só formatação
        return self.mensagem


def _hunks_por_arquivo(diff: str) -> list[tuple[str | None, str, list[str]]]:
    """Separa o diff em (arquivo, cabeçalho do hunk, linhas do hunk)."""
    resultado: list[tuple[str | None, str, list[str]]] = []
    arquivo: str | None = None
    cabecalho: str | None = None
    corpo: list[str] = []

    def fechar() -> None:
        if cabecalho is not None:
            resultado.append((arquivo, cabecalho, corpo))

    for linha in diff.splitlines():
        novo_arquivo = CABECALHO_ARQUIVO.match(linha)
        if novo_arquivo:
            fechar()
            arquivo = novo_arquivo.group(1)
            cabecalho = None
            corpo = []
            continue
        if linha.startswith("--- "):
            # "--- a/arquivo": o nome real vem do "+++ b/..." seguinte.
            continue
        if linha.startswith("diff --git "):
            fechar()
            arquivo = None
            cabecalho = None
            corpo = []
            continue
        if linha.startswith("@@"):
            fechar()
            cabecalho = linha
            corpo = []
            continue
        if cabecalho is not None and linha[:1] in (CONTEXTO, REMOVIDO, ADICIONADO):
            corpo.append(linha)
            continue
        if cabecalho is not None and not linha.strip():
            # Linha vazia dentro de um hunk conta como contexto em branco.
            corpo.append(CONTEXTO)
    fechar()
    return resultado


def validar_hunks(diff: str) -> list[ProblemaHunk]:
    """Lista os problemas que impedem aplicar `diff` com segurança.

    Vazia = patch aplicável. Cada problema é um hunco sem contexto, ou um hunk
    cujas contagens não fecham com as linhas presentes.
    """
    problemas: list[ProblemaHunk] = []

    for arquivo, cabecalho, corpo in _hunks_por_arquivo(diff):
        if cabecalho is None:
            continue
        match = HUNK.match(cabecalho)
        if not match:
            problemas.append(ProblemaHunk(
                "hunk_malformado",
                f"hunk malformado em {arquivo or '?'}: {cabecalho}",
                cabecalho, arquivo))
            continue

        contagem_antiga = match.group(2)
        contagem_nova = match.group(4)
        linhas_contexto = [l for l in corpo if l.startswith(CONTEXTO)]
        linhas_removidas = [l for l in corpo if l.startswith(REMOVIDO)]
        linhas_adicionadas = [l for l in corpo if l.startswith(ADICIONADO)]

        # Sem contexto, o hunk não tem âncora: o git aplica onde der.
        if not linhas_contexto:
            esperado = contagem_antiga if contagem_antiga is not None else "1"
            problemas.append(ProblemaHunk(
                "hunk_sem_contexto",
                f"hunk sem linhas de contexto em {arquivo or '?'} ({cabecalho}): "
                f"sem âncora, o git aplicaria o trecho no fim do arquivo em vez de "
                f"na linha {match.group(1)}. Peça diff com contexto (as linhas "
                f"originais em volta da mudança) ou aplique com --unidiff-zero. "
                f"Esperava {esperado} linha(s) antiga(s) e veio {len(linhas_removidas)}.",
                cabecalho, arquivo))
            continue

        # Com contexto, as contagens precisam fechar — senão o git recusa.
        if contagem_antiga is not None:
            esperado_antigo = int(contagem_antiga)
            real_antigo = len(linhas_contexto) + len(linhas_removidas)
            if esperado_antigo != real_antigo:
                problemas.append(ProblemaHunk(
                    "hunk_contagem_incoerente",
                    f"contagem inconsistente em {arquivo or '?'} ({cabecalho}): "
                    f"o hunk declara {esperado_antigo} linha(s) antiga(s) e tem {real_antigo}.",
                    cabecalho, arquivo))
        if contagem_nova is not None:
            esperado_novo = int(contagem_nova)
            real_novo = len(linhas_contexto) + len(linhas_adicionadas)
            if esperado_novo != real_novo:
                problemas.append(ProblemaHunk(
                    "hunk_contagem_incoerente",
                    f"contagem inconsistente em {arquivo or '?'} ({cabecalho}): "
                    f"o hunk declara {esperado_novo} linha(s) nova(s) e tem {real_novo}.",
                    cabecalho, arquivo))

    return problemas


def diff_tem_contexto(diff: str) -> bool:
    """True se todos os hunks do diff trazem linhas de contexto."""
    hunks = _hunks_por_arquivo(diff)
    if not hunks:
        return False
    return all(
        any(l.startswith(CONTEXTO) for l in corpo)
        for _arquivo, _cabecalho, corpo in hunks
    )


def resumo(problemas: list[ProblemaHunk]) -> str:
    """Mensagem de uma linha para o operador."""
    if not problemas:
        return ""
    if len(problemas) == 1:
        return problemas[0].mensagem
    return (f"{len(problemas)} problema(s) no diff: "
            + "; ".join(p.codigo for p in problemas))
