"""Segunda camada: o código novo caiu onde a instrução pediu?

Regressão de 2026-11-04: a docstring de `criar` foi parar depois do `return` de
`apagar_branch` — código morto. O `exige` dava verde (a string existia), o gate
dava verde (nada quebrou) e o observer dava verde (leu a proposta, não o
resultado).

`verificador_aplicado` responde com o AST do arquivo JÁ APLICADO: onde a linha
nova caiu de fato.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import verificador_aplicado as ver  # noqa: E402

ARQUIVO = "app/x.py"

DIFF_DOCSTRING = f"""--- a/{ARQUIVO}
+++ b/{ARQUIVO}
@@ -5,0 +6 @@
+    \"\"\"Cria a cópia isolada da sessão e o branch de trabalho.\"\"\"
"""

DOC = '    """Cria a cópia isolada da sessão e o branch de trabalho."""'


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app").mkdir()

    def escrever(texto: str) -> Path:
        (tmp_path / ARQUIVO).write_text(texto, encoding="utf-8")
        return tmp_path

    return escrever


# ---------------------------------------------------------------- código morto

CASO_REAL = f'''def criar(x):
    """Docstring que ja existia."""


def apagar_branch(ident):
    """Apaga."""
    return {{"id": ident}}
{DOC}
'''


def test_codigo_morto_no_caso_real(repo):
    raiz = repo(CASO_REAL)
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione uma docstring a funcao criar")
    categorias = {a.categoria for a in achados}
    assert "codigo_morto" in categorias
    assert "funcao_nao_alterada" in categorias


def test_codigo_morto_diz_o_arquivo_e_a_linha(repo):
    raiz = repo(CASO_REAL)
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione uma docstring a funcao criar")
    morto = next(a for a in achados if a.categoria == "codigo_morto")
    assert ARQUIVO in morto.mensagem
    assert "apagar_branch" in morto.mensagem


def test_codigo_correto_nao_gera_achado(repo):
    correto = f'''def criar(x):
{DOC}


def apagar_branch(ident):
    """Apaga."""
    return {{"id": ident}}
'''
    raiz = repo(correto)
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione uma docstring a funcao criar")
    assert achados == []


# ---------------------------------------------------------------- escopo

def test_linha_nova_em_outra_funcao_e_apontada(repo):
    """Código alcançável, mas no escopo errado — o caso mais traiçoeiro."""
    fonte = f'''def criar(x):
    """Docstring que ja existia."""


def apagar_branch(ident):
    """Apaga."""
{DOC}
    return {{"id": ident}}
'''
    raiz = repo(fonte)
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione uma docstring a funcao criar")
    categorias = {a.categoria for a in achados}
    assert "simbolo_em_outro_escopo" in categorias
    escopo = next(a for a in achados if a.categoria == "simbolo_em_outro_escopo")
    assert "apagar_branch" in escopo.mensagem
    assert "criar" in escopo.mensagem


def test_funcao_pedida_nao_alterada(repo):
    fonte = f'''def criar(x):
    return x


def outra():
{DOC}
'''
    raiz = repo(fonte)
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione uma docstring a funcao criar")
    assert any(a.categoria == "funcao_nao_alterada" for a in achados)


# ---------------------------------------------------------------- limites

def test_instrucao_sem_funcao_nomeada_nao_julga_escopo(repo):
    """Sem alvo nomeado não há como dizer que o escopo está errado."""
    raiz = repo("X = 1\n" + DOC + "\n")
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione o valor X = 2 no arquivo")
    assert not [a for a in achados if a.categoria in ("simbolo_em_outro_escopo", "funcao_nao_alterada")]


def test_arquivo_que_nao_existe_nao_quebra(repo):
    raiz = repo("X = 1\n")
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione a funcao criar",
                                          alvos=["app/inexistente.py"])
    assert achados == []


def test_arquivo_nao_python_e_ignorado(repo):
    raiz = repo("X = 1\n")
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione a funcao criar",
                                          alvos=["app/x.ts"])
    assert achados == []


def test_sintaxe_invalida_nao_quebra(repo):
    """Quem reprova sintaxe é o gate, não este módulo."""
    raiz = repo("def criar(:\n")
    achados = ver.verificar_diff_aplicado(DIFF_DOCSTRING, raiz, "Adicione a docstring a funcao criar")
    assert achados == []


# ---------------------------------------------------------------- unidades

def test_funcoes_citadas_le_a_instrucao():
    assert "criar" in ver.funcoes_citadas("Insira uma docstring na função `criar`")
    assert "criar" in ver.funcoes_citadas("Adicione uma docstring a funcao criar")
    assert "criar" in ver.funcoes_citadas("edite em criar(x)")


def test_linhas_novas_ignora_cabecalho():
    diff = f"--- a/{ARQUIVO}\n+++ b/{ARQUIVO}\n@@ -1,0 +2 @@\n+novo\n"
    assert ver.linhas_novas(diff) == ["novo"]


def test_resumo_vazio():
    assert ver.resumo([]) == ""


def test_achado_vira_dict_para_a_api():
    achado = ver.Achado("codigo_morto", "erro", "mensagem")
    assert achado.como_dict() == {"categoria": "codigo_morto", "severidade": "erro",
                                  "mensagem": "mensagem"}


def test_codigo_morto_em_if_e_detectado(repo):
    """Código depois do return dentro de um if também é morto."""
    import ast
    fonte = '''def f(x):
    if x:
        return 1
        print("nunca")
    return 2
'''
    mortos = ver.codigo_morto(ast.parse(fonte))
    assert mortos and mortos[0][0] == 4


def test_docstring_legitima_nao_e_codigo_morto(repo):
    import ast
    fonte = '''def f(x):
    """Docstring."""
    return 1
'''
    assert ver.codigo_morto(ast.parse(fonte)) == []
