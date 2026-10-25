"""Fase 0 do loop de tools: argumentos, repetição, tempo total, truncamento, slot local e telemetria."""
import fcntl
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.routers import ai
from app.services import agent_runtimes as runtimes
from app.services import tool_loop

SCHEMA = {"type": "object", "properties": {"caminho": {"type": "string"}, "inicio": {"type": "integer"},
                                           "fim": {"type": "integer"}, "forcar": {"type": "boolean"},
                                           "modo": {"type": "string", "enum": ["a", "b"]}},
          "required": ["caminho", "inicio"]}
TOOLS = [{"name": "ler", "input_schema": SCHEMA}]


# ---------------------------------------------------------------- validação

def test_validar_coage_o_obvio_e_aponta_o_resto():
    args, erros = tool_loop.validar(SCHEMA, {"caminho": "a.py", "inicio": "10", "fim": 20.0, "forcar": "true"})
    assert erros == [] and args == {"caminho": "a.py", "inicio": 10, "fim": 20, "forcar": True}
    _, erros = tool_loop.validar(SCHEMA, {"inicio": "dez", "modo": "c"})
    assert "falta o argumento obrigatório 'caminho'" in erros
    assert any("'inicio' precisa ser integer" in e for e in erros)
    assert any("'modo' precisa ser um de" in e for e in erros)
    assert tool_loop.validar(SCHEMA, ["nao", "objeto"])[1] == ["os argumentos precisam ser um objeto JSON"]


def test_argumentos_json_quebrado_e_tool_fora_do_catalogo():
    guarda = tool_loop.Guarda(TOOLS, local=True)
    args, erro = guarda.argumentos("ler", "{quebrado")
    assert args is None and json.loads(erro)["code"] == "json_invalido"
    args, erro = guarda.argumentos("ler", '{"caminho": "a.py"}')
    assert json.loads(erro)["code"] == "argumentos_invalidos" and "inicio" in json.loads(erro)["erro"]
    # Fora do catálogo quem recusa é o gate de autoridade; aqui só o parse.
    assert guarda.argumentos("outra", '{"x": 1}') == ({"x": 1}, None)


def test_repeticao_avisa_e_depois_interrompe():
    guarda = tool_loop.Guarda(TOOLS, local=False)
    args = {"caminho": "a.py", "inicio": 1}
    assert guarda.repetida("ler", args) is None and guarda.repetida("ler", dict(args)) is None
    assert json.loads(guarda.repetida("ler", args))["code"] == "chamada_repetida"
    # Chamada diferente zera a sequência de recusas.
    assert guarda.repetida("ler", {"caminho": "b.py", "inicio": 1}) is None
    guarda.repetida("ler", args)
    guarda.repetida("ler", args)
    with pytest.raises(tool_loop.Interromper) as erro:
        guarda.repetida("ler", args)
    assert erro.value.motivo == "repeticao"


def test_prazo_total_e_truncamento(monkeypatch):
    monkeypatch.setenv("AI_LOCAL_MAX_TOTAL_SECONDS", "60")
    monkeypatch.setenv("AI_TOOL_RESULT_MAX_CHARS", "10")
    guarda = tool_loop.Guarda(TOOLS, local=True)
    assert guarda.prazo(900) <= 60
    guarda.inicio -= 58
    with pytest.raises(tool_loop.Interromper) as erro:
        guarda.prazo(900)
    assert erro.value.motivo == "tempo"
    assert guarda.truncar("0123456789abc").startswith("0123456789\n[... resultado cortado: 3")


def test_slot_local_espera_a_bancada_e_desiste(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path))
    with tool_loop.slot_local(True, espera_s=1):
        pass
    with open(tmp_path / ".execucao.lock", "w") as outro:
        fcntl.flock(outro, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(tool_loop.Interromper) as erro:
            with tool_loop.slot_local(True, espera_s=0.6):
                pass
    assert erro.value.motivo == "ocupado"
    with tool_loop.slot_local(False):
        pass


def test_registrar_grava_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TELEMETRIA_DIR", str(tmp_path / "t"))
    tool_loop.registrar(provider="ollama", tools=["ler"], tok_s_total=3.5)
    linha = json.loads(next((tmp_path / "t").glob("*.jsonl")).read_text())
    assert linha["provider"] == "ollama" and linha["tools"] == ["ler"] and "ts" in linha


# ---------------------------------------------------------------- loops do ai.py

def _resposta(tool_calls=None, content=None):
    msg = MagicMock(tool_calls=tool_calls or [], content=content)
    msg.model_dump.return_value = {"role": "assistant"}
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=4)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls" if tool_calls else "stop")],
                           usage=usage)


