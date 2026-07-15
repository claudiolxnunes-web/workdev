import os
import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from anthropic import Anthropic
from openai import OpenAI
from app.database import SessionLocal
from app.models.project import Project
from app.models.backlog import BacklogItem
from app.models.subtask import BacklogSubtask
from app.models.knowledge import KnowledgeEntry
from app.models.chat import ChatSession, ChatMessage as ChatMessageDB

router = APIRouter()

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_anthropic_client = None
_openai_client = None


def get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic()
    return _anthropic_client


def get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


SYSTEM = (
    "Você é o assistente do WorkDev, plataforma de engenharia do Cláudio "
    "(BPF Consult). Responda sempre em português do Brasil, curto e direto. "
    "Use as ferramentas para consultar ou modificar projetos, backlog e "
    "subtasks. Slugs: workdev-core, nutrigestor-crm, agente-pessoal, "
    "openclaw, feed-bpf, nutricontrole."
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
    provider: str | None = None
    session_id: str | None = None
TOOLS = [
    {
        "name": "listar_projetos",
        "description": "Lista todos os projetos do WorkDev com status",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "listar_backlog",
        "description": "Lista itens do backlog, filtro opcional por status e/ou projeto",
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
    {
        "name": "decompor_task",
        "description": "Cria subtasks para um item do backlog. Use quando pedirem para decompor/quebrar uma task. Você decide as subtasks: títulos claros e acionáveis, em ordem de execução.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo_task": {"type": "string", "description": "título (ou parte) da task"},
                "subtasks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["titulo_task", "subtasks"],
        },
    },
    {
        "name": "registrar_conhecimento",
        "description": "Registra uma entrada no Knowledge Engine: decisoes, licoes aprendidas, solucoes ou referencias. Use quando pedirem para registrar/gravar/anotar conhecimento, licao ou decisao.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "conteudo": {"type": "string", "description": "texto completo em markdown"},
                "categoria": {"type": "string", "enum": ["decisao", "licao", "solucao", "referencia"]},
                "tags": {"type": "string", "description": "separadas por virgula, ex: docker,ufw"},
                "projeto_slug": {"type": "string", "description": "opcional; omitir se global"},
            },
            "required": ["titulo", "conteudo", "categoria"],
        },
    },
    {
        "name": "buscar_conhecimento",
        "description": "Busca no Knowledge Engine por texto (titulo, conteudo ou tags) e/ou categoria. Use antes de opinar sobre problemas tecnicos - pode haver licao registrada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string"},
                "categoria": {"type": "string", "enum": ["decisao", "licao", "solucao", "referencia"]},
            },
        },
    },
    {
        "name": "listar_subtasks",
        "description": "Lista as subtasks de uma task do backlog",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo_task": {"type": "string"},
            },
            "required": ["titulo_task"],
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
        return json.dumps(
            [{"titulo": i.title, "status": i.status, "prioridade": i.priority,
              "tipo": i.type, "sprint": i.sprint} for i in q.all()],
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

    if nome == "decompor_task":
        t = (db.query(BacklogItem)
             .filter(BacklogItem.title.ilike(f"%{args['titulo_task']}%"))
             .first())
        if not t:
            return json.dumps({"erro": "task não encontrada"})
        criadas = []
        for i, titulo in enumerate(args["subtasks"], start=1):
            db.add(BacklogSubtask(backlog_id=t.id, title=titulo,
                                  execution_order=i))
            criadas.append(titulo)
        db.commit()
        return json.dumps({"ok": True, "task": t.title, "subtasks": criadas},
                          ensure_ascii=False)

    if nome == "listar_subtasks":
        t = (db.query(BacklogItem)
             .filter(BacklogItem.title.ilike(f"%{args['titulo_task']}%"))
             .first())
        if not t:
            return json.dumps({"erro": "task não encontrada"})
        subs = (db.query(BacklogSubtask)
                .filter(BacklogSubtask.backlog_id == t.id)
                .order_by(BacklogSubtask.execution_order).all())
        return json.dumps(
            {"task": t.title,
             "subtasks": [{"ordem": s.execution_order, "titulo": s.title,
                           "status": s.status} for s in subs]},
            ensure_ascii=False,
        )

    if nome == "registrar_conhecimento":
        pid = None
        if args.get("projeto_slug"):
            p = db.query(Project).filter(Project.slug == args["projeto_slug"]).first()
            if p:
                pid = p.id
        entry = KnowledgeEntry(
            project_id=pid,
            title=args["titulo"],
            content=args["conteudo"],
            category=args["categoria"],
            tags=args.get("tags"),
        )
        db.add(entry)
        db.commit()
        return json.dumps({"ok": True, "titulo": entry.title,
                           "categoria": entry.category}, ensure_ascii=False)

    if nome == "buscar_conhecimento":
        q = db.query(KnowledgeEntry)
        if args.get("categoria"):
            q = q.filter(KnowledgeEntry.category == args["categoria"])
        if args.get("termo"):
            termo = f"%{args['termo']}%"
            q = q.filter(
                KnowledgeEntry.title.ilike(termo)
                | KnowledgeEntry.content.ilike(termo)
                | KnowledgeEntry.tags.ilike(termo)
            )
        rs = q.order_by(KnowledgeEntry.created_at.desc()).limit(10).all()
        return json.dumps(
            [{"titulo": r.title, "categoria": r.category, "tags": r.tags,
              "conteudo": r.content[:500]} for r in rs],
            ensure_ascii=False,
        )

    return json.dumps({"erro": "ferramenta desconhecida"})


def chat_anthropic(messages: list, db: Session) -> str:
    client = get_anthropic()
    for _ in range(5):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
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
    return "Não consegui concluir a operação (limite de passos)."

def tools_openai() -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]


def chat_openai(messages: list, db: Session) -> str:
    client = get_openai()
    msgs = [{"role": "system", "content": SYSTEM}] + messages
    for _ in range(5):
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=1024,
            tools=tools_openai(),
            messages=msgs,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        msgs.append(msg)
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            out = executar_tool(tc.function.name, args, db)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": out,
            })
    return "Não consegui concluir a operação (limite de passos)."

@router.post("/ai/chat")
def ai_chat(req: ChatRequest, db: Session = Depends(get_db)):
    provider = (req.provider or os.getenv("AI_PROVIDER", "anthropic")).lower()
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    session = None
    if req.session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == req.session_id).first()
    if session is None and messages:
        first_user = next((m["content"] for m in messages
                           if m["role"] == "user"), "Conversa")
        session = ChatSession(title=first_user[:250])
        db.add(session)
        db.commit()
        db.refresh(session)
    if session and messages:
        last = messages[-1]
        if last["role"] == "user":
            db.add(ChatMessageDB(session_id=session.id,
                                 role="user", content=last["content"]))
            db.commit()

    try:
        if provider == "openai":
            reply = chat_openai(messages, db)
        else:
            provider = "anthropic"
            reply = chat_anthropic(messages, db)
    except Exception as e:
        reply = f"Erro no provider {provider}: {type(e).__name__} - {e}"
        return {"reply": reply, "provider": provider, "error": True,
                "session_id": str(session.id) if session else None}

    if session:
        db.add(ChatMessageDB(session_id=session.id,
                             role="assistant", content=reply))
        session.updated_at = __import__("datetime").datetime.utcnow()
        db.commit()
    return {"reply": reply, "provider": provider,
            "session_id": str(session.id) if session else None}
