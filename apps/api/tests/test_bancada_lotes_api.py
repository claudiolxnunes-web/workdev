"""POST/GET /api/bancada/lotes: o plano do AI Hub vira lote gravado, sem copiar e colar."""
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import bancada
from app.services import bancada_runner as runner

HOJE = datetime.now().strftime("%y%m%d")


@pytest.fixture
def api(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "mod.py").write_text("".join(f"linha {i}\n" for i in range(1, 101)))
    monkeypatch.setattr(runner, "REPO_TRABALHO", repo)
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    app = FastAPI()
    app.include_router(bancada.router, prefix="/api")
    return TestClient(app), tmp_path / "bancada" / "planos"


def _plano(n, ids=None):
    ids = ids or [""] * n
    return {"tarefas": [{"id": ids[i], "instrucao": "Escreva a docstring da função do trecho abaixo.",
                         "trechos": [["app/mod.py", 1, 10]]} for i in range(n)]}


def test_grava_um_lote_e_devolve_para_a_pagina(api):
    cliente, planos = api
    r = cliente.post("/api/bancada/lotes", json={"plano": _plano(2)})
    assert r.status_code == 201
    assert r.json() == {"lotes": [{"lote": f"{HOJE}-01", "tarefas": 2}]}
    gravado = json.loads((planos / f"{HOJE}-01.json").read_text())
    assert gravado["origem"] == "ai_hub" and [t["id"] for t in gravado["tarefas"]] == [f"{HOJE}-01-01", f"{HOJE}-01-02"]

    lido = cliente.get(f"/api/bancada/lotes/{HOJE}-01").json()
    assert lido["lote"] == f"{HOJE}-01" and len(lido["tarefas"]) == 2


def test_plano_grande_vira_dois_lotes(api):
    cliente, _ = api
    r = cliente.post("/api/bancada/lotes", json={"plano": _plano(13)})
    assert r.json()["lotes"] == [{"lote": f"{HOJE}-01", "tarefas": 7}, {"lote": f"{HOJE}-02", "tarefas": 6}]


def test_ids_de_previa_sao_refeitos_com_o_lote_real(api):
    cliente, planos = api
    cliente.post("/api/bancada/lotes", json={"plano": _plano(1)})  # ocupa o -01
    previa = _plano(2, [f"{HOJE}-01-01", "doc_descritivo"])

    r = cliente.post("/api/bancada/lotes", json={"plano": previa})

    assert r.json()["lotes"][0]["lote"] == f"{HOJE}-02"
    ids = [t["id"] for t in json.loads((planos / f"{HOJE}-02.json").read_text())["tarefas"]]
    assert ids == [f"{HOJE}-02-01", "doc_descritivo"]


@pytest.mark.parametrize("plano, codigo", [
    ({"tarefas": [], "fora_do_alcance": "migração"}, "fora_do_alcance"),
    ({"tarefas": [{"id": "", "instrucao": "Escreva a docstring da função.", "trechos": [["app/mod.py", 1, 500]]}]},
     "plano_invalido"),
    (_plano(21), "plano_invalido"),
])
def test_recusa_sem_gravar(api, plano, codigo):
    cliente, planos = api
    r = cliente.post("/api/bancada/lotes", json={"plano": plano})
    assert r.status_code == 422 and r.json()["detail"]["code"] == codigo
    assert not planos.exists()


@pytest.mark.parametrize("lote, status", [("../x", 404), ("abc", 400), (f"{HOJE}-09", 404)])
def test_get_lote_so_le_lote_valido(api, lote, status):
    cliente, _ = api
    assert cliente.get(f"/api/bancada/lotes/{lote}").status_code == status
