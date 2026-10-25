"""Escolha do modelo local: opcoes e troca.

O llama-server é compartilhado pela Bancada, pelo chat do Workspace e pelo
agente local-code. A troca reinicia o serviço quando ele está ligado e é
recusada enquanto o local-code tem trabalho em andamento.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import bancada
from app.services import local_model


@pytest.fixture
def cliente():
    app = FastAPI()
    app.include_router(bancada.router, prefix="/api")
    return TestClient(app)


def test_opcoes_listam_todos_os_modelos_locais(cliente):
    resposta = cliente.get("/api/bancada/modelo/opcoes")

    assert resposta.status_code == 200
    corpo = resposta.json()
    chaves = {m["chave"] for m in corpo["modelos"]}
    assert chaves == set(local_model.MODELS)
    assert all(m["label"] for m in corpo["modelos"])
    # O padrão é o MoE de 35B, como o operador definiu.
    assert local_model.DEFAULT_MODEL == "moe"


def test_trocar_modelo_desconhecido_recusa(cliente):
    resposta = cliente.post("/api/bancada/modelo/trocar", json={"chave": "nao-existe"})

    assert resposta.status_code == 409
    assert resposta.json()["detail"]["code"] == "model_unknown"


def test_trocar_modelo_grava_a_escolha_e_relata_o_estado(cliente, monkeypatch, tmp_path):
    arquivo = tmp_path / "modelo"
    monkeypatch.setattr(local_model, "KEY_FILE", arquivo)
    trocas = []

    def fake_switch(chave, db):
        trocas.append(chave)
        return {"model": chave, "switched": True, "restarted": False}

    monkeypatch.setattr(local_model, "switch", fake_switch)

    resposta = cliente.post("/api/bancada/modelo/trocar", json={"chave": "q27"})

    assert resposta.status_code == 200
    assert resposta.json() == {"model": "q27", "switched": True, "restarted": False}
    assert trocas == ["q27"]


def test_trocar_modelo_recusa_quando_o_local_code_esta_ocupado(cliente, monkeypatch):
    def fake_switch(chave, db):
        raise local_model.SwitchError("agent_busy", "local-code tem trabalho ativo")

    monkeypatch.setattr(local_model, "switch", fake_switch)

    resposta = cliente.post("/api/bancada/modelo/trocar", json={"chave": "fast"})

    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert detalhe["code"] == "agent_busy"
    assert "trabalho ativo" in detalhe["message"]
