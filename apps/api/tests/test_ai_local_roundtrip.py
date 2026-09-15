"""Existing tool executor with isolated persistence; real Ollama is opt-in."""
import json
import os
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from openai import OpenAI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.backlog import BacklogItem
from app.routers import ai


@pytest.fixture
def isolated_db(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def functions(connection, _):
        connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)
        connection.create_function("now", 0, lambda: "2026-09-15 00:00:00")

    Project.__table__.create(engine)
    BacklogItem.__table__.create(engine)
    # External projection is deliberately disabled; persistence below is real.
    monkeypatch.setattr(ai.graph_sync, "sync_safely", MagicMock())
    with Session(engine) as db:
        db.add(Project(id=uuid4(), name="Isolated validation", slug="isolated-validation",
                       type="web", status="Development"))
        db.commit()
        yield db
    engine.dispose()


@pytest.mark.parametrize("mode", ["allowed", "denied", "prose", "invalid_json"])
def test_local_protocol_uses_authoritative_persistence(isolated_db, monkeypatch, mode):
    requests = []
    args = {"projeto_slug": "isolated-validation", "titulo": "Isolated task"}

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        message = {"role": "assistant", "content": "Criei a task."}
        if len(requests) == 1 and mode != "prose":
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-isolated", "type": "function", "function": {
                    "name": "criar_task", "arguments": "{invalid" if mode == "invalid_json" else json.dumps(args),
                },
            }]}
        return httpx.Response(200, json={"id": "chat-isolated", "object": "chat.completion",
            "created": 0, "model": "installed-model", "choices": [{"index": 0, "message": message,
            "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]})

    client = OpenAI(api_key="isolated", base_url="http://isolated.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(ai, "get_openai", lambda *args: client)
    monkeypatch.setattr(ai.agent_runtimes, "local_chat_context", lambda *args: 32768)
    kwargs = dict(model="installed-model", provider="ollama", runtime_id="local-code",
                  nivel="observe" if mode == "denied" else "plan", max_output_tokens=256)
    if mode == "invalid_json":
        with pytest.raises(json.JSONDecodeError):
            ai.chat_openai([], isolated_db, **kwargs)
    else:
        ai.chat_openai([], isolated_db, **kwargs)
    assert isolated_db.query(BacklogItem).count() == (1 if mode == "allowed" else 0)
    if mode in {"allowed", "denied"}:
        result = requests[-1]["messages"][-1]
        assert result["role"] == "tool" and result["tool_call_id"] == "call-isolated"
        receipt = json.loads(result["content"])
        assert receipt.get("ok") is True if mode == "allowed" else receipt["executado"] is False


@pytest.mark.skipif(not os.getenv("WORKDEV_LOCAL_MODEL_TEST"), reason="opt-in real local model")
def test_real_local_model_with_canonical_plan_and_tools(isolated_db, monkeypatch):
    monkeypatch.setenv("AI_MAX_TOOL_STEPS", "3")
    model = os.environ["WORKDEV_LOCAL_MODEL_TEST"]
    assert any(row["model"] == model for row in ai.agent_runtimes.local_chat_models())
    title = "Validation " + uuid4().hex[:10]
    system = "\n\n".join([ai.SYSTEM, ai.autoridade.instrucao_de_nivel("plan"), ai.load_plan_system_prompt()])
    observed = []
    execute = ai.executar_tool

    def capture(*args, **kwargs):
        result = execute(*args, **kwargs)
        observed.append({"tool": args[0], "result": json.loads(result)})
        return result

    monkeypatch.setattr(ai, "executar_tool", capture)
    result = ai.chat_openai([
        {"role": "user", "content": f'Crie exatamente uma task com titulo "{title}" no projeto '
         'de slug "isolated-validation", tipo feature, prioridade medium. Use criar_task diretamente; '
         'o projeto ja existe. Depois do resultado, confirme brevemente e nao repita a criacao.'},
    ], isolated_db, model=model, provider="ollama", runtime_id="local-code", system=system,
        nivel="plan", max_output_tokens=256)
    assert isolated_db.query(BacklogItem).filter(BacklogItem.title == title).count() == 1
    assert len([row for row in observed if row["tool"] == "criar_task"]) == 1
    assert any(row["tool"] == "criar_task" and row["result"].get("ok") is True for row in observed)
    assert result.text and result.input_tokens > 0
    print(json.dumps({"model": model, "input_tokens": result.input_tokens,
                      "output_tokens": result.output_tokens, "tools": observed}, ensure_ascii=False))
