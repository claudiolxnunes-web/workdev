"""Testes da correção local antes do supervisor de nuvem."""
import json
import subprocess
from pathlib import Path

import pytest

from app.services import bancada_runner, build_worktree, test_gate, workspace, workspace_execucao as ex
from app.services import workspace_sessao as sessao


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    git(raiz.parent, "init", "-q", "-b", "main", str(raiz))
    git(raiz, "config", "user.name", "T")
    git(raiz, "config", "user.email", "t@x")
    git(raiz, "add", ".")
    git(raiz, "commit", "-q", "-m", "base")

    monkeypatch.setattr(workspace, "REPO", raiz)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    monkeypatch.setattr(bancada_runner, "chave_modelo", lambda: "moe")

    monkeypatch.setattr(ex, "_subtasks", lambda task_id, fatias: [f"sub-{f['n']}" for f in fatias])
    monkeypatch.setattr(ex, "_backlog", lambda acao, *args: None)
    monkeypatch.setattr(ex, "_verificar_semantica", lambda cwd, diff, instrucao, caminhos: [])
    def gate_falso(cwd, caminhos, completo=False, head=None):
        return ([test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok")], False)
    monkeypatch.setattr(ex, "_gate", gate_falso)

    class R:
        pass
    r = R()
    r.raiz = raiz
    return r


def test_correcao_local_monta_prompt_com_erro_e_diff(repo, monkeypatch):
    """_correcao_local monta prompt com erro anterior, diff e pedido de contexto."""
    pedidos = []

    def preparar_falso(pid, instrucao, trechos, max_tokens, exige, ler_repo, ferramentas, cwd):
        pedidos.append({"pid": pid, "instrucao": instrucao, "trechos": trechos})
        return {"id": pid}

    def executar_falso(plano):
        yield "data: " + json.dumps({"tipo": "inicio", "id": plano['id'], "modelo": "moe"}) + "\n\n"
        yield "data: " + json.dumps({"tipo": "fim", "id": plano['id'], "modelo": "moe", "segundos": 1.0, "leituras": 0}) + "\n\n"

    monkeypatch.setattr(bancada_runner, "preparar_execucao", preparar_falso)
    monkeypatch.setattr(bancada_runner, "executar", executar_falso)

    # Cria arquivo de resposta
    def pasta_falsa():
        p = repo.raiz.parent / "bancada" / "moe"
        p.mkdir(parents=True, exist_ok=True)
        return p.parent
    monkeypatch.setattr(bancada_runner, "pasta", pasta_falsa)

    meta = sessao.criar(task_id="t-1")
    ex.aprovar_plano(meta["id"], {"fatias": [{
        "objetivo": "f retorna 2", "instrucao": "Troque o retorno de f para 2.",
        "trechos": [["app/mod.py", 1, 2]], "gate": ["pytest"]
    }]})

    # Simula uma fatia que falhou na etapa aplicar
    meta = sessao._ler_meta(meta["id"])
    fatia = meta["plano"]["fatias"][0]
    fatia.update({
        "status": "falhou",
        "etapa": "aplicar",
        "erro_anterior": "hunk_sem_contexto",
        "diff_aplicado": "--- a/app/mod.py\n+++ b/app/mod.py\n@@ -1 +1 @@\n-def f():\n+def f():\n",
    })
    sessao._gravar_meta(meta)

    # Escreve o arquivo de resposta esperado por _correcao_local
    pid = f"ws-{meta['id']}-{fatia['id']}-local"[:80]
    (pasta_falsa() / "moe" / f"{pid}.txt").write_text("diff corrigido", encoding="utf-8")

    resultado = ex._correcao_local(meta["id"], 1)

    assert resultado == "diff corrigido"
    assert len(pedidos) == 1
    prompt = pedidos[0]["instrucao"]
    assert "hunk_sem_contexto" in prompt
    assert "3 antes e 3 depois" in prompt
    assert "def f():" in prompt
    assert "Troque o retorno de f para 2" in prompt


def test_executar_fatia_tenta_local_antes_do_supervisor(repo, monkeypatch):
    """executar_fatia emite correcao_local antes de chamar _correcao_do_supervisor."""
    correcao_local_chamada = []
    supervisor_chamado = []

    def correcao_local_falsa(ident, n):
        correcao_local_chamada.append((ident, n))
        return "correcao local"

    def correcao_supervisor_falsa(ident, n):
        supervisor_chamado.append((ident, n))
        return "correcao supervisor"

    monkeypatch.setattr(ex, "_correcao_local", correcao_local_falsa)
    monkeypatch.setattr(ex, "_correcao_do_supervisor", correcao_supervisor_falsa)

    tentativas = []

    def executar_falso(plano):
        destino = bancada_runner.pasta() / "moe"
        destino.mkdir(parents=True, exist_ok=True)
        pid = plano['id']
        if len(tentativas) == 0:
            tentativas.append(1)
            texto = "FALTA: contexto"
        else:
            texto = """```diff
--- a/app/mod.py
+++ b/app/mod.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
```"""
        (destino / f"{pid}.txt").write_text(texto, encoding="utf-8")
        yield "data: " + json.dumps({"tipo": "inicio", "id": pid, "modelo": "moe"}) + "\n\n"
        yield "data: " + json.dumps({"tipo": "fim", "id": pid, "modelo": "moe", "segundos": 1.0, "leituras": 0}) + "\n\n"
    monkeypatch.setattr(bancada_runner, "executar", executar_falso)

    meta = sessao.criar(task_id="t-1")
    ex.aprovar_plano(meta["id"], {"fatias": [{
        "objetivo": "f retorna 2", "instrucao": "Troque o retorno de f para 2.",
        "trechos": [["app/mod.py", 1, 2]], "gate": ["pytest"]
    }]})

    eventos = []
    for e in ex.executar_fatia(meta["id"], 1):
        eventos.append(json.loads(e[5:]))

    assert len(correcao_local_chamada) >= 1
    assert len(supervisor_chamado) == 0
    assert any(e.get("tipo") == "correcao_local" for e in eventos)
    assert any(e.get("tipo") == "fatia" and e.get("status") == "ok" for e in eventos)
