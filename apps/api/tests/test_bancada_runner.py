"""Bancada Local, segunda etapa: execuções por clique, uma por vez, sem aplicar nada."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import bancada
from app.services import bancada_runner as runner


def eventos(resposta) -> list[dict]:
    return [json.loads(l[5:]) for l in resposta.text.splitlines() if l.startswith("data:")]


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "apps").mkdir(parents=True)
    (repo / "apps" / "modulo.py").write_text("AGENT = 'x'\ndef current():\n    return AGENT\n")
    (repo / ".env").write_text("SEGREDO=1\n")
    pasta = tmp_path / "bancada"
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(pasta))
    monkeypatch.setattr(runner, "REPO_TRABALHO", repo)
    monkeypatch.setattr(runner, "chave_modelo", lambda: "moe")
    monkeypatch.setattr(runner, "commit_base", lambda: "abc1234")
    monkeypatch.setattr(runner, "llama_no_ar", lambda: True)
    roteiro = {"partes": [[{"tipo": "token", "texto": "proposta "}, {"tipo": "token", "texto": "ok\n"},
                           {"tipo": "tokens", "tokens": 7}]]}

    def falso_stream(mensagens, max_tokens, conhecido, vigiar):
        roteiro.setdefault("mensagens", []).append(mensagens)
        yield from roteiro["partes"].pop(0)
    monkeypatch.setattr(runner, "_stream_llama", falso_stream)
    app = FastAPI()
    app.include_router(bancada.router, prefix="/api")
    return SimpleNamespace(cliente=TestClient(app), pasta=pasta, roteiro=roteiro)


def rodar(cliente, ident="t1", **extra):
    corpo = {"id": ident, "instrucao": "Explique current().", "trechos": [["apps/modulo.py", 1, 3]], **extra}
    return cliente.post("/api/bancada/rodar", json=corpo)


def test_rodar_transmite_tokens_e_grava_so_em_tmp_bancada(ambiente):
    resposta = rodar(ambiente.cliente)
    assert resposta.status_code == 200
    tipos = [e["tipo"] for e in eventos(resposta)]
    assert tipos == ["inicio", "token", "token", "fim"]
    assert (ambiente.pasta / "moe" / "t1.txt").read_text() == "proposta ok\n"
    meta = json.loads((ambiente.pasta / "tarefas" / "t1.json").read_text())
    assert meta["base"] == "abc1234" and meta["trechos"] == [["apps/modulo.py", 1, 3]]
    assert "def current" in meta["prompt"]
    registro = [json.loads(l) for l in (ambiente.pasta / "registro.jsonl").read_text().splitlines()]
    assert registro[-1]["origem"] == "pagina" and registro[-1]["tipo"] == "execucao"


def test_vigia_interrompe_e_reenvia_uma_vez(ambiente):
    ambiente.roteiro["partes"] = [
        [{"tipo": "token", "texto": "agent.inventada()\n"}, {"tipo": "interrompido", "nomes": ["agent.inventada"], "tokens": 3}],
        [{"tipo": "token", "texto": "FALTA: não há função para isso\n"}, {"tipo": "tokens", "tokens": 9}],
    ]
    tipos = [e["tipo"] for e in eventos(rodar(ambiente.cliente))]
    assert tipos == ["inicio", "token", "vigia", "reinicio", "token", "fim"]
    assert (ambiente.pasta / "moe" / "t1.txt").read_text().startswith("FALTA")
    assert "`agent.inventada` não existe" in ambiente.roteiro["mensagens"][1][-1]["content"]


def test_uma_execucao_por_vez(ambiente):
    with runner._lock_execucao():
        assert rodar(ambiente.cliente).status_code == 409


def test_modelo_desligado_vira_evento_claro(ambiente, monkeypatch):
    monkeypatch.setattr(runner, "llama_no_ar", lambda: False)
    corpo = eventos(rodar(ambiente.cliente))
    assert corpo == [{"tipo": "erro", "codigo": "modelo_desligado", "mensagem": "O modelo local está desligado. Use Ligar."}]
    assert not (ambiente.pasta / "moe").exists()


@pytest.mark.parametrize("trecho,codigo", [
    ([".env", 1, 1], "trecho_bloqueado"),
    (["../fora.py", 1, 1], "trecho_invalido"),
])
def test_trechos_proibidos_sao_recusados(ambiente, trecho, codigo):
    resposta = ambiente.cliente.post("/api/bancada/rodar", json={"id": "x", "instrucao": "y", "trechos": [trecho]})
    assert resposta.status_code == 422
    assert resposta.json()["detail"]["code"] == codigo
    assert "SEGREDO" not in resposta.text


def test_id_repetido_e_invalido(ambiente):
    rodar(ambiente.cliente)
    assert rodar(ambiente.cliente).status_code == 409
    assert rodar(ambiente.cliente, ident="../x").status_code == 422


def test_reenvio_encadeado_so_com_tarefa_da_pagina(ambiente):
    rodar(ambiente.cliente)
    ambiente.roteiro["partes"].append([{"tipo": "token", "texto": "corrigida\n"}, {"tipo": "tokens", "tokens": 2}])
    resposta = ambiente.cliente.post("/api/bancada/propostas/moe/t1/reenviar", json={"prompt": "Use só current()."})
    fim = eventos(resposta)[-1]
    assert fim["tipo"] == "fim" and fim["id"] == "t1-r1"
    meta = json.loads((ambiente.pasta / "tarefas" / "t1-r1.json").read_text())
    assert meta["origem_de"] == "t1" and meta["prompt_correcao"] == "Use só current()."
    enviadas = ambiente.roteiro["mensagens"][-1]
    assert [m["role"] for m in enviadas] == ["user", "assistant", "user"]
    assert enviadas[1]["content"] == "proposta ok\n"
    (ambiente.pasta / "dev").mkdir()
    (ambiente.pasta / "dev" / "corpus1.txt").write_text("x")
    assert ambiente.cliente.post("/api/bancada/propostas/dev/corpus1/reenviar", json={"prompt": "y"}).status_code == 409


def test_verificar_e_parecer_gravam_resultado(ambiente, monkeypatch):
    rodar(ambiente.cliente)
    checks = SimpleNamespace(verificar=lambda texto, tarefa: {"achados": [], "erros": 0, "categorias_erro": [], "aprovada": True})
    observador = SimpleNamespace(
        PADRAO="openai/gpt-5.6-luna", OBSERVERS={"openai/gpt-5.6-luna": {}},
        montar_mensagens=lambda *a: [{"role": "user", "content": "x"}],
        observar=lambda modelo, mensagens: {"ok": True, "parecer": {"veredito": "aproveitada", "erros": [], "prompt_correcao": ""},
                                            "custo_usd": 0.0009, "segundos": 3.0, "falhas": []})
    monkeypatch.setattr(runner, "_modulo", lambda nome: {"bancada_checks": checks, "bancada_observer": observador}[nome])
    assert ambiente.cliente.post("/api/bancada/propostas/moe/t1/verificar").json()["aprovada"] is True
    parecer = ambiente.cliente.post("/api/bancada/propostas/moe/t1/parecer", json={}).json()
    assert parecer["parecer"]["veredito"] == "aproveitada" and parecer["custo_usd"] == 0.0009
    assert (ambiente.pasta / "pareceres" / "t1__openai--gpt-5.6-luna.json").exists()
    recusa = ambiente.cliente.post("/api/bancada/propostas/moe/t1/parecer", json={"observer": "qualquer/um"})
    assert recusa.status_code == 422
    detalhe = ambiente.cliente.get("/api/bancada/propostas/moe/t1").json()
    assert detalhe["tarefa"]["base"] == "abc1234" and detalhe["pareceres"][0]["veredito"] == "aproveitada"


def test_ligar_desligar_e_nao_desliga_ocupado(ambiente, monkeypatch):
    from app.services import agent_lifecycle
    chamadas = []
    monkeypatch.setattr(agent_lifecycle, "_llama_service", lambda acao: chamadas.append(acao) or True)
    assert ambiente.cliente.post("/api/bancada/modelo/ligar").json() == {"acao": "ligar", "ok": True}
    with runner._lock_execucao():
        assert ambiente.cliente.post("/api/bancada/modelo/desligar").status_code == 409
    assert chamadas == ["start"]
    assert ambiente.cliente.post("/api/bancada/modelo/trocar").status_code == 404


def test_exige_e_espera_diff_chegam_as_checagens(ambiente, monkeypatch):
    rodar(ambiente.cliente, exige={r"current\(\)": "usar current()"}, espera_diff=True)
    meta = json.loads((ambiente.pasta / "tarefas" / "t1.json").read_text())
    assert meta["exige"] == {r"current\(\)": "usar current()"} and meta["espera_diff"] is True
    recebida = {}
    checks = SimpleNamespace(verificar=lambda texto, tarefa: recebida.update(tarefa) or
                             {"achados": [], "erros": 0, "categorias_erro": [], "aprovada": True})
    monkeypatch.setattr(runner, "_modulo", lambda nome: checks)
    ambiente.cliente.post("/api/bancada/propostas/moe/t1/verificar")
    assert recebida["exige"] == {r"current\(\)": "usar current()"} and recebida["espera_diff"] is True
    assert recebida["escopo"] == ["apps/modulo.py"] and recebida["base"] == "abc1234"


@pytest.mark.parametrize("exige,codigo", [
    ({"(": "regex quebrada"}, "exige_invalido"),
    ({f"a{i}": "x" for i in range(6)}, "exige_demais"),
])
def test_exige_invalido_e_recusado(ambiente, exige, codigo):
    resposta = rodar(ambiente.cliente, exige=exige)
    assert resposta.status_code == 422 and resposta.json()["detail"]["code"] == codigo


def _observador_falso(vereditos: dict):
    """vereditos: observer -> veredito (None = falha do observer)."""
    chamados = []

    def observar(modelo, mensagens):
        chamados.append(modelo)
        veredito = vereditos[modelo]
        if veredito is None:
            return {"ok": False, "parecer": None, "custo_usd": 0.0001, "segundos": 1.0, "falhas": ["sem JSON"]}
        return {"ok": True, "parecer": {"veredito": veredito, "erros": [], "prompt_correcao": ""},
                "custo_usd": 0.001 if "luna" in modelo else 0.0002, "segundos": 2.0, "falhas": []}
    modulo = SimpleNamespace(
        PADRAO="openai/gpt-5.6-luna", OBSERVERS={"openai/gpt-5.6-luna": {}, "mistralai/codestral-2508": {}},
        SEGUNDA_OPINIAO_PRIMARIO="mistralai/codestral-2508", SEGUNDA_OPINIAO_ARBITRO="openai/gpt-5.6-luna",
        montar_mensagens=lambda *a: [{"role": "user", "content": "x"}], observar=observar)
    return modulo, chamados


@pytest.mark.parametrize("vereditos,chamados_esperados,final,decidido", [
    ({"mistralai/codestral-2508": "aproveitada", "openai/gpt-5.6-luna": "descartada"},
     ["mistralai/codestral-2508"], "aproveitada", "mistralai/codestral-2508"),
    ({"mistralai/codestral-2508": "descartada", "openai/gpt-5.6-luna": "correcao_pequena"},
     ["mistralai/codestral-2508", "openai/gpt-5.6-luna"], "correcao_pequena", "openai/gpt-5.6-luna"),
    ({"mistralai/codestral-2508": "descartada", "openai/gpt-5.6-luna": None},
     ["mistralai/codestral-2508", "openai/gpt-5.6-luna"], "descartada", "mistralai/codestral-2508"),
])
def test_segunda_opiniao_escala_so_quando_precisa(ambiente, monkeypatch, vereditos, chamados_esperados, final, decidido):
    rodar(ambiente.cliente)
    observador, chamados = _observador_falso(vereditos)
    checks = SimpleNamespace(verificar=lambda texto, tarefa: {"achados": [], "erros": 0, "categorias_erro": [], "aprovada": True})
    monkeypatch.setattr(runner, "_modulo", lambda nome: {"bancada_checks": checks, "bancada_observer": observador}[nome])
    corpo = ambiente.cliente.post("/api/bancada/propostas/moe/t1/parecer", json={"observer": "segunda-opiniao"}).json()
    assert chamados == chamados_esperados
    assert corpo["parecer"]["veredito"] == final and corpo["decidido_por"] == decidido
    assert [e["observer"] for e in corpo["etapas"]] == chamados_esperados
    assert corpo["custo_usd"] == round(0.0002 + (0.001 if vereditos["openai/gpt-5.6-luna"] and len(chamados) > 1 else 0.0001 if len(chamados) > 1 else 0), 6)


def test_lista_observers_e_segunda_opiniao(ambiente, monkeypatch):
    observador, _ = _observador_falso({})
    monkeypatch.setattr(runner, "_modulo", lambda nome: observador)
    corpo = ambiente.cliente.get("/api/bancada/observers").json()
    assert corpo["padrao"] == "openai/gpt-5.6-luna" and "mistralai/codestral-2508" in corpo["observers"]
    assert corpo["segunda_opiniao"] == {"id": "segunda-opiniao", "primario": "mistralai/codestral-2508", "arbitro": "openai/gpt-5.6-luna"}
