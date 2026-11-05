"""Validação de hunks: nenhum patch sem âncora é aplicado.

Regressão de 2026-11-04: um hunk sem contexto (`@@ -172,0 +173 @@`) passou
pelo `git apply --check`, pelo `exige`, pelo pytest e pela auditoria do
observer — e aplicou a docstring no FIM do arquivo, depois do `return`. Código
morto, quatro camadas verdes.

Estes testes travam o comportamento: hunk sem contexto é recusado antes de
qualquer `git apply`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import hunk_validator  # noqa: E402

# O caso real do Workspace Local: hunk sem contexto.
HUNK_SEM_CONTEXTO = """--- a/apps/api/app/services/workspace_sessao.py
+++ b/apps/api/app/services/workspace_sessao.py
@@ -172,0 +173 @@
+    \"\"\"Cria a cópia isolada da sessão e o branch de trabalho.\"\"\"
"""

# Diff com contexto (formato canonico do git: 3 linhas de contexto de cada lado).
HUNK_COM_CONTEXTO = """--- a/app/mod.py
+++ b/app/mod.py
@@ -1,2 +1,3 @@
 def f():
+    \"\"\"doc\"\"\"
     return 1
"""

# Diff real, gerado pelo git.
DIFF_REAL = """--- a/app/mod.py
+++ b/app/mod.py
@@ -47,7 +47,7 @@ linha46
 linha47
 linha48
 linha49
-linha50
+linha50 MUDADA
 linha51
 linha52
 linha53
"""


class TestValidarHunks:
    def test_hunk_sem_contexto_e_recusado(self):
        problemas = hunk_validator.validar_hunks(HUNK_SEM_CONTEXTO)
        assert problemas, "hunk sem contexto tem de ser recusado"
        assert problemas[0].codigo == "hunk_sem_contexto"
        assert "âncora" in problemas[0].mensagem

    def test_mensagem_explica_o_jeito_de_sair(self):
        problema = hunk_validator.validar_hunks(HUNK_SEM_CONTEXTO)[0]
        assert "contexto" in problema.mensagem
        assert "unidiff-zero" in problema.mensagem

    def test_hunk_com_contexto_passa(self):
        assert hunk_validator.validar_hunks(HUNK_COM_CONTEXTO) == []

    def test_diff_real_passa(self):
        assert hunk_validator.validar_hunks(DIFF_REAL) == []

    def test_diff_vazio_nao_quebra(self):
        assert hunk_validator.validar_hunks("") == []
        assert hunk_validator.validar_hunks("sem diff nenhum") == []

    def test_texto_que_nao_e_diff_nao_quebra(self):
        assert hunk_validator.validar_hunks("FALTA: o trecho do arquivo") == []

    def test_contagem_incoerente_e_detectada(self):
        diff = """--- a/app/mod.py
+++ b/app/mod.py
@@ -1,9 +1,4 @@
 def f():
     return 1
