import os
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session
from anthropic import Anthropic
from openai import OpenAI
from app.database import SessionLocal
from app.models.project import Project
from app.models.backlog import BacklogItem
from app.models.subtask import BacklogSubtask
from app.models.knowledge import KnowledgeEntry
from app.models.adr import ADR
from app.models.handoff import ExecutionPlan
from app.models.chat import ChatSession, ChatMessage as ChatMessageDB
from app.services.engineering_graph import graph_sync
from app.services.handoff import HandoffError, create_plan

router = APIRouter()

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_anthropic_client = None
_openai_client = None


def get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(timeout=30)
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
    "ollama": {"base_url": "https://ollama.com/v1/",
               "env_key": "OLLAMA_API_KEY",
               "default_model": os.getenv("OLLAMA_MODEL",
                                            "gpt-oss:20b")},
}


def get_openai(provider: str = "openai") -> OpenAI:
    if provider not in _compat_clients:
        cfg = COMPAT_PROVIDERS[provider]
        kwargs = {"api_key": os.getenv(cfg["env_key"])}
        if cfg["base_url"]:
            kwargs["base_url"] = cfg["base_url"]
        _compat_clients[provider] = OpenAI(timeout=30, **kwargs)
    return _compat_clients[provider]


SYSTEM = (
    "Você é o assistente do WorkDev, plataforma de engenharia do Cláudio "
    "(BPF Consult). Responda sempre em português do Brasil, curto e direto. "
    "O AI Hub é o estágio PLAN: consulte contexto, registre decisões e crie "
    "planos estruturados, mas nunca diga que executou código, testes ou deploy. "
    "O estágio BUILD acontece nos Agents depois da aprovação do plano. "
    "Use as ferramentas para consultar ou modificar projetos, backlog e subtasks. "
    "Slugs: workdev-core, nutrigestor-crm, agente-pessoal, "
    "openclaw, feed-bpf, nutricontrole."
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def build_project_system(slug: str, db: Session) -> str | None:
    project = db.query(Project).filter(Project.slug == slug).first()
    if project is None:
        return None
    itens = (
        db.query(BacklogItem)
        .filter(BacklogItem.project_id == project.id)
        .order_by(BacklogItem.rank.asc().nullslast(), BacklogItem.created_at.desc())
        .limit(20)
        .all()
    )
    por_status: dict[str, int] = {}
    for item in itens:
        por_status[item.status] = por_status.get(item.status, 0) + 1
    resumo_itens = "\n".join(
        f"- [{item.status}/{item.priority}] {item.title}" for item in itens
    ) or "Backlog vazio."
    return (
        f"{SYSTEM}\n\n"
        f"Contexto desta conversa: projeto '{project.name}' (slug: {project.slug}), "
        f"status geral: {project.status}, tipo: {project.type}.\n"
        f"Resumo do backlog ({sum(por_status.values())} itens, por status: {por_status}):\n"
        f"{resumo_itens}\n"
        f"Responda focado neste projeto, a menos que o usuário peça algo sobre outro."
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: str | None = None
    model: str | None = None
    session_id: str | None = None
    project_slug: str | None = None
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
                "task_id": {"type": "string", "description": "opcional; UUID da task relacionada"},
                "titulo_task": {"type": "string", "description": "opcional; título exato da task relacionada"},
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
    {
        "name": "criar_plano_execucao",
        "description": "Cria um plano de execução versionado em rascunho para uma task. Use ao finalizar o planejamento; o plano será aprovado e enviado ao Build pela interface.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "UUID da task; preferencial"},
                "titulo_task": {"type": "string", "description": "alternativa ao UUID"},
                "projeto_slug": {"type": "string", "description": "use para desambiguar o título"},
                "objetivo": {"type": "string"},
                "escopo": {"type": "string"},
                "restricoes": {"type": "array", "items": {"type": "string"}},
                "criterios_aceite": {"type": "array", "items": {"type": "string"}},
                "validacoes": {"type": "array", "items": {"type": "string"}},
                "notas_implementacao": {"type": "string"},
            },
            "required": ["objetivo", "criterios_aceite", "validacoes"],
        },
    },
    {
        "name": "listar_planos_execucao",
        "description": "Lista planos de execução, opcionalmente filtrados por status ou task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["draft", "approved", "needs_revision", "superseded", "discarded"]},
                "task_id": {"type": "string"},
            },
        },
    },
    {
        "name": "criar_adr",
        "description": "Registra uma decisão arquitetural (ADR), opcionalmente ligada a uma feature do backlog.",
        "input_schema": {
            "type": "object",
            "properties": {
                "projeto_slug": {"type": "string"},
                "titulo": {"type": "string"},
                "contexto": {"type": "string"},
                "decisao": {"type": "string"},
                "consequencias": {"type": "string"},
                "task_id": {"type": "string", "description": "feature relacionada, opcional"},
            },
            "required": ["projeto_slug", "titulo", "contexto", "decisao"],
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
        graph_sync.sync_safely(
            "sync_backlog", str(item.id), str(item.project_id), item.type
        )
        return json.dumps({"ok": True, "titulo": item.title, "projeto": p.name},
                          ensure_ascii=False)

    if nome == "decompor_task":
        t = (db.query(BacklogItem)
             .filter(BacklogItem.title.ilike(f"%{args['titulo_task']}%"))
             .first())
        if not t:
            return json.dumps({"erro": "task não encontrada"})
        criadas = []
        objetos = []
        for i, titulo in enumerate(args["subtasks"], start=1):
            subtask = BacklogSubtask(backlog_id=t.id, title=titulo,
                                     execution_order=i)
            db.add(subtask)
            objetos.append(subtask)
            criadas.append(titulo)
        db.commit()
        for subtask in objetos:
            graph_sync.sync_safely(
                "sync_subtask",
                str(subtask.id),
                str(t.id),
                str(t.project_id),
            )
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
        backlog_id = None
        if args.get("projeto_slug"):
            p = db.query(Project).filter(Project.slug == args["projeto_slug"]).first()
            if p:
                pid = p.id
        task = None
        if args.get("task_id"):
            task = db.query(BacklogItem).filter(
                BacklogItem.id == args["task_id"]
            ).first()
        elif args.get("titulo_task"):
            query = db.query(BacklogItem).filter(
                BacklogItem.title.ilike(args["titulo_task"])
            )
            if pid:
                query = query.filter(BacklogItem.project_id == pid)
            matches = query.all()
            if len(matches) > 1:
                return json.dumps(
                    {"erro": "mais de uma task encontrada para o conhecimento"},
                    ensure_ascii=False,
                )
            task = matches[0] if matches else None
        if args.get("task_id") or args.get("titulo_task"):
            if not task:
                return json.dumps({"erro": "task relacionada não encontrada"})
            if pid and task.project_id != pid:
                return json.dumps({"erro": "task não pertence ao projeto informado"})
            pid = task.project_id
            backlog_id = task.id
        entry = KnowledgeEntry(
            project_id=pid,
            backlog_id=backlog_id,
            title=args["titulo"],
            content=args["conteudo"],
            category=args["categoria"],
            tags=args.get("tags"),
        )
        db.add(entry)
        db.commit()
        if entry.project_id:
            graph_sync.sync_safely(
                "sync_related",
                "Knowledge",
                str(entry.id),
                str(entry.project_id),
                "LINKED_TO_KNOWLEDGE",
                str(entry.backlog_id) if entry.backlog_id else None,
            )
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

    if nome == "criar_plano_execucao":
        task = None
        if args.get("task_id"):
            task = db.query(BacklogItem).filter(
                BacklogItem.id == args["task_id"]
            ).first()
        elif args.get("titulo_task"):
            query = db.query(BacklogItem).filter(
                BacklogItem.title.ilike(f"%{args['titulo_task']}%")
            )
            if args.get("projeto_slug"):
                project = db.query(Project).filter(
                    Project.slug == args["projeto_slug"]
                ).first()
                if not project:
                    return json.dumps({"erro": "projeto não encontrado"}, ensure_ascii=False)
                query = query.filter(BacklogItem.project_id == project.id)
            matches = query.all()
            if len(matches) > 1:
                return json.dumps(
                    {"erro": "task ambígua — use task_id",
                     "candidatas": [{"id": str(row.id), "titulo": row.title}
                                    for row in matches]}, ensure_ascii=False,
                )
            task = matches[0] if matches else None
        if not task:
            return json.dumps(
                {"erro": "task não encontrada — informe task_id ou titulo_task"},
                ensure_ascii=False,
            )
        try:
            plan = create_plan(db, {
                "backlog_id": task.id,
                "objective": args["objetivo"],
                "scope": args.get("escopo"),
                "constraints": args.get("restricoes") or [],
                "acceptance_criteria": args.get("criterios_aceite") or [],
                "validation_steps": args.get("validacoes") or [],
                "implementation_notes": args.get("notas_implementacao"),
                "created_by": "ai_hub",
            })
        except HandoffError as error:
            return json.dumps({"erro": str(error)}, ensure_ascii=False)
        graph_sync.sync_safely(
            "sync_plan", str(plan.id), str(task.project_id), str(task.id)
        )
        return json.dumps({
            "ok": True, "plano_id": str(plan.id), "versao": plan.version,
            "status": plan.status, "task_id": str(task.id), "task": task.title,
            "proximo_passo": "Revisar e aprovar no painel Planos do AI Hub",
        }, ensure_ascii=False)

    if nome == "listar_planos_execucao":
        query = db.query(ExecutionPlan)
        if args.get("status"):
            query = query.filter(ExecutionPlan.status == args["status"])
        if args.get("task_id"):
            query = query.filter(ExecutionPlan.backlog_id == args["task_id"])
        rows = query.order_by(ExecutionPlan.created_at.desc()).limit(30).all()
        tasks = {
            row.id: row.title for row in db.query(BacklogItem).filter(
                BacklogItem.id.in_([plan.backlog_id for plan in rows])
            ).all()
        } if rows else {}
        return json.dumps([
            {"id": str(plan.id), "task_id": str(plan.backlog_id),
             "task": tasks.get(plan.backlog_id), "versao": plan.version,
             "status": plan.status, "objetivo": plan.objective}
            for plan in rows
        ], ensure_ascii=False)

    if nome == "criar_adr":
        project = db.query(Project).filter(
            Project.slug == args["projeto_slug"]
        ).first()
        if not project:
            return json.dumps({"erro": "projeto não encontrado"}, ensure_ascii=False)
        feature_id = None
        if args.get("task_id"):
            feature = db.query(BacklogItem).filter(
                BacklogItem.id == args["task_id"],
                BacklogItem.project_id == project.id,
                BacklogItem.type == "feature",
            ).first()
            if not feature:
                return json.dumps(
                    {"erro": "task_id não é uma feature deste projeto"},
                    ensure_ascii=False,
                )
            feature_id = feature.id
        adr = ADR(
            project_id=project.id, feature_id=feature_id,
            title=args["titulo"], context=args["contexto"],
            decision=args["decisao"], consequences=args.get("consequencias"),
            status="proposed",
        )
        db.add(adr)
        db.commit()
        db.refresh(adr)
        graph_sync.sync_safely(
            "sync_related", "ADR", str(adr.id), str(project.id),
            "LINKED_TO_ADR", str(feature_id) if feature_id else None,
        )
        return json.dumps(
            {"ok": True, "adr_id": str(adr.id), "titulo": adr.title,
             "status": adr.status}, ensure_ascii=False,
        )

    return json.dumps({"erro": "ferramenta desconhecida"})


def chat_anthropic(messages: list, db: Session, model: str | None = None, system: str | None = None) -> str:
    client = get_anthropic()
    for _ in range(12):
        resp = client.messages.create(
            model=model or ANTHROPIC_MODEL,
            max_tokens=4096,
            system=system or SYSTEM,
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
                    db.rollback()
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


def chat_openai(messages: list, db: Session, model: str | None = None, provider: str = "openai", system: str | None = None) -> str:
    client = get_openai(provider)
    msgs = [{"role": "system", "content": system or SYSTEM}] + messages
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
                db.rollback()
                out = json.dumps({"erro": f"argumentos invalidos: "
                                  f"{type(e).__name__} {e}"},
                                 ensure_ascii=False)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": out,
            })
    return "Não consegui concluir a operação (limite de passos)."

AI_PROVIDER_KEYS = {
    "anthropic": ("Claude (Anthropic)", "ANTHROPIC_API_KEY"),
    "openai": ("OpenAI", "OPENAI_API_KEY"),
    "kimi": ("Kimi (Moonshot)", "MOONSHOT_API_KEY"),
    "gemini": ("Gemini", "GEMINI_API_KEY"),
    "openrouter": ("OpenRouter", "OPENROUTER_API_KEY"),
    "ollama": ("Ollama Cloud", "OLLAMA_API_KEY"),
}
API_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")


class ApiKeyUpdate(BaseModel):
    api_key: SecretStr


def _provider_status() -> list[dict]:
    return [
        {"provider": provider, "label": label,
         "connected": bool(os.getenv(env_name))}
        for provider, (label, env_name) in AI_PROVIDER_KEYS.items()
    ]


def _write_env_key(name: str, value: str | None) -> None:
    """Atualiza uma chave no .env sem jamais ler ou devolver outros valores."""
    path = os.path.abspath(API_ENV_FILE)
    with open(path, encoding="utf-8") as source:
        lines = source.readlines()
    escaped = (
        value.replace(chr(92), chr(92) * 2)
        .replace(chr(34), chr(92) + chr(34))
        if value else None
    )
    replacement = f'{name}="{escaped}"\n' if escaped else None
    output: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{name}="):
            found = True
            if replacement:
                output.append(replacement)
        else:
            output.append(line)
    if replacement and not found:
        output.append(replacement)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as target:
        target.writelines(output)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


@router.get("/ai/providers")
def ai_providers():
    providers = _provider_status()
    connected = sum(1 for p in providers if p["connected"])
    return {"providers": providers, "connected": connected, "total": len(providers)}


@router.put("/ai/providers/{provider}/key")
def update_ai_provider_key(provider: str, payload: ApiKeyUpdate):
    config = AI_PROVIDER_KEYS.get(provider)
    if not config:
        raise HTTPException(status_code=404, detail="Provider não encontrado")
    value = payload.api_key.get_secret_value().strip()
    if not value or "\n" in value or "\r" in value:
        raise HTTPException(status_code=422, detail="Chave inválida")
    env_name = config[1]
    _write_env_key(env_name, value)
    os.environ[env_name] = value
    return {"provider": provider, "connected": True}


@router.delete("/ai/providers/{provider}/key")
def delete_ai_provider_key(provider: str):
    config = AI_PROVIDER_KEYS.get(provider)
    if not config:
        raise HTTPException(status_code=404, detail="Provider não encontrado")
    env_name = config[1]
    _write_env_key(env_name, None)
    os.environ.pop(env_name, None)
    return {"provider": provider, "connected": False}


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

    system = build_project_system(req.project_slug, db) if req.project_slug else None

    try:
        if provider in COMPAT_PROVIDERS:
            reply = chat_openai(messages, db, req.model, provider, system=system)
        else:
            provider = "anthropic"
            reply = chat_anthropic(messages, db, req.model, system=system)
    except Exception as e:
        reply = f"Erro no provider {provider}: {type(e).__name__} - {e}"
        return {"reply": reply, "provider": provider, "error": True,
                "session_id": str(session.id) if session else None}

    if session:
        try:
            db.add(ChatMessageDB(session_id=session.id,
                                 role="assistant", content=reply))
            session.updated_at = __import__("datetime").datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
    return {"reply": reply, "provider": provider,
            "session_id": str(session.id) if session else None}
