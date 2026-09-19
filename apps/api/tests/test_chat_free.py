"""Contrato do Chat livre: conversa sem tools, isolada do sistema.

A regra central é que a requisição ao modelo NÃO contém o campo `tools` —
é o que garante que o chat livre nunca escreve no WorkDev. Estes testes
fixam esse contrato e o CRUD das conversas.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import chat_free
from app.routers.chat_free import MessageSend


def _conv(**kwargs):
    padroes = dict(
        id="11111111-1111-1111-1111-111111111112", title="Nova conversa",
        title_locked=False, input_tokens=0, output_tokens=0, cost_usd=0,
        created_at="2026-09-19 00:00:00", updated_at="2026-09-19 00:00:00",
    )
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


class TruncamentoTest:
    pass


def test_truncate_history_descarta_antigas_mantendo_a_ultima():
    mensagens = [{"role": "user", "content": "x" * 4000} for _ in range(10)]
    mensagens.append({"role": "user", "content": "pergunta final"})

    saida = chat_free.truncate_history(mensagens, context_limit=2000)

    assert saida[-1]["content"] == "pergunta final"
    assert len(saida) < len(mensagens)


def test_truncate_history_nao_descarta_quando_cabe():
    mensagens = [{"role": "user", "content": "oi"}]

    assert chat_free.truncate_history(mensagens, 16384) == mensagens


def test_estimate_tokens_usa_a_mesma_regra_do_ai_hub():
    # ~4 chars por token, mínimo 1.
    assert chat_free.estimate_tokens([{"role": "user", "content": "abcd"}]) >= 1
    assert chat_free.estimate_tokens([]) == 1


def _fake_db(conv):
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conv
    return db


def test_payload_do_modelo_nao_contem_tools():
    """Regra central: a requisição ao provider não pode ter o campo tools."""
    conv = _conv()
    db = _fake_db(conv)
    req = MessageSend(content="olá", provider="openrouter",
                      model="moonshotai/kimi-k3")
    history = [{"role": "user", "content": "olá"}]

    capturado = {}

    class _Resp:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"oi"}}]}'
            yield 'data: {"usage":{"prompt_tokens":3,"completion_tokens":1}}'
            yield "data: [DONE]"

    def fake_stream(method, url, json=None, headers=None, timeout=None):
        capturado["payload"] = json
        return _Resp()

    with patch.object(chat_free.agent_runtimes, "local_chat_runtime"), \
         patch.object(chat_free.httpx, "stream", side_effect=fake_stream), \
         patch.object(chat_free.ai_cost_guard, "policy_for",
                      side_effect=Exception("sem custo")):
        eventos = list(chat_free._stream_chat(req, conv, history, db))

    assert capturado["payload"] is not None
    assert "tools" not in capturado["payload"]
    assert capturado["payload"]["stream"] is True
    # A resposta chegou por SSE e foi persistida.
    assert any(e.startswith(b"event: delta") for e in eventos)
    assert any(e.startswith(b"event: done") for e in eventos)
    db.add.assert_called()


def test_stream_chat_rejeita_provider_desconhecido():
    """Provider inválido vira `event: error` no SSE, não exceção propagada."""
    conv = _conv()
    db = _fake_db(conv)
    req = MessageSend(content="oi", provider="nao-existe", model="x")

    eventos = list(chat_free._stream_chat(
        req, conv, [{"role": "user", "content": "oi"}], db))

    assert len(eventos) == 1
    assert eventos[0].startswith(b"event: error")
    assert b"Provider" in eventos[0] or b"provider" in eventos[0]


def test_titulo_automatico_na_primeira_mensagem():
    """A primeira mensagem do usuário vira o título se não foi renomeado."""
    conv = _conv(title="Nova conversa", title_locked=False)
    db = Mock()
    # 1ª chamada: _get_conversation; 2ª: já existe msg de usuário? (não);
    # 3ª: histórico (vazio antes de gravar).
    db.query.return_value.filter.return_value.first.side_effect = [conv, None]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    req = MessageSend(content="Como faço um hello world em Rust?",
                      provider="openrouter", model="moonshotai/kimi-k3")

    with patch.object(chat_free, "_stream_chat", return_value=iter([])):
        chat_free.send_message(str(conv.id), req, db)

    assert conv.title == "Como faço um hello world em Rust?"
    db.add.assert_called()  # mensagem do usuário gravada
    db.commit.assert_called()


def test_titulo_nao_muda_depois_de_renomeado():
    """Depois do rename (title_locked), a 1ª mensagem não sobrescreve."""
    conv = _conv(title="Ideias de produto", title_locked=True)
    db = Mock()
    db.query.return_value.filter.return_value.first.side_effect = [conv, None]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    req = MessageSend(content="qualquer coisa", provider="openrouter",
                      model="moonshotai/kimi-k3")

    with patch.object(chat_free, "_stream_chat", return_value=iter([])):
        chat_free.send_message(str(conv.id), req, db)

    assert conv.title == "Ideias de produto"


def test_rename_trava_titulo_automatico():
    conv = _conv(title="Velho", title_locked=False)
    db = _fake_db(conv)
    payload = chat_free.ConversationRename(title="Ideias de produto")

    saida = chat_free.rename_conversation(str(conv.id), payload, db)

    assert saida["title"] == "Ideias de produto"
    assert conv.title_locked is True
    db.commit.assert_called()


def test_delete_conversation_remove_do_banco():
    conv = _conv()
    db = _fake_db(conv)

    saida = chat_free.delete_conversation(str(conv.id), db)

    assert saida["deleted"] is True
    db.delete.assert_called_once_with(conv)
    db.commit.assert_called()


def test_conversation_out_forma_estavel():
    esperadas = {"id", "title", "input_tokens", "output_tokens", "cost_usd",
                 "created_at", "updated_at"}
    assert set(chat_free.conversation_out(_conv())) == esperadas


def test_sse_format():
    quadro = chat_free._sse("delta", {"content": "olá"})
    assert quadro.startswith(b"event: delta\n")
    assert b"data: " in quadro
    assert json.loads(quadro.decode().split("data: ", 1)[1]) == {"content": "olá"}
