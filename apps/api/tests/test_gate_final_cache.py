"""Testes de persistência do gate final entre sessões do Workspace Local."""
from pathlib import Path

import pytest

from app.services import gate_cache, test_gate, workspace_execucao as ex


@pytest.fixture(autouse=True)
def _limpar_cache():
    gate_cache.limpar_tudo()
    yield
    gate_cache.limpar_tudo()


def test_gate_final_reaproveia_cache_compartilhado(tmp_path, monkeypatch):
    """Se o cache compartilhado já tem o gate final para aquele HEAD, _gate_final não reexecuta pytest."""
    head = "abc123"
    caminhos = ["apps/api/app.py"]
    checks = [test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)]

    # Preenche o cache como se outra sessão já tivesse rodado o gate final
    gate_cache.gravar(head, caminhos, ["pytest:None"], True, checks)

    chamadas_pytest = []

    def guardrails(paths):
        return test_gate.CheckResult(name="guardrails", passed=True, mandatory=True, reason="ok")

    def pytest_check(paths, env=None, alvos=None):
        chamadas_pytest.append(alvos)
        return test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)

    monkeypatch.setattr(test_gate, "_check_guardrails", guardrails)
    monkeypatch.setattr(test_gate, "_check_pytest", pytest_check)

    meta = {"id": "261110-000000-test", "caminho": str(tmp_path), "base": "base123", "branch": "workspace/x"}

    def git_mock(args, cwd):
        class R:
            pass
        r = R()
        if args[0] == "rev-parse":
            r.stdout = head + "\n"
        else:
            r.stdout = "\n".join(caminhos) + "\n"
        return r

    monkeypatch.setattr(ex, "_git", git_mock)

    ex._gate_final(meta)

    assert meta["gate_final"]["passou"] is True
    assert meta["gate_final"].get("cache_hit") is True
    assert len(chamadas_pytest) == 0


def test_gate_final_grava_cache_quando_miss(tmp_path, monkeypatch):
    """Quando não há cache, _gate_final executa e o resultado fica persistido no cache compartilhado."""
    head = "def456"
    caminhos = ["apps/api/app.py"]

    chamadas_pytest = []

    def guardrails(paths):
        return test_gate.CheckResult(name="guardrails", passed=True, mandatory=True, reason="ok")

    def pytest_check(paths, env=None, alvos=None):
        chamadas_pytest.append(alvos)
        return test_gate.CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=50)

    monkeypatch.setattr(test_gate, "_check_guardrails", guardrails)
    monkeypatch.setattr(test_gate, "_check_pytest", pytest_check)

    meta = {"id": "261110-000001-test", "caminho": str(tmp_path), "base": "base123", "branch": "workspace/x"}

    def git_mock(args, cwd):
        class R:
            pass
        r = R()
        if args[0] == "rev-parse":
            r.stdout = head + "\n"
        else:
            r.stdout = "\n".join(caminhos) + "\n"
        return r

    monkeypatch.setattr(ex, "_git", git_mock)

    ex._gate_final(meta)

    assert meta["gate_final"]["passou"] is True
    assert meta["gate_final"].get("cache_hit") is False
    assert len(chamadas_pytest) == 1

    # Segunda chamada deve bater no cache
    meta2 = {"id": "261110-000002-test", "caminho": str(tmp_path), "base": "base123", "branch": "workspace/x"}
    ex._gate_final(meta2)
    assert meta2["gate_final"].get("cache_hit") is True
    assert len(chamadas_pytest) == 1
