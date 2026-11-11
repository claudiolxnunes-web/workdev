"""Execução contínua de fatias: avança sozinho enquanto passa, para em falha/banco."""
import json
import subprocess
from pathlib import Path

import pytest

from app.services import workspace_execucao as ex
from app.services import workspace_sessao as sessao

# Reusa o fixture `amb` de test_workspace_execucao.py.
pytest_plugins = ["apps.api.tests.test_workspace_execucao"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


DIFF_PADRAO = """```diff
--- a/{caminho}
+++ b/{caminho}
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
```"""


def fatia(n, objetivo=None, tipo="codigo", caminho="app/mod.py", **extra):
    return {
        "id": f"f{n}",
        "objetivo": objetivo or f"fatia {n}",
        "instrucao": f"Mude {caminho}.",
        "trechos": [[caminho, 1, 5]],
        "gate": ["pytest"],
        "tipo": tipo,
        **extra,
    }


def eventos(gerador) -> list[dict]:
    return [json.loads(e[5:]) for e in gerador]


def _prepara_runner(amb, respostas: list[str]):
    amb.respostas.extend(respostas)


def _status(meta, n: int):
    return meta["plano"]["fatias"][n - 1]["status"]


def test_continuo_passa_tres_fatias_sem_clique(amb):
    amb.gate["passa"] = True
    # Cria arquivos isolados para cada fatia, com conteúdo suficiente para diff válido.
    for nome in ("a.py", "b.py", "c.py"):
        (amb.repo / "app" / nome).write_text("def f():\n    return 1\n", encoding="utf-8")
    git(amb.repo, "add", ".")
    git(amb.repo, "commit", "-q", "-m", "arquivos extras")

    plano = ex.aprovar_plano(
        sessao.criar(task_id="t-continuo")["id"],
        {"fatias": [
            fatia(1, caminho="app/a.py"),
            fatia(2, "segunda", caminho="app/b.py"),
            fatia(3, "terceira", caminho="app/c.py"),
        ]},
    )
    ident = plano["id"]
    _prepara_runner(amb, [
        DIFF_PADRAO.format(caminho="app/a.py"),
        DIFF_PADRAO.format(caminho="app/b.py"),
        DIFF_PADRAO.format(caminho="app/c.py"),
    ])

    evs = eventos(ex.executar_fatia_continua(ident, 1, None, continuo=True))

    meta = sessao._ler_meta(ident)
    assert _status(meta, 1) == "ok"
    assert _status(meta, 2) == "ok"
    assert _status(meta, 3) == "ok"
    assert amb.gate["chamadas"]
    # Evento de conclusão da execução contínua.
    assert any(e.get("tipo") == "continuo" and e.get("motivo") == "concluido" for e in evs)


def test_continuo_para_na_falha(amb):
    amb.gate["passa"] = True
    plano = ex.aprovar_plano(
        sessao.criar(task_id="t-falha")["id"],
        {"fatias": [
            fatia(1, caminho="app/mod.py"),
            fatia(2, "segunda", caminho="app/duas.py"),
        ]},
    )
    ident = plano["id"]
    # A segunda fatia não traz diff.
    _prepara_runner(amb, [DIFF_PADRAO.format(caminho="app/mod.py"), "FALTA: não sei fazer"])

    evs = eventos(ex.executar_fatia_continua(ident, 1, None, continuo=True))

    meta = sessao._ler_meta(ident)
    assert _status(meta, 1) == "ok"
    assert _status(meta, 2) == "falhou"
    paradas = [e for e in evs if e.get("tipo") == "continuo" and e.get("motivo") == "falha"]
    assert paradas


def test_continuo_para_antes_do_banco(amb):
    amb.gate["passa"] = True
    plano = ex.aprovar_plano(
        sessao.criar(task_id="t-banco")["id"],
        {"fatias": [
            fatia(1, caminho="app/mod.py"),
            {"id": "f2", "objetivo": "banco", "instrucao": "Insira um registro.",
             "trechos": [], "gate": ["select 1"], "tipo": "banco",
             "tabelas": ["backlog"], "verificacao": ["select 1"]},
        ]},
    )
    ident = plano["id"]
    _prepara_runner(amb, [DIFF_PADRAO.format(caminho="app/mod.py")])

    evs = eventos(ex.executar_fatia_continua(ident, 1, None, continuo=True))

    meta = sessao._ler_meta(ident)
    assert _status(meta, 1) == "ok"
    assert _status(meta, 2) == "pendente"
    paradas = [e for e in evs if e.get("tipo") == "continuo" and e.get("motivo") == "banco"]
    assert paradas
    assert paradas[0].get("proxima") == 2


def test_continuo_desligado_executa_somente_a_fatia_solicitada(amb):
    amb.gate["passa"] = True
    plano = ex.aprovar_plano(
        sessao.criar(task_id="t-uma")["id"],
        {"fatias": [
            fatia(1, caminho="app/mod.py"),
            fatia(2, "segunda", caminho="app/duas.py"),
        ]},
    )
    ident = plano["id"]
    _prepara_runner(amb, [DIFF_PADRAO.format(caminho="app/mod.py")])

    evs = eventos(ex.executar_fatia_continua(ident, 1, None, continuo=False))

    meta = sessao._ler_meta(ident)
    assert _status(meta, 1) == "ok"
    assert _status(meta, 2) == "pendente"
    assert not any(e.get("tipo") == "continuo" for e in evs)
