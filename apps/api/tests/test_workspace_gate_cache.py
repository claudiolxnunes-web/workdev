"""Testes da integração do gate_cache no workspace_execucao."""
import json
from pathlib import Path

import pytest

from app.services import gate_cache, test_gate, workspace_execucao as ex


def test_gate_busca_e_grava_no_cache(tmp_path, monkeypatch):
    """_gate consulta o cache; em miss executa, grava e retorna cache_hit=False."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    (raiz / "apps" / "api" / "tests").mkdir(parents=True)
    (raiz / "apps" / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")

    gravado = []

    def guardrails(paths):
        return test_gate.CheckResult(name="guardrails", passed=True, mandatory=True, reason="ok")

    def pytest_falso(paths, env, alvos):
        return test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)

    monkeypatch.setattr(test_gate, "_check_guardrails", guardrails)
    monkeypatch.setattr(test_gate, "_check_pytest", pytest_falso)
    monkeypatch.setattr(ex, "_git", lambda args, cwd: type("R", (), {"stdout": "abc123\n"})())

    original_gravar = gate_cache.gravar
    def gravar_fake(head, caminhos, comandos, passou, checks, stdout=""):
        gravado.append((head, caminhos, comandos, passou))
        return original_gravar(head, caminhos, comandos, passou, checks, stdout)
    monkeypatch.setattr(gate_cache, "gravar", gravar_fake)

    resultados, cache_hit = ex._gate(raiz, ["apps/api/app.py"])
    assert len(resultados) == 2
    assert resultados[0].name == "guardrails"
    assert resultados[1].name == "pytest"
    assert cache_hit is False
    assert len(gravado) == 1
    assert gravado[0][3] is True


def test_gate_retorna_cache_hit_na_segunda_chamada(tmp_path, monkeypatch):
    """Segunda chamada com mesma chave reaproveita o cache."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    (raiz / "apps" / "api" / "tests").mkdir(parents=True)
    (raiz / "apps" / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")

    def guardrails(paths):
        return test_gate.CheckResult(name="guardrails", passed=True, mandatory=True, reason="ok")

    chamadas_pytest = []

    def pytest_falso(paths, env, alvos):
        chamadas_pytest.append(alvos)
        return test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)

    monkeypatch.setattr(test_gate, "_check_guardrails", guardrails)
    monkeypatch.setattr(test_gate, "_check_pytest", pytest_falso)
    monkeypatch.setattr(ex, "_git", lambda args, cwd: type("R", (), {"stdout": "abc123\n"})())

    gate_cache.limpar_tudo()

    r1, hit1 = ex._gate(raiz, ["apps/api/app.py"])
    r2, hit2 = ex._gate(raiz, ["apps/api/app.py"])

    assert hit1 is False
    assert hit2 is True
    assert len(chamadas_pytest) == 1
    assert r1[1].name == "pytest"
    assert r2[1].name == "pytest"


def test_sse_gate_contem_cache_hit(tmp_path, monkeypatch):
    """O evento SSE da etapa gate inclui a flag cache_hit."""
    from app.services import bancada_runner, build_worktree, workspace, workspace_sessao as sessao

    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    def git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()
    import subprocess
    git(raiz.parent, "init", "-q", "-b", "main", str(raiz))
    git(raiz, "config", "user.name", "T")
    git(raiz, "config", "user.email", "t@x")
    git(raiz, "add", ".")
    git(raiz, "commit", "-q", "-m", "base")

    monkeypatch.setattr(workspace, "REPO", raiz)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    monkeypatch.setattr(bancada_runner, "chave_modelo", lambda: "moe")

    def executar_falso(plano):
        destino = bancada_runner.pasta() / "moe"
        destino.mkdir(parents=True, exist_ok=True)
        texto = """```diff\n--- a/app/mod.py\n+++ b/app/mod.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n```"""
        (destino / f"{plano['id']}.txt").write_text(texto, encoding="utf-8")
        yield "data: " + json.dumps({"tipo": "inicio", "id": plano["id"], "modelo": "moe"}) + "\n\n"
        yield "data: " + json.dumps({"tipo": "fim", "id": plano['id'], "modelo": "moe", "segundos": 1.0, "leituras": 0}) + "\n\n"
    monkeypatch.setattr(bancada_runner, "executar", executar_falso)

    def guardrails(paths):
        return test_gate.CheckResult(name="guardrails", passed=True, mandatory=True, reason="ok")

    def pytest_falso(paths, env, alvos):
        return test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)

    monkeypatch.setattr(test_gate, "_check_guardrails", guardrails)
    monkeypatch.setattr(test_gate, "_check_pytest", pytest_falso)
    monkeypatch.setattr(ex, "_subtasks", lambda task_id, fatias: [f"sub-{f['n']}" for f in fatias])
    monkeypatch.setattr(ex, "_backlog", lambda acao, *args: None)

    gate_cache.limpar_tudo()

    meta = sessao.criar(task_id="t-1")
    plano = ex.aprovar_plano(meta["id"], {"fatias": [{
        "objetivo": "f retorna 2", "instrucao": "Troque o retorno de f para 2.",
        "trechos": [["app/mod.py", 1, 2]], "gate": ["pytest"]
    }]})

    eventos = [json.loads(e[5:]) for e in ex.executar_fatia(meta["id"], 1)]
    gates = [e for e in eventos if e.get("tipo") == "gate"]
    assert len(gates) == 1
    assert gates[0].get("cache_hit") is False
