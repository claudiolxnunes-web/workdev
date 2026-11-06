"""Verificação semântica do diff aplicado: o código novo caiu onde a instrução pediu?

Por que este módulo existe
--------------------------
O `exige` (regex sobre as linhas `+` do diff) responde "o código pedido existe
em algum lugar?". Não responde "está no lugar certo?". Em 2026-11-04 essa
diferença deixou passar código morto: a docstring existia, mas depois de um
`return` — o `exige` dava verde.

Este é a **segunda camada**, e roda depois de o patch ser aplicado na cópia da
sessão. O diff sozinho não diz onde a mudança caiu; o arquivo final diz.

Como funciona
-------------
1. Acha no arquivo final as linhas que o diff introduziu (comparando o conteúdo
   textual das linhas `+` com o arquivo aplicado).
2. Pergunta ao AST em qual função cada uma dessas linhas caiu.
3. Compara com a função que a instrução nomeia.

Achados possíveis
------------------
- `codigo_morto` — a linha nova ficou depois de um `return`/`raise`: é
  inalcançável. É o caso do bug de 2026-11-04.
- `simbolo_em_outro_escopo` — a instrução pediu a função `criar`, e a linha
  nova caiu dentro de `apagar_branch`.
- `funcao_nao_alterada` — a instrução pediu `criar`, e nenhuma linha nova
  ficou dentro dela.

Tudo com AST: sem LLM, sem custo, determinístico. Devolve achados no mesmo
formato do `bancada_checks` (`categoria`, `severidade`, `mensagem`).

O que este módulo **não** faz
-----------------------------
Não julga se a mudança cumpre o *sentido* do pedido (isso é do observer, com
LLM). Não substitui o gate. Não altera nada.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

# Terminadores de fluxo: o que vem depois deles, no mesmo bloco, é inalcançável.
TERMINADORES = (ast.Return, ast.Raise, ast.Continue, ast.Break)


class Achado(NamedTuple):
    categoria: str
    severidade: str
    mensagem: str

    def como_dict(self) -> dict:
        return {"categoria": self.categoria, "severidade": self.severidade,
                "mensagem": self.mensagem}


# ---------------------------------------------------------------- diff

def arquivos_do_diff(diff: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)


def linhas_novas(diff: str) -> list[str]:
    """As linhas `+` do diff, sem o cabeçalho `+++`."""
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def funcoes_citadas(instrucao: str) -> list[str]:
    """Nomes que a instrução trata como alvo ('a função criar', 'em `criar`')."""
    padroes = [
        r"(?:fun[cç][aã]o|m[eé]todo)\s+`?([A-Za-z_]\w*)`?",
        r"`([A-Za-z_]\w*)`",
        r"\bem\s+([A-Za-z_]\w*)\s*\(",
    ]
    nomes: list[str] = []
    for padrao in padroes:
        for nome in re.findall(padrao, instrucao, re.IGNORECASE):
            if nome not in nomes:
                nomes.append(nome)
    return nomes


# ---------------------------------------------------------------- AST

def _pai_por_linha(arvore: ast.AST) -> dict[int, list[str]]:
    """Linha -> nomes das funções (e classe) que contêm essa linha.

    A lista vai do mais interno para o mais externo.
    """
    mapa: dict[int, list[str]] = {}

    def marcar(no: ast.AST, pilha: list[str]) -> None:
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pilha = pilha + [no.name]
        inicio = getattr(no, "lineno", None)
        fim = getattr(no, "end_lineno", None)
        if inicio is None:
            return
        for linha in range(inicio, (fim or inicio) + 1):
            mapa.setdefault(linha, list(pilha))

    class Visitador(ast.NodeVisitor):
        def visit_FunctionDef(self, no):  # noqa: N802
            marcar(no, [])
            self.generic_visit(no)

        def visit_AsyncFunctionDef(self, no):  # noqa: N802
            marcar(no, [])
            self.generic_visit(no)

        def visit_ClassDef(self, no):  # noqa: N802
            marcar(no, [])
            self.generic_visit(no)

    Visitador().visit(arvore)
    return mapa


def codigo_morto(arvore: ast.AST) -> list[tuple[int, str]]:
    """(linha, contexto) de código inalcançável depois de um terminador."""
    achados: list[tuple[int, str]] = []
    vistos: set[int] = set()
    corpos_de_funcao = (ast.FunctionDef, ast.AsyncFunctionDef)

    def olhar(corpo: list, onde: str) -> None:
        for indice, no in enumerate(corpo[:-1]):
            if not isinstance(no, TERMINADORES):
                continue
            if isinstance(no, corpos_de_funcao):
                continue  # docstring é o 1º item do corpo: nunca "depois" de terminador
            seguinte = corpo[indice + 1]
            if isinstance(seguinte, ast.Expr) and isinstance(seguinte.value, ast.Constant) \
                    and isinstance(seguinte.value.value, str):
                descricao = "string"
            elif isinstance(seguinte, ast.Expr):
                descricao = "expressão"
            else:
                descricao = "instrução"
            if seguinte.lineno in vistos:
                continue
            vistos.add(seguinte.lineno)
            achados.append((seguinte.lineno, f"{onde}: {descricao} depois do return é código morto"))

    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            olhar(getattr(no, "body", []), getattr(no, "name", None) or "<módulo>")
        elif isinstance(no, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                             ast.AsyncWith, ast.Try, ast.ExceptHandler)):
            for campo in ("body", "orelse", "finalbody"):
                corpo = getattr(no, campo, None)
                if isinstance(corpo, list) and corpo:
                    olhar(corpo, "<bloco>")
    return achados


def _corresponde(linha_arquivo: str, linha_diff: str) -> bool:
    """Compara ignorando o recuo: o git pode reindentar o que foi inserido."""
    return linha_arquivo.strip() == linha_diff.strip()


def _linhas_das_novas(linhas_arquivo: list[str], novas: list[str]) -> list[int]:
    """Números (1-based) das linhas do arquivo que são as linhas novas do diff."""
    achadas: list[int] = []
    usadas: set[int] = set()
    for nova in novas:
        for indice, linha in enumerate(linhas_arquivo, 1):
            if indice in usadas:
                continue
            if _corresponde(linha, nova):
                achadas.append(indice)
                usadas.add(indice)
                break
    return achadas


# ---------------------------------------------------------------- verificação

def verificar_diff_aplicado(diff: str, cwd: Path, instrucao: str,
                            alvos: list[str] | None = None) -> list[Achado]:
    """Achados sobre o diff JÁ APLICADO em `cwd`."""
    achados: list[Achado] = []
    arquivos = alvos or arquivos_do_diff(diff)
    funcoes_pedidas = funcoes_citadas(instrucao)
    novas = linhas_novas(diff)

    for arquivo in arquivos:
        if not arquivo.endswith(".py"):
            continue
        caminho = cwd / arquivo
        try:
            fonte = caminho.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            arvore = ast.parse(fonte)
        except SyntaxError:
            continue  # o gate já reprova sintaxe; aqui não é o lugar

        linhas_arquivo = fonte.splitlines()
        novas_no_arquivo = _linhas_das_novas(linhas_arquivo, novas)
        if not novas_no_arquivo:
            continue

        # 1. código morto (independentemente de onde a instrução pediu)
        mortos = dict(codigo_morto(arvore))
        for linha, contexto in mortos.items():
            achados.append(Achado(
                "codigo_morto", "erro",
                f"{arquivo}:{linha} — {contexto}. O código novo ficou inalcançável: "
                f"o patch provavelmente aplicou fora do lugar."))

        if not funcoes_pedidas:
            continue

        # 2. em qual função cada linha nova caiu?
        mapa = _pai_por_linha(arvore)
        for linha in novas_no_arquivo:
            if linha in mortos:
                continue  # já reportado como código morto
            escopo = mapa.get(linha, [])
            funcao_do_escopo = escopo[0] if escopo else None
            if funcao_do_escopo is None:
                continue  # linha no nível do módulo: não dá para judgingar o escopo
            for pedida in funcoes_pedidas:
                if funcao_do_escopo == pedida:
                    break
            else:
                achados.append(Achado(
                    "simbolo_em_outro_escopo", "erro",
                    f"{arquivo}:{linha} — o código novo caiu em {funcao_do_escopo}(), "
                    f"mas a instrução pediu {funcoes_pedidas[0]}()."))

        # 3. a função pedida foi alterada?
        for pedida in funcoes_pedidas:
            funcoes = {no.name: no for no in ast.walk(arvore)
                       if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))}
            alvo = funcoes.get(pedida)
            if alvo is None:
                continue
            inicio = alvo.lineno
            fim = getattr(alvo, "end_lineno", inicio)
            dentro = [l for l in novas_no_arquivo if inicio <= l <= fim]
            if not dentro:
                achados.append(Achado(
                    "funcao_nao_alterada", "erro",
                    f"{arquivo}: a função {pedida}() não recebeu nenhuma linha nova, "
                    f"mas a instrução pediu mudança nela."))

    vistos, unicos = set(), []
    for achado in achados:
        if achado.mensagem not in vistos:
            vistos.add(achado.mensagem)
            unicos.append(achado)
    return unicos


def resumo(achados: list[Achado]) -> str:
    if not achados:
        return ""
    return "; ".join(a.mensagem for a in achados[:3])
