"""Medição da Bancada: prefill x geração, a partir do bloco `timings` do llama-server."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import bancada
from app.services import bancada_runner as runner

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"

TIMINGS = {"cache_n": 14, "prompt_n": 4, "prompt_ms": 228.4,
           "predicted_n": 2, "predicted_ms": 61.0}


@pytest.fixture
def local(tmp_path, monkeypatch):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    modulo = importlib.import_module("bancada_local")
    monkeypatch.setattr(modulo, "SAIDA", tmp_path / "bancada")
    return modulo


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "apps").mkdir(parents=True)
    (repo / "apps" / "modulo.py").write_text("def current():\n    return 1\n")
    pasta = tmp_path / "bancada"
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(pasta))
    monkeypatch.setattr(runner, "REPO_TRABALHO", repo)
    monkeypatch.setattr(runner, "chave_modelo", lambda: "moe")
    monkeypatch.setattr(runner, "commit_base", lambda raiz=None: "abc1234")
    monkeypatch.setattr(runner, "llama_no_ar", lambda: True)

    def falso_stream(mensagens, max_tokens, conhecido, vigiar):
        yield {"tipo": "token", "texto": "proposta "}
        yield {"tipo": "tokens", "tokens": 7, "medicao": {
            "prefill_ms": 228.4, "prefill_tok": 4, "cache_tok": 14, "prompt_tok": 18,
            "geracao_ms": 61.0, "geracao_tok": 2,
            "tok_s_prefill": 17.52, "tok_s_geracao": 32.79}}
    monkeypatch.setattr(runner, "_stream_llama", falso_stream)
    app = FastAPI()
    app.include_router(bancada.router, prefix="/api")
    return SimpleNamespace(cliente=TestClient(app), pasta=pasta)


def eventos(resposta) -> list[dict]:
    return [json.loads(l[5:]) for l in resposta.text.splitlines() if l.startswith("data:")]


# ---------------------------------------------------------------- a normalização

def test_timings_viram_prefill_e_geracao(local):
    medicao = local.medir_timings({"timings": TIMINGS})
    assert medicao["prefill_ms"] == 228.4 and medicao["prefill_tok"] == 4
    assert medicao["geracao_ms"] == 61.0 and medicao["geracao_tok"] == 2
    assert medicao["cache_tok"] == 14 and medicao["prompt_tok"] == 18
    assert medicao["tok_s_geracao"] == pytest.approx(32.79, abs=0.01)


def test_sem_timings_nao_medi_nada(local):
    assert local.medir_timings({}) == {}
    assert local.medir_timings({"timings": {}}) == {}
    assert local.medir_timings({"usage": {"completion_tokens": 3}}) == {}


# ---------------------------------------------------------------- a agregação

def test_agrega_prefill_e_geracao_por_modelo(local, tmp_path):
    saida = tmp_path / "bancada"
    (saida / "moe").mkdir(parents=True)
    (saida / "moe" / "_resumo.json").write_text(json.dumps({
        "t1": {"segundos": 3.0, "medicao": {"prefill_ms": 1000.0, "prefill_tok": 10, "cache_tok": 0,
                                            "prompt_tok": 10, "geracao_ms": 2000.0, "geracao_tok": 20}},
        "t2": {"segundos": 5.0, "medicao": {"prefill_ms": 3000.0, "prefill_tok": 30, "cache_tok": 10,
                                            "prompt_tok": 40, "geracao_ms": 4000.0, "geracao_tok": 40}},
        "t3": {"segundos": 9.0},  # execução sem medição: fica de fora
    }))
    linhas = local.agregar_medicoes(saida)
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["modelo"] == "moe" and linha["execucoes"] == 2
    assert linha["prefill_medio_ms"] == 2000.0 and linha["geracao_medio_ms"] == 3000.0
    assert linha["prefill_ms"] == 4000.0 and linha["geracao_ms"] == 6000.0
    assert linha["cache_pct"] == 20.0
    assert linha["tok_s_geracao"] == pytest.approx(10.0, abs=0.01)


def test_agregacao_sem_pasta_devolve_vazio(local, tmp_path):
    assert local.agregar_medicoes(tmp_path / "nao-existe") == []


# ---------------------------------------------------------------- a página

def test_execucao_grava_a_medicao(ambiente):
    resposta = ambiente.cliente.post("/api/bancada/rodar", json={
        "id": "t1", "instrucao": "Explique current().", "trechos": [["apps/modulo.py", 1, 2]]})
    assert resposta.status_code == 200
    fim = [e for e in eventos(resposta) if e["tipo"] == "fim"][0]
    assert fim["medicao"]["prefill_ms"] == 228.4
    assert fim["medicao"]["geracao_ms"] == 61.0
    resumo = json.loads((ambiente.pasta / "moe" / "_resumo.json").read_text())
    assert resumo["t1"]["medicao"]["cache_tok"] == 14
    registro = [json.loads(l) for l in (ambiente.pasta / "registro.jsonl").read_text().splitlines()]
    assert registro[-1]["medicao"]["prefill_tok"] == 4


def test_endpoint_de_medicoes(ambiente):
    ambiente.cliente.post("/api/bancada/rodar", json={
        "id": "t1", "instrucao": "Explique current().", "trechos": [["apps/modulo.py", 1, 2]]})
    resposta = ambiente.cliente.get("/api/bancada/medicoes")
    assert resposta.status_code == 200
    linhas = resposta.json()["linhas"]
    assert len(linhas) == 1
    assert linhas[0]["modelo"] == "moe" and linhas[0]["execucoes"] == 1
    assert linhas[0]["prefill_medio_ms"] == 228.4


def test_endpoint_de_medicoes_sem_nada_rodado(ambiente):
    resposta = ambiente.cliente.get("/api/bancada/medicoes")
    assert resposta.status_code == 200
    assert resposta.json()["linhas"] == []