"""
        problemas = hunk_validator.validar_hunks(diff)
        assert problemas
        assert problemas[0].codigo == "hunk_contagem_incoerente"

    def test_problema_carrega_o_arquivo(self):
        problemas = hunk_validator.validar_hunks(HUNK_SEM_CONTEXTO)
        assert problemas[0].arquivo == "apps/api/app/services/workspace_sessao.py"

    def test_resumo_de_um_problema(self):
        problemas = hunk_validator.validar_hunks(HUNK_SEM_CONTEXTO)
        assert hunk_validator.resumo(problemas) == problemas[0].mensagem

    def test_resumo_de_varios_problemas(self):
        diff = HUNK_SEM_CONTEXTO + HUNK_SEM_CONTEXTO.replace("workspace_sessao.py", "outro.py")
        problemas = hunk_validator.validar_hunks(diff)
        assert len(problemas) == 2
        assert "2 problema(s)" in hunk_validator.resumo(problemas)

    def test_resumo_vazio(self):
        assert hunk_validator.resumo([]) == ""


class TestDiffTemContexto:
    def test_sem_contexto(self):
        assert hunk_validator.diff_tem_contexto(HUNK_SEM_CONTEXTO) is False

    def test_com_contexto(self):
        assert hunk_validator.diff_tem_contexto(DIFF_REAL) is True


class TestComportamentoDoGit:
    """Confirma o fato que motivou o módulo: sem contexto, o git joga no fim."""

    @pytest.fixture
    def repo(self, tmp_path):
        raiz = tmp_path / "repo"
        raiz.mkdir()
        (raiz / "a.py").write_text("\n".join(f"linha{i}" for i in range(1, 101)) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(raiz)], check=True)
        for chave, valor in (("user.name", "t"), ("user.email", "t@t")):
            subprocess.run(["git", "-C", str(raiz), "config", chave, valor], check=True)
        subprocess.run(["git", "-C", str(raiz), "add", "."], check=True)
        subprocess.run(["git", "-C", str(raiz), "commit", "-q", "-m", "base"], check=True)
        return raiz

    def test_git_apply_sem_contexto_ignora_a_posicao_declarada(self, repo):
        patch = repo / "p.patch"
        patch.write_text("--- a/a.py\n+++ b/a.py\n@@ -50,0 +51 @@\n+x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "apply", "--recount", str(patch)], check=True)
        onde = [i for i, linha in enumerate((repo / "a.py").read_text(encoding="utf-8").splitlines(), 1)
                if linha == "x"]
        # Declarado: linha 51. Sem contexto, o git aplica no fim do arquivo.
        assert onde == [101], "sem contexto, o git aplica no fim — é o bug que o módulo impede"

    def test_git_apply_com_contexto_ancora_pelo_conteudo(self, repo):
        patch = repo / "p.patch"
        patch.write_text(
            "--- a/a.py\n+++ b/a.py\n@@ -47,7 +47,7 @@ linha46\n"
            " linha47\n linha48\n linha49\n-linha50\n+linha50 MUDADA\n"
            " linha51\n linha52\n linha53\n",
            encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "apply", "--recount", str(patch)], check=True)
        onde = [i for i, linha in enumerate((repo / "a.py").read_text(encoding="utf-8").splitlines(), 1)
                if linha == "linha50 MUDADA"]
        assert onde == [50], "com contexto, a mudanca vai onde o contexto casa"

    def test_git_apply_com_contexto_busca_o_trecho_e_aplica_onde_casa(self, repo):
        # Com contexto, o git acha o trecho no arquivo e aplica ONDE ELE CASAR,
        # ignorando a posicao declarada. E a ancora que o hunk sem contexto nao
        # tem -- e a razao de o hunk sem contexto ser perigoso.
        patch = repo / "p.patch"
        patch.write_text(
            "--- a/a.py\n+++ b/a.py\n@@ -8,7 +8,7 @@ linha7\n"
            " linha47\n linha48\n linha49\n-linha50\n+linha50 MUDADA\n"
            " linha51\n linha52\n linha53\n",
            encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "apply", "--recount", str(patch)], check=True)
        onde = [i for i, linha in enumerate((repo / "a.py").read_text(encoding="utf-8").splitlines(), 1)
                if linha == "linha50 MUDADA"]
        assert onde == [50], "com contexto, o git aplica onde o trecho casa"

    def test_git_apply_com_contexto_reprova_quando_o_trecho_nao_existe(self, repo):
        # Contexto que nao existe em lugar nenhum: o --check tem de reprovar.
        patch = repo / "p.patch"
        patch.write_text(
            "--- a/a.py\n+++ b/a.py\n@@ -8,7 +8,7 @@ linha7\n"
            " linhaX1\n linhaX2\n linhaX3\n-linhaX4\n+linhaX4 MUDADA\n"
            " linhaX5\n linhaX6\n linhaX7\n",
            encoding="utf-8")
        resultado = subprocess.run(["git", "-C", str(repo), "apply", "--check", "--recount", str(patch)],
                                   capture_output=True, text=True)
        assert resultado.returncode != 0, "contexto inexistente tem de ser recusado"

