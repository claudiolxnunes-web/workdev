"""Testes do cache determinístico de gate do Workspace Local."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import gate_cache
from app.services.test_gate import CheckResult


@pytest.fixture(autouse=True)
def _limpar_cache():
    gate_cache.limpar_tudo()
    yield
    gate_cache.limpar_tudo()


def test_chave_e_deterministica():
    c1 = gate_cache.chave("abc", ["b.py", "a.py"], ["pytest"])
    c2 = gate_cache.chave("abc", ["a.py", "b.py"], ["pytest"])
    c3 = gate_cache.chave("abc", ["a.py"], ["pytest"])
    assert c1 == c2
    assert isinstance(c1, str)
    assert len(c1) == 64
    assert c1 != c3


def test_buscar_retorna_none_sem_cache():
    assert gate_cache.buscar("head", ["a.py"], ["pytest"]) is None


def test_gravar_e_buscar():
    checks = [CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=100)]
    gate_cache.gravar("head1", ["a.py", "b.py"], ["pytest"], True, checks, "stdout")
    resultado = gate_cache.buscar("head1", ["b.py", "a.py"], ["pytest"])
    assert resultado is not None
    assert resultado.passou is True
    assert resultado.stdout == "stdout"
    assert len(resultado.checks) == 1
    assert resultado.checks[0]["name"] == "pytest"


def test_to_check_results():
    checks = [CheckResult(name="pytest", passed=True, mandatory=True, reason="ok", duration_ms=100)]
    gate_cache.gravar("head1", ["a.py"], ["pytest"], True, checks)
    resultado = gate_cache.buscar("head1", ["a.py"], ["pytest"])
    recuperados = resultado.to_check_results()
    assert len(recuperados) == 1
    assert recuperados[0].name == "pytest"
    assert recuperados[0].passed is True


def test_cache_expira_apos_ttl(monkeypatch):
    checks = [CheckResult(name="pytest", passed=True, mandatory=True, reason="ok")]
    gate_cache.gravar("head1", ["a.py"], ["pytest"], True, checks)

    # Simula passagem de 8 dias
    caminho = Path(gate_cache._arquivo(gate_cache.chave("head1", ["a.py"], ["pytest"])))
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    futuro = datetime.now(timezone.utc) - timedelta(days=8)
    dados["gravado_em"] = futuro.isoformat()
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    assert gate_cache.buscar("head1", ["a.py"], ["pytest"]) is None


def test_limpar_tudo_remove_cache():
    gate_cache.gravar("head1", ["a.py"], ["pytest"], True, [])
    gate_cache.limpar_tudo()
    assert gate_cache.buscar("head1", ["a.py"], ["pytest"]) is None
    assert not list(gate_cache.CACHE_DIR.glob("*.json"))


def test_arquivo_corrompido_e_removido():
    chave = gate_cache.chave("head1", ["a.py"], ["pytest"])
    caminho = gate_cache._arquivo(chave)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("não é json", encoding="utf-8")
    assert gate_cache.buscar("head1", ["a.py"], ["pytest"]) is None
    assert not caminho.exists()


def test_diretorio_fica_fora_do_repo():
    assert "workspace/.gate-cache" in str(gate_cache.CACHE_DIR)
