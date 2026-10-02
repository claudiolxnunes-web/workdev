"""bancada_checks.base: núcleo (apps/api/app + scripts) + escopo da tarefa sob demanda."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def checks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for caminho, texto in {
        "apps/api/app/x.py": "X = 1\n",
        "scripts/s.py": "S = 1\n",
        "apps/web/src/A.tsx": "export const a = 1\nexport const b = 2\n",
    }.items():
        (repo / caminho).parent.mkdir(parents=True, exist_ok=True)
        (repo / caminho).write_text(texto)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    monkeypatch.setenv("WORKDEV_BANCADA_REPO", str(repo))
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("bancada_checks", None)
    modulo = importlib.import_module("bancada_checks")
    yield modulo, git(repo, "rev-parse", "--short=12", "HEAD").strip()
    sys.modules.pop("bancada_checks", None)


def test_base_extrai_nucleo_e_escopo_sob_demanda(checks):
    modulo, commit = checks
    raiz = modulo.base(commit)
    assert (raiz / "apps/api/app/x.py").exists() and (raiz / "scripts/s.py").exists()
    assert not (raiz / "apps/web/src/A.tsx").exists()
    raiz = modulo.base(commit, ["apps/web/src/A.tsx", "apps/web/src/novo.tsx", "../fora.txt", "/etc/passwd"])
    assert (raiz / "apps/web/src/A.tsx").read_text().startswith("export const a")
    assert not (raiz / "apps/web/src/novo.tsx").exists()
    assert not (raiz.parent / "fora.txt").exists()


def test_verificar_aplica_diff_de_frontend(checks):
    modulo, commit = checks
    proposta = (
        "--- a/apps/web/src/A.tsx\n+++ b/apps/web/src/A.tsx\n"
        "@@ -1,2 +1,2 @@\n export const a = 1\n-export const b = 2\n+export const b = 3\n"
    )
    resultado = modulo.verificar(proposta, {"base": commit, "escopo": ["apps/web/src/A.tsx"],
                                            "trechos": [["apps/web/src/A.tsx", 1, 2]], "espera_diff": True})
    assert "diff_nao_aplica" not in resultado["categorias_erro"], resultado["achados"]
