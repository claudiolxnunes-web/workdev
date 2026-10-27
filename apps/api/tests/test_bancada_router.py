"""Bancada Local: API só GET, presa à pasta da Bancada."""
import json
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import bancada

CHAVE_FALSA = "-".join(["sk", "or", "v1", "abcdefghijklmnop"])


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    raiz = tmp_path / "bancada"
    (raiz / "moe").mkdir(parents=True)
    # Chave falsa montada em partes: o arquivo não contém nada com cara de chave.
    (raiz / "moe" / "t1.txt").write_text("proposta do moe " + CHAVE_FALSA, encoding="utf-8")
    (raiz / "moe" / "_resumo.json").write_text(json.dumps({"t1": {"segundos": 12.5, "tokens": 40}}))
    (raiz / "_base" / "e66f298").mkdir(parents=True)
    (raiz / "_base" / "e66f298" / "segredo.txt").write_text("não pode sair")
    (raiz / "verificacoes").mkdir()
    (raiz / "verificacoes" / "c1.json").write_text(json.dumps({
        "id": "c1", "modelo": "dev", "tarefa": "minimo", "esperado": "correcao_pequena",
        "proposta": "local_model.current()", "erros": 1, "aprovada": False,
        "achados": [{"categoria": "uso_errado", "severidade": "erro", "mensagem": "objeto errado"},
                    {"categoria": "diff_nao_aplica", "severidade": "info", "mensagem": "ok"}]}))
    (raiz / "pareceres").mkdir()
    (raiz / "pareceres" / "c1__deepseek--deepseek-v4-flash.json").write_text(json.dumps({
        "id": "c1", "modelo": "dev", "observer": "deepseek/deepseek-v4-flash", "ok": True,
        "parecer": {"veredito": "correcao_pequena", "erros": [{"categoria": "uso_errado", "descricao": "x"}],
                    "prompt_correcao": "Use from app.services import local_model"},
        "custo_usd": 0.0002, "segundos": 3.1, "falhas": []}))
    (raiz / "registro.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"id": "t1", "modelo": "moe", "veredito": "aproveitada", "origem": "operador"},
        {"id": "c1", "modelo": "dev", "veredito": "correcao_pequena", "origem": "observer",
         "observer": "deepseek/deepseek-v4-flash"},
        {"id": "c1", "modelo": "dev", "veredito": "falhou", "origem": "observer", "observer": "moonshotai/kimi-k2.6"},
    ]) + "\n")
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(raiz))
    app = FastAPI()
    app.include_router(bancada.router, prefix="/api")
    return TestClient(app)


def test_lista_propostas_do_modelo_e_do_corpus_sem_pastas_internas(pasta):
    itens = pasta.get("/api/bancada/propostas").json()["propostas"]
    assert {(i["modelo"], i["id"], i["origem"]) for i in itens} == {("moe", "t1", "rodar"), ("dev", "c1", "corpus")}
    c1 = next(i for i in itens if i["id"] == "c1")
    assert c1["achados"] == {"erro": 1, "aviso": 0, "info": 1}
    assert {o["observer"] for o in c1["observers"]} == {"deepseek/deepseek-v4-flash", "moonshotai/kimi-k2.6"}


def test_detalhe_traz_verificacao_parecer_e_prompt_e_mascara_chave(pasta):
    corpo = pasta.get("/api/bancada/propostas/dev/c1").json()
    assert corpo["texto"] == "local_model.current()"
    assert corpo["verificacao"]["erros"] == 1
    assert corpo["pareceres"][0]["prompt_correcao"] == "Use from app.services import local_model"
    texto = pasta.get("/api/bancada/propostas/moe/t1").json()["texto"]
    assert CHAVE_FALSA not in texto and "[mascarado]" in texto


@pytest.mark.parametrize("caminho", [
    "/api/bancada/propostas/_base/segredo",
    "/api/bancada/propostas/moe/..%2F..%2Fetc",
    "/api/bancada/propostas/moe/t1.env",
    "/api/bancada/propostas/..%2F_base/x",
])
def test_recusa_fora_da_pasta_e_pastas_internas(pasta, caminho):
    resposta = pasta.get(caminho)
    assert resposta.status_code in (400, 404)
    assert "não pode sair" not in resposta.text


def test_so_aceita_get(pasta):
    for metodo in ("post", "put", "patch", "delete"):
        assert getattr(pasta, metodo)("/api/bancada/propostas").status_code == 405


def test_resumo_separa_operador_e_observer(pasta):
    linhas = pasta.get("/api/bancada/resumo").json()["linhas"]
    por_quem = {(l["modelo"], l["avaliado_por"]): l for l in linhas}
    assert por_quem[("moe", "operador")]["aproveitada"] == 100
    assert por_quem[("moe", "operador")]["tempo_medio_s"] == 12.5
    assert por_quem[("dev", "moonshotai/kimi-k2.6")]["falhas"] == 1


def test_estado_mostra_indisponivel_em_vez_de_erro(pasta, monkeypatch):
    def falha(*_a, **_k):
        raise subprocess.SubprocessError("sem systemctl")
    monkeypatch.setattr(bancada.subprocess, "run", falha)
    monkeypatch.setattr(bancada, "LLAMA_KEY_FILE", bancada.Path("/nao/existe"))
    resposta = pasta.get("/api/bancada/estado")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["ativo"] is None and corpo["processo_mb"] is None and corpo["chave"] is None
    assert corpo["pasta_existe"] is True


def test_endpoints_exigem_login_no_app_real():
    from app.main import app
    with TestClient(app) as cliente:
        assert cliente.get("/api/bancada/estado").status_code == 401
