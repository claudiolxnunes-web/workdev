import os
import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from anthropic import Anthropic
from app.database import SessionLocal
from app.models.project import Project
from app.models.backlog import BacklogItem

router = APIRouter()
client = Anthropic()

MODEL = "claude-sonnet-4-6"

SYSTEM = (
    "Você é o assistente do WorkDev, plataforma de engenharia do Cláudio "
    "(BPF Consult). Responda sempre em português do Brasil, de forma curta e "
    "direta. Use as ferramentas para consultar ou modificar projetos e backlog. "
    "Slugs conhecidos: workdev-core, nutrigestor-crm, agente-pessoal, openclaw, "
    "feed-bpf, nutricontrole."
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


TOOLS = [
    {
        "name": "listar_projetos",
        "description": "Lista todos os projetos do WorkDev com status",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "listar_backlog",
        "description": "Lista itens do backlog, com filtro opcional por status e/ou projeto",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["todo", "doing", "blocked", "done"]},
                "projeto_slug": {"type": "string"},
            },
        },
    },
    {
        "name": "criar_task",
        "description": "Cria um item no backlog de um projeto",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "projeto_slug": {"type": "string"},
                "tipo": {"type": "string", "enum": ["feature", "bug", "chore", "infra"]},
                "prioridade": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "sprint": {"type": "string"},
            },
            "required": ["titulo", "projeto_slug"],
        },
    },
]


def executar_tool(nome: str, args: dict, db: Session) -> str:
    if nome == "listar_projetos":
        ps = db.query(Project).all()
        return json.dumps(
            [{"nome": p.name, "slug": p.slug, "status": p.status} for p in ps],
            ensure_ascii=False,
        )

    if nome == "listar_backlog":
        q = db.query(BacklogItem)
        if args.get("status"):
            q = q.filter(BacklogItem.status == args["status"])
        if args.get("projeto_slug"):
            p = db.query(Project).filter(Project.slug == args["projeto_slug"]).first()
            if not p:
                return json.dumps({"erro": "projeto não encontrado"})
            q = q.filter(BacklogItem.project_id == p.id)
        items = q.all()
        return json.dumps(
            [{"titulo": i.title, "status": i.status, "prioridade": i.priority,
              "tipo": i.type, "sprint": i.sprint} for i in items],
            ensure_ascii=False,
        )

    if nome == "criar_task":
        p = db.query(Project).filter(Project.slug == args["projeto_slug"]).first()
        if not p:
            return json.dumps({"erro": "projeto não encontrado"})
        item = BacklogItem(
            project_id=p.id,
            title=args["titulo"],
            type=args.get("tipo", "feature"),
            priority=args.get("prioridade", "medium"),
            sprint=args.get("sprint"),
            status="todo",
        )
        db.add(item)
        db.commit()
        return json.dumps({"ok": True, "titulo": item.title, "projeto": p.name},
                          ensure_ascii=False)

    return json.dumps({"erro": "ferramenta desconhecida"})


@router.post("/ai/chat")
def ai_chat(req: ChatRequest, db: Session = Depends(get_db)):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    for _ in range(5):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            texto = "".join(b.text for b in resp.content if b.type == "text")
            return {"reply": texto}

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = executar_tool(block.name, block.input, db)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                })
        messages.append({"role": "user", "content": results})

    return {"reply": "Não consegui concluir a operação (limite de passos)."}
