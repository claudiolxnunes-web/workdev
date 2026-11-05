"""Checagem mecânica da Bancada: hunk sem contexto é reprovado.

Regressão de 2026-11-04: o patch sem contexto passava por `git apply --check`
(ele aplica, só que no fim do arquivo), pelo `exige` e pela checagem de
compilação. A Bancada dava "aprovada" para uma mudança que nascia errada.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"

# Hunk sem contexto: é o que o modelo local produz com frequência.
PATCH_SEM_CONTEXTO = """--- a/apps/api/app/x.py
+++ b/apps/api/app/x.py
@@ -1,0 +2 @@
+X = 2
"""

# Hunk com contexto (formato canônico do git).
PATCH_COM_CONTEXTO = """--- a/apps/api/app/x.py
+++ b/apps/api/app/x.py
@@ -1,2 +1,3 @@
 X = 1
+X = 2
 Y = 3
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def checks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "apps/api/app").mkdir(parents=True)
    (repo / "apps/api/app/x.py").write_text("X = 1\nY = 3\n")
    # `base()` extrai "apps/api/app" e "scripts" como obrigatórios.
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/s.py").write_text("S = 1\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    monkeypatch.setenv("WORKDEV_BANCADA_REPO", str(repo))
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("bancada_checks", None)
    modulo = importlib.import_module("bancada_checks")
    yield modulo, git(repo, "rev-parse", "HEAD").strip()
    sys.modules.pop("bancada_checks", None)


def _tarefa(commit: str) -> dict:
    return {"base": commit, "trechos": [["apps/api/app/x.py", 1, 2]],
            "escopo": ["apps/api/app/x.py"], "exige": {}, "espera_diff": True}


def test_patch_sem_contexto_e_reprovado(checks):
    modulo, commit = checks
    resultado = modulo.verificar(PATCH_SEM_CONTEXTO, _tarefa(commit))
    assert not resultado["aprovada"], "hunk sem contexto não pode passar nas checagens"
    assert "hunk_sem_contexto" in resultado["categorias_erro"]


def test_patch_com_contexto_passa(checks):
    modulo, commit = checks
    resultado = modulo.verificar(PATCH_COM_CONTEXTO, _tarefa(commit))
    assert resultado["aprovada"], f"patch com contexto tem de passar: {resultado['categorias_erro']}"


def test_a_mensagem_diz_como_corrigir(checks):
    modulo, commit = checks
    resultado = modulo.verificar(PATCH_SEM_CONTEXTO, _tarefa(commit))
    mensagens = [a["mensagem"] for a in resultado["achados"] if a["categoria"] == "hunk_sem_contexto"]
    assert mensagens
    assert "contexto" in mensagens[0]
    assert "unidiff-zero" in mensagens[0]


def test_a_checagem_mecanica_vem_antes_das_informativas(checks):
    """O erro de hunk sem contexto tem de aparecer mesmo com o resto em info."""
    modulo, commit = checks
    resultado = modulo.verificar(PATCH_SEM_CONTEXTO, _tarefa(commit))
    categorias = {a["categoria"]: a["severidade"] for a in resultado["achados"]}
    assert categorias.get("hunk_sem_contexto") == "erro"