def _chamada(args: str, ident="c1"):
    return SimpleNamespace(id=ident, function=SimpleNamespace(name="ler_trecho", arguments=args))


@pytest.fixture
def openai_local(monkeypatch, tmp_path):
    client = MagicMock()
    monkeypatch.setattr(ai, "get_openai", lambda *a: client)
    monkeypatch.setattr(runtimes, "local_chat_context", lambda *a: 100000)
    monkeypatch.setattr(runtimes, "local_chat_runtime", lambda *a: SimpleNamespace(engine=runtimes.ENGINE_LLAMACPP))
    monkeypatch.setattr(ai.local_model, "current", lambda: "moe")
    slots = []

    @contextmanager
    def slot_falso(ativo, espera_s=None):
        slots.append(ativo)
        yield
    monkeypatch.setattr(tool_loop, "slot_local", slot_falso)
    executadas = []
    monkeypatch.setattr(ai, "executar_tool", lambda nome, args, db, nivel, backlog_id=None:
                        executadas.append((nome, args)) or '{"texto": "' + "x" * 50 + '"}')
    return SimpleNamespace(client=client, slots=slots, executadas=executadas, telemetria=tmp_path / "ai-telemetria")


def test_openai_local_coage_argumentos_trunca_usa_slot_e_registra(openai_local, monkeypatch):
    monkeypatch.setenv("AI_TOOL_RESULT_MAX_CHARS", "20")
    openai_local.client.chat.completions.create.side_effect = [
        _resposta([_chamada('{"caminho": "a.py", "inicio": "1", "fim": "5"}')]), _resposta(content="pronto")]
    r = ai.chat_openai([], MagicMock(), "m", "ollama", nivel="observe", runtime_id="local-code", max_output_tokens=64)
    assert r.text == "pronto"
    assert openai_local.executadas == [("ler_trecho", {"caminho": "a.py", "inicio": 1, "fim": 5})]
    ultima = openai_local.client.chat.completions.create.call_args.kwargs
    assert "[... resultado cortado" in ultima["messages"][-1]["content"]
    assert 0 < ultima["timeout"] <= 900
    assert openai_local.slots == [True, True]
    linhas = [json.loads(l) for l in next(openai_local.telemetria.glob("*.jsonl")).read_text().splitlines()]
    assert [l["tools"] for l in linhas] == [["ler_trecho"], []]
    assert linhas[0]["modelo_local"] == "moe" and linhas[0]["completion_tokens"] == 4 and "tok_s_total" in linhas[0]


def test_openai_json_quebrado_volta_ao_modelo(openai_local):
    openai_local.client.chat.completions.create.side_effect = [
        _resposta([_chamada("{quebrado")]), _resposta(content="corrigi")]
    r = ai.chat_openai([], MagicMock(), "m", "ollama", nivel="observe", runtime_id="local-code", max_output_tokens=64)
    assert r.text == "corrigi" and openai_local.executadas == []
    erro = json.loads(openai_local.client.chat.completions.create.call_args.kwargs["messages"][-1]["content"])
    assert erro["code"] == "json_invalido"


def test_openai_repeticao_encerra_com_mensagem(openai_local):
    mesma = '{"caminho": "a.py", "inicio": 1, "fim": 2}'
    openai_local.client.chat.completions.create.side_effect = [_resposta([_chamada(mesma, f"c{i}")]) for i in range(12)]
    r = ai.chat_openai([], MagicMock(), "m", "ollama", nivel="observe", runtime_id="local-code", max_output_tokens=64)
    assert "repetição" in r.text
    assert len(openai_local.executadas) == tool_loop.MAX_REPETICOES


def test_openai_nuvem_nao_usa_slot_local(openai_local, monkeypatch):
    monkeypatch.setattr(ai, "get_openai", lambda *a: openai_local.client)
    openai_local.client.chat.completions.create.side_effect = [_resposta(content="ok")]
    ai.chat_openai([], MagicMock(), "m", "openrouter", nivel="observe", max_output_tokens=64)
    assert openai_local.slots == [False]
    assert openai_local.client.chat.completions.create.call_args.kwargs["timeout"] <= 30


def test_anthropic_passa_prazo_e_interrompe_repeticao(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai, "get_anthropic", lambda: client)
    bloco = SimpleNamespace(type="tool_use", name="ler_trecho", id="t", input={"caminho": "a.py", "inicio": 1, "fim": 2})
    client.messages.create.return_value = SimpleNamespace(stop_reason="tool_use", content=[bloco],
                                                          usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(ai, "executar_tool", lambda *a, **k: "{}")
    r = ai.chat_anthropic([], MagicMock(), nivel="observe")
    assert "repetição" in r.text and r.input_tokens > 0
    assert 0 < client.messages.create.call_args.kwargs["timeout"] <= 120
