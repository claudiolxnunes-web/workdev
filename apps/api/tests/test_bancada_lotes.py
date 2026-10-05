"""Lotes da Bancada: id AAMMDD-NN, pasta única planos/ e rodar sem sobrescrever."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import bancada_runner as runner

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture
def local(tmp_path, monkeypatch):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    modulo = importlib.import_module("bancada_local")
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "x.py").write_text("".join(f"linha {i}\n" for i in range(1, 31)))
    monkeypatch.setattr(modulo, "REPO", repo)
    monkeypatch.setattr(modulo, "SAIDA", repo / "tmp" / "bancada")
    return modulo


def _plano(*ids):
    return json.dumps({"tarefas": [
        {"id": i, "instrucao": "Escreva a docstring da função do trecho abaixo.",
         "trechos": [["app/x.py", 1, 10]]} for i in ids]})


def test_proximo_lote(local, tmp_path):
    planos = tmp_path / "planos"
    assert local.proximo_lote(planos, "260105") == "260105-01"
    planos.mkdir()
    for nome in ("260105-01.json", "260105-03.json", "260104-09.json", "plano-123.json"):
        (planos / nome).write_text("{}")
    assert local.proximo_lote(planos, "260105") == "260105-04"
    assert local.proximo_lote(planos, "260106") == "260106-01"


def test_ids_genericos_levam_o_lote(local):
    plano = local._extrair_plano(_plano("1", "t2", "docstring_x", None), "260105-02")
    assert [t["id"] for t in plano["tarefas"]] == ["260105-02-01", "260105-02-02", "docstring_x", "260105-02-03"]


def test_planos_do_mesmo_dia_nao_repetem_ids(local):
    a = local._extrair_plano(_plano("1", "2"), "260105-01")
    b = local._extrair_plano(_plano("1", "2"), "260105-02")
    assert not {t["id"] for t in a["tarefas"]} & {t["id"] for t in b["tarefas"]}


def _args_rodar(arquivo, sobrescrever=False):
    return SimpleNamespace(tarefas=str(arquivo), so=None, stream=False, url="http://x",
                           timeout=1, sobrescrever=sobrescrever)


def test_rodar_pula_proposta_existente(local, monkeypatch, tmp_path, capsys):
    chamadas = []
    monkeypatch.setattr(local, "health", lambda url: True)
    monkeypatch.setattr(local, "modelo_ativo", lambda: "moe")
    monkeypatch.setattr(local, "chat", lambda url, corpo, timeout: chamadas.append(1) or
                        {"choices": [{"message": {"content": "nova"}}], "usage": {}})
    arquivo = tmp_path / "lote.json"
    arquivo.write_text(_plano("a", "b"))
    pasta = local.SAIDA / "moe"
    pasta.mkdir(parents=True)
    (pasta / "a.txt").write_text("antiga\n")

    assert local.cmd_rodar(_args_rodar(arquivo)) == 0
    assert (pasta / "a.txt").read_text() == "antiga\n"
    assert (pasta / "b.txt").read_text() == "nova\n"
    assert len(chamadas) == 1
    assert "[pulada] a" in capsys.readouterr().out

    assert local.cmd_rodar(_args_rodar(arquivo, sobrescrever=True)) == 0
    assert (pasta / "a.txt").read_text() == "nova\n"


def test_planejar_da_pagina_grava_em_planos_com_lote(tmp_path, monkeypatch, local):
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    planner = SimpleNamespace(planejar_stream=lambda *a: iter([{"tipo": "ok", "tarefas": [{"id": "x"}], "tokens": 5}]))
    monkeypatch.setattr(runner, "_modulo", lambda nome: {"bancada_planner": planner, "bancada_local": local}[nome])
    hoje = local.proximo_lote(tmp_path / "nada")[:6]

    eventos = [json.loads(e[5:]) for e in runner.planejar_stream(
        {"tarefa_id": None, "prompt": "p", "modelo": "m"})]

    assert eventos[-1]["id"] == f"{hoje}-01"
    gravado = json.loads((tmp_path / "bancada" / "planos" / f"{hoje}-01.json").read_text())
    assert gravado["lote"] == f"{hoje}-01" and gravado["tarefas"] == [{"id": "x"}]
    assert not (tmp_path / "bancada" / "planejamentos").exists()
