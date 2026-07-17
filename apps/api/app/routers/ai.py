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


_compat_clients: dict = {}

COMPAT_PROVIDERS = {
    "openai": {"base_url": None, "env_key": "OPENAI_API_KEY",
               "default_model": OPENAI_MODEL},
    "kimi": {"base_url": "https://api.moonshot.cn/v1",
             "env_key": "MOONSHOT_API_KEY",
             "default_model": os.getenv("KIMI_MODEL", "kimi-k2.6")},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com"
                           "/v1beta/openai/",
               "env_key": "GEMINI_API_KEY",
               "default_model": os.getenv("GEMINI_MODEL",
                                          "gemini-3.5-flash")},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                   "env_key": "OPENROUTER_API_KEY",
                   "default_model": os.getenv("OPENROUTER_MODEL",
                                              "moonshotai/kimi-k3")},
}


def get_openai(provider: str = "openai") -> OpenAI:
    if provider not in _compat_clients:
        cfg = COMPAT_PROVIDERS[provider]
        kwargs = {"api_key": os.getenv(cfg["env_key"])}
        if cfg["base_url"]:
            kwargs["base_url"] = cfg["base_url"]
        _compat_clients[provider] = OpenAI(**kwargs)
    return _compat_clients[provider]


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
    model: str | None = None
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
        "description": "Lista as subtasks de uma task do backlog. Prefira task_id (uuid) quando souber; senao use titulo_task. Se houver mais de uma task com titulo parecido, a tool devolve candidatas para voce pedir especificacao.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "id (uuid) da task — prefira sempre que souber"},
                "titulo_task": {"type": "string", "description": "titulo (ou parte unica) da task"},
            },
            "required": [],
        },
    },
    {
        "name": "atualizar_task",
        "description": "Atualiza uma task do backlog: status (todo/doing/blocked/done), prioridade, titulo ou sprint. Use quando pedirem para marcar como concluida/done, mover para doing, mudar prioridade, renomear. Se houver mais de uma task com titulo parecido, a tool devolve a lista para voce pedir especificacao.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "id (uuid) da task — prefira sempre que souber"},
                "titulo_task": {"type": "string", "description": "titulo (ou parte unica) da task"},
                "novo_status": {"type": "string", "enum": ["todo", "doing", "blocked", "done"]},
                "nova_prioridade": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "novo_titulo": {"type": "string"},
                "novo_sprint": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "atualizar_subtask",
        "description": "Atualiza uma subtask de uma task: status (todo/doing/done) ou titulo. Identifique a subtask pela ordem (numero) ou por parte do titulo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo_task": {"type": "string"},
                "task_id": {"type": "string", "description": "id (uuid) da task — prefira sempre que souber"},
                "subtask_id": {"type": "string", "description": "id (uuid) da subtask — prefira sempre que souber"},
                "ordem": {"type": "integer", "description": "numero de ordem da subtask"},
                "titulo_subtask": {"type": "string", "description": "alternativa a ordem"},
                "novo_status": {"type": "string", "enum": ["todo", "doing", "done"]},
                "novo_titulo": {"type": "string"},
            },
            "required": [],
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
            [{"id": str(i.id), "titulo": i.title, "status": i.status,
              "prioridade": i.priority, "tipo": i.type,
              "sprint": i.sprint} for i in q.all()],
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
        t = None
        if args.get("task_id"):
            t = db.query(BacklogItem).filter(
                BacklogItem.id == args["task_id"]).first()
            if not t:
                return json.dumps({"erro": "task não encontrada por task_id"})
        elif args.get("titulo_task"):
            matches = (db.query(BacklogItem)
                       .filter(BacklogItem.title.ilike(
                           f"%{args['titulo_task']}%"))
                       .all())
            if len(matches) > 1:
                return json.dumps(
                    {"erro": "mais de uma task encontrada, especifique",
                     "candidatas": [{"id": str(m.id), "titulo": m.title}
                                    for m in matches]},
                    ensure_ascii=False)
            t = matches[0] if matches else None
        if not t:
            return json.dumps({"erro": "task não encontrada — informe task_id ou titulo_task"})
        subs = (db.query(BacklogSubtask)
                .filter(BacklogSubtask.backlog_id == t.id)
                .order_by(BacklogSubtask.execution_order).all())
        return json.dumps(
            {"task": t.title, "task_id": str(t.id),
             "subtasks": [{"id": str(s.id), "ordem": s.execution_order,
                           "titulo": s.title,
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

    if nome == "atualizar_task":
        if args.get("task_id") is not None:
            matches = (db.query(BacklogItem)
                       .filter(BacklogItem.id == args["task_id"]).all())
        elif args.get("titulo_task"):
            termo = args["titulo_task"]
            matches = (db.query(BacklogItem)
                       .filter(BacklogItem.title.ilike(f"%{termo}%")).all())
            exatas = [m for m in matches if m.title.lower() == termo.lower()]
            if len(exatas) == 1:
                matches = exatas
        else:
            return json.dumps({"erro": "informe task_id ou titulo_task"},
                              ensure_ascii=False)
        if not matches:
            return json.dumps({"erro": "task não encontrada"}, ensure_ascii=False)
        if len(matches) > 1:
            return json.dumps(
                {"erro": "match ambíguo — especifique melhor",
                 "candidatas": [{"id": str(m.id), "titulo": m.title,
                                 "status": m.status,
                                 "prioridade": m.priority} for m in matches]},
                ensure_ascii=False)
        t = matches[0]
        alteracoes = {}
        if args.get("novo_status"):
            t.status = args["novo_status"]
            alteracoes["status"] = t.status
        if args.get("nova_prioridade"):
            t.priority = args["nova_prioridade"]
            alteracoes["prioridade"] = t.priority
        if args.get("novo_titulo"):
            t.title = args["novo_titulo"][:250]
            alteracoes["titulo"] = t.title
        if args.get("novo_sprint"):
            t.sprint = args["novo_sprint"]
            alteracoes["sprint"] = t.sprint
        if not alteracoes:
            return json.dumps({"erro": "nenhuma alteração informada"},
                              ensure_ascii=False)
        db.commit()
        return json.dumps({"ok": True, "task": t.title,
                           "alteracoes": alteracoes}, ensure_ascii=False)

    if nome == "atualizar_subtask":
        s = None
        t = None
        if args.get("subtask_id") is not None:
            s = (db.query(BacklogSubtask)
                 .filter(BacklogSubtask.id == args["subtask_id"]).first())
            if not s:
                return json.dumps({"erro": "subtask não encontrada"},
                                  ensure_ascii=False)
            t = (db.query(BacklogItem)
                 .filter(BacklogItem.id == s.backlog_id).first())
        elif args.get("task_id") is not None:
            t = (db.query(BacklogItem)
                 .filter(BacklogItem.id == args["task_id"]).first())
        elif args.get("titulo_task"):
            ts = (db.query(BacklogItem)
                  .filter(BacklogItem.title.ilike(f"%{args['titulo_task']}%"))
                  .all())
            if len(ts) > 1:
                return json.dumps(
                    {"erro": "task ambígua — use task_id",
                     "candidatas": [{"id": str(x.id), "titulo": x.title,
                                     "status": x.status} for x in ts]},
                    ensure_ascii=False)
            t = ts[0] if ts else None
        if s is None:
            if not t:
                return json.dumps(
                    {"erro": "task não encontrada — informe subtask_id, "
                             "task_id ou titulo_task"}, ensure_ascii=False)
            q = (db.query(BacklogSubtask)
                 .filter(BacklogSubtask.backlog_id == t.id))
            if args.get("ordem") is not None:
                s = q.filter(
                    BacklogSubtask.execution_order == args["ordem"]).first()
            elif args.get("titulo_subtask"):
                subs = q.filter(
                    BacklogSubtask.title.ilike(
                        f"%{args['titulo_subtask']}%")).all()
                if len(subs) > 1:
                    return json.dumps(
                        {"erro": "match ambíguo — use subtask_id ou ordem",
                         "candidatas": [{"id": str(x.id),
                                         "ordem": x.execution_order,
                                         "titulo": x.title} for x in subs]},
                        ensure_ascii=False)
                s = subs[0] if subs else None
        if not s:
            return json.dumps({"erro": "subtask não encontrada"},
                              ensure_ascii=False)
        alteracoes = {}
        if args.get("novo_status"):
            s.status = args["novo_status"]
            alteracoes["status"] = s.status
        if args.get("novo_titulo"):
            s.title = args["novo_titulo"][:250]
            alteracoes["titulo"] = s.title
        if not alteracoes:
            return json.dumps({"erro": "nenhuma alteração informada"},
                              ensure_ascii=False)
        db.commit()
        return json.dumps({"ok": True, "task": t.title,
                           "subtask": s.title, "ordem": s.execution_order,
                           "alteracoes": alteracoes}, ensure_ascii=False)

    return json.dumps({"erro": "ferramenta desconhecida"})


def chat_anthropic(messages: list, db: Session, model: str | None = None) -> str:
    client = get_anthropic()
    for _ in range(12):
        resp = client.messages.create(
            model=model or ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if resp.stop_reason == "max_tokens":
            txt = "".join(b.text for b in resp.content if b.type == "text")
            return (txt + "\n\n[resposta truncada — limite de tokens]") \
                if txt else ("Resposta truncada pelo limite de tokens — "
                             "tente um pedido menor ou dividido.")
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                try:
                    out = executar_tool(block.name, block.input, db)
                except Exception as e:
                    out = json.dumps({"erro": f"argumentos invalidos: "
                                      f"{type(e).__name__} {e}"},
                                     ensure_ascii=False)
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


def chat_openai(messages: list, db: Session, model: str | None = None, provider: str = "openai") -> str:
    client = get_openai(provider)
    msgs = [{"role": "system", "content": SYSTEM}] + messages
    for _ in range(12):
        resp = client.chat.completions.create(
            model=model or COMPAT_PROVIDERS[provider]["default_model"],
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
            try:
                out = executar_tool(tc.function.name, args, db)
            except Exception as e:
                out = json.dumps({"erro": f"argumentos invalidos: "
                                  f"{type(e).__name__} {e}"},
                                 ensure_ascii=False)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": out,
            })
    return "Não consegui concluir a operação (limite de passos)."

class VozRequest(BaseModel):
    texto: str


@router.post("/ai/voz")
def ai_voz(req: VozRequest, db: Session = Depends(get_db)):
    """Executor de comandos de voz: texto transcrito -> Fable -> acao."""
    instrucao = (
        "Comando de voz transcrito (pode conter erros de transcricao). "
        "Execute as acoes pedidas usando as tools disponiveis. "
        "Responda em no maximo 3 frases curtas confirmando o que foi feito, "
        "sem markdown — a resposta vira mensagem de Telegram.\n\n"
        f"Comando: {req.texto}"
    )
    messages = [{"role": "user", "content": instrucao}]
    try:
        reply = chat_anthropic(messages, db)
    except Exception as e:
        return {"reply": f"Erro ao executar: {type(e).__name__} - {e}",
                "error": True}
    return {"reply": reply}


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
        if provider in COMPAT_PROVIDERS:
            reply = chat_openai(messages, db, req.model, provider)
        else:
            provider = "anthropic"
            reply = chat_anthropic(messages, db, req.model)
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
