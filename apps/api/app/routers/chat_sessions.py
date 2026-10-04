from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.chat import ChatSession, ChatMessage as ChatMessageDB
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.schemas.chat import SessionFromTask, SessionUpdate, BancadaPlanningRequest
from app.services import autoridade, chat_audit
from app.services.handoff import active_plan_for_task, PLANNING_TASK_STATUSES

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sessao_out(sessao: ChatSession, projeto: Project | None = None) -> dict:
    """Forma única da sessão na API — evita divergência entre listar e abrir."""
    return {
        "id": str(sessao.id),
        "title": sessao.title,
        "project_id": str(sessao.project_id) if sessao.project_id else None,
        "project_slug": projeto.slug if projeto else None,
        "project_name": projeto.name if projeto else None,
        "authority": autoridade.normalizar(sessao.authority),
        "backlog_id": str(sessao.task_id) if getattr(sessao, 'task_id', None) else None,
        "created_at": str(sessao.created_at),
        "updated_at": str(sessao.updated_at),
    }


def _projetos_das_sessoes(db: Session, sessoes: list[ChatSession]) -> dict:
    """Resolve os projetos em uma consulta só, não uma por sessão."""
    ids = {s.project_id for s in sessoes if s.project_id}
    if not ids:
        return {}
    return {
        projeto.id: projeto
        for projeto in db.query(Project).filter(Project.id.in_(ids)).all()
    }


def _get_sessao(db: Session, session_id: str) -> ChatSession:
    try:
        session_uuid = UUID(str(session_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    sessao = db.query(ChatSession).filter(ChatSession.id == session_uuid).first()
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return sessao


def _markdown_value(value: object | None, fallback: str = "Não informado") -> str:
    """Mantém valores do banco dentro da estrutura Markdown da ficha."""
    text = str(value).strip() if value is not None else ""
    if not text:
        return fallback
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _task_context(
    task: BacklogItem, project: Project, subtasks: list[BacklogSubtask]
) -> str:
    lines = [
        "Você está auxiliando no planejamento da seguinte tarefa do WorkDev.",
        "",
        "## Ficha técnica da tarefa",
        f"- **Task ID:** `{task.id}`",
        f"- **Título:** {_markdown_value(task.title)}",
        f"- **Descrição:** {_markdown_value(task.description, 'Sem descrição')}",
        f"- **Prioridade:** {_markdown_value(task.priority)}",
        f"- **Projeto:** {_markdown_value(project.name)} (`{project.slug}`)",
        f"- **Sprint:** {_markdown_value(task.sprint, 'Sem sprint')}",
        f"- **Tipo:** {_markdown_value(task.type)}",
        "",
        "## Subtasks",
    ]
    if subtasks:
        lines.extend(
            f"- [{subtask.status}] {_markdown_value(subtask.title)}"
            for subtask in subtasks
        )
    else:
        lines.append("- Nenhuma subtask cadastrada.")
    lines.extend([
        "",
        "## Regras deste planejamento",
        "- Durante formulação e revisão, use `previsualizar_plano_execucao`; a prévia não cria plan_id nem versão.",
        "- Só chame `criar_plano_execucao` depois de o usuário aprovar explicitamente a formulação final da prévia.",
        "- Ao criar o plano oficial, use o Task ID acima e informe `aprovado_pelo_usuario=true`.",
        "- Todo plano criado deve permanecer em `draft` até aprovação humana.",
        "- Aprovar plano não inicia Build, não escolhe agente e não inicia tmux.",
        "- Após aprovação, apenas recomende o agente/modelo mais econômico e adequado; a execução é manual pelo usuário.",
    ])
    return "\n".join(lines)


def _bancada_planning_context(task: BacklogItem | None, project: Project | None, prompt_livre: str | None = None) -> str | None:
    """Prompt de planejamento da Bancada Local para LLM grande via OpenRouter."""
    if prompt_livre:
        entrada = f"Pedido livre:\n{prompt_livre}"
    else:
        if not (task.description or "").strip():
            return None  # Sinal de que a descrição está vazia
        entrada = f"Task: {task.title}\n{task.description or ''}"

    lines = [
        "Você é o planejador da Bancada Local do WorkDev. Vai quebrar o pedido abaixo em",
        "micro-tarefas para um modelo local pequeno (Qwen ~30B MoE, contexto curto, sem",
        "ferramentas). O modelo local NÃO lê arquivos: ele só vê os trechos que você",
        "indicar, com número de linha. Ele inventa nomes com facilidade quando o",
        "contexto não traz o que precisa.",
        "",
        "Regras de cada micro-tarefa:",
        "- Uma ação só: um diff pequeno, uma docstring, um teste, um resumo, uma lista.",
        "  Nada de 'refatore o módulo'.",
        "- Trechos mínimos e suficientes: inclua a definição de TODO nome que a resposta",
        "  vai precisar usar (função, constante, import). Se o diff mexe em X e chama Y,",
        "  o trecho de Y também entra. Na dúvida, inclua o bloco de imports do arquivo.",
        "- Linhas reais do arquivo atual, [caminho relativo à raiz do repo, início, fim],",
        "  inclusivas. No máximo 8 trechos e 400 linhas por trecho; prefira bem menos.",
        "- Nunca use .env, .git, chaves, certificados, node_modules ou caminhos fora do",
        "  repo: a Bancada recusa.",
        "- Instrução autocontida e explícita sobre o formato de saída. Para mudança de",
        "  código: 'Saída: diff unificado (--- a/… +++ b/…) contra os trechos, e nada",
        "  mais.' Para análise: diga o formato (lista, JSON com chaves X/Y).",
        "- Sempre inclua na instrução: 'Use só nomes que aparecem nos trechos. Se faltar",
        "  algo, responda FALTA: <o que falta> em vez de inventar.'",
        "- espera_diff: true quando a saída esperada é um diff. As checagens rodam",
        "  `git apply --check` contra a base e acusam erro se não vier diff.",
        "- exige: até 5 pares {regex: explicação} com o essencial que a resposta precisa",
        "  ACRESCENTAR (ex.: {'current\\\\(\\\\)': 'usar current() para ler a chave'}).",
        "  É expressão regular Python, procurada só no código NOVO: linhas '+' do diff",
        "  (ou blocos de código, se não houver diff). Escape parênteses e pontos.",
        "- max_tokens: o suficiente para a saída, entre 64 e 4000 (diff pequeno ~400-800,",
        "  teste ~800-1500, resumo ~300-600).",
        "- id: único, só letras, números, _ e -, até 80 caracteres, descritivo.",
        "- Ordene as tarefas para que cada uma seja independente: o modelo local não vê",
        "  a resposta das anteriores.",
        "- Se o pedido não cabe em micro-tarefas (precisa de muitos arquivos, decisão de",
        "  arquitetura, migração de banco), NÃO force: devolva {\"tarefas\": [],",
        "  \"fora_do_alcance\": \"<motivo>\"}.",
        "",
        "Responda APENAS com JSON válido, sem texto antes ou depois:",
        "{\"tarefas\": [ {\"id\": \"...\", \"instrucao\": \"...\", \"trechos\": [[\"caminho\", ini, fim]],",
        "               \"max_tokens\": 800, \"espera_diff\": true, \"exige\": {\"regex\": \"explicação\"}} ]}",
        "",
        f"Contexto do projeto: {project.name if project else 'N/A'} ({project.slug if project else 'N/A'})",
        "",
        entrada,
    ]
    return "\n".join(lines)


def planning_eligibility(db: Session, task) -> dict:
    if task.status not in PLANNING_TASK_STATUSES:
        return {'eligible': False, 'code': 'task_not_eligible',
            'message': 'Somente tarefas abertas podem ser enviadas ao AI Hub.'}
    active = active_plan_for_task(db, task.id)
    if active:
        return {'eligible': False, 'code': 'active_plan_exists',
            'message': f'Já existe um plano {active.status} para esta tarefa (versão {active.version}).',
            'plan_id': str(active.id), 'plan_status': active.status}
    return {'eligible': True, 'code': None, 'message': None}


@router.get('/chat/sessions/from-task/{task_id}/eligibility')
def task_planning_eligibility(task_id: UUID, db: Session = Depends(get_db)):
    task = db.query(BacklogItem).filter(BacklogItem.id == task_id).first()
    if not task:
        raise HTTPException(404, 'Task não encontrada')
    return {'backlog_id': str(task.id), **planning_eligibility(db, task)}


@router.post("/chat/sessions/from-task", status_code=201)
def criar_sessao_da_task(
    payload: SessionFromTask, db: Session = Depends(get_db)
):
    task = db.query(BacklogItem).filter(
        BacklogItem.id == payload.task_id
    ).with_for_update().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada")

    project = db.query(Project).filter(Project.id == task.project_id).first()
    if not project:
        raise HTTPException(status_code=409, detail="Projeto da task não encontrado")

    eligibility = planning_eligibility(db, task)
    if not eligibility['eligible']:
        raise HTTPException(status_code=409, detail=eligibility)

    existing_session = db.query(ChatSession).filter(ChatSession.task_id == task.id).first()
    if existing_session:
        return {
            **sessao_out(existing_session, project),
            "task_id": str(task.id),
            "task_title": task.title,
            "backlog_id": str(task.id),
        }


    subtasks = (
        db.query(BacklogSubtask)
        .filter(BacklogSubtask.backlog_id == task.id)
        .order_by(BacklogSubtask.execution_order.asc(), BacklogSubtask.created_at.asc())
        .all()
    )
    session = ChatSession(
        title=f"Planejar: {task.title}"[:255],
        project_id=project.id,
        task_id=task.id,
        authority=autoridade.PLAN,
    )
    try:
        db.add(session)
        db.flush()
        db.add(ChatMessageDB(
            session_id=session.id,
            role="system",
            content=_task_context(task, project, subtasks),
        ))
        db.commit()
        db.refresh(session)
    except IntegrityError:
        db.rollback()
        session = db.query(ChatSession).filter(ChatSession.task_id == task.id).first()
        if session is None:
            raise

    return {
        **sessao_out(session, project),
        "task_id": str(task.id),
        "task_title": task.title,
        "backlog_id": str(task.id),
    }


@router.post("/chat/bancada/planejar", status_code=201)
def criar_sessao_planejamento_bancada(
    payload: BancadaPlanningRequest, db: Session = Depends(get_db)
):
    """Cria uma sessão de chat para planejar uma task da Bancada Local.

    Recebe task_id ou prompt livre. Se task_id, valida que a task tem descrição.
    Retorna uma sessão em modo OBSERVE com o prompt do planejador.
    """
    if not payload.task_id and not payload.prompt:
        raise HTTPException(422, "Forneça task_id ou prompt")

    task = None
    project = None

    if payload.task_id:
        task = db.query(BacklogItem).filter(
            BacklogItem.id == payload.task_id
        ).first()
        if not task:
            raise HTTPException(404, "Task não encontrada")
        project = db.query(Project).filter(Project.id == task.project_id).first()

        # Validação: recusa task sem descrição
        if not (task.description or "").strip():
            raise HTTPException(409, {
                "code": "descricao_vazia",
                "message": "A task não tem descrição. Peça a descrição antes de planejar."
            })
    else:
        # Prompt livre: sem projeto específico
        project = None

    # Monta o prompt de planejamento
    prompt_content = _bancada_planning_context(task, project, payload.prompt)
    if prompt_content is None:
        raise HTTPException(409, "Task sem descrição")

    # Cria a sessão em modo OBSERVE (somente leitura)
    session = ChatSession(
        title=f"Planejar Bancada: {task.title if task else 'Prompt livre'}"[:255],
        project_id=project.id if project else None,
        task_id=task.id if task else None,
        authority=autoridade.OBSERVE,  # Somente leitura
    )
    try:
        db.add(session)
        db.flush()
        db.add(ChatMessageDB(
            session_id=session.id,
            role="system",
            content=prompt_content,
        ))
        db.commit()
        db.refresh(session)
    except IntegrityError:
        db.rollback()
        raise HTTPException(500, "Erro ao criar sessão de planejamento")

    return {
        **sessao_out(session, project),
        "task_id": str(task.id) if task else None,
        "task_title": task.title if task else None,
    }


@router.get("/chat/sessions")
def listar_sessoes(
    project_id: UUID | None = Query(
        None, description="filtra as conversas de um projeto"
    ),
    db: Session = Depends(get_db),
):
    consulta = db.query(ChatSession)
    if project_id is not None:
        consulta = consulta.filter(ChatSession.project_id == project_id)
    sessoes = consulta.order_by(ChatSession.updated_at.desc()).limit(50).all()
    projetos = _projetos_das_sessoes(db, sessoes)
    return [
        sessao_out(sessao, projetos.get(sessao.project_id)) for sessao in sessoes
    ]


@router.get("/chat/sessions/{session_id}")
def carregar_sessao(session_id: str, db: Session = Depends(get_db)):
    sessao = _get_sessao(db, session_id)
    linhas = (
        db.query(ChatMessageDB)
        .filter(ChatMessageDB.session_id == sessao.id)
        .order_by(ChatMessageDB.created_at.asc())
        .all()
    )
    # Eventos de auditoria vivem na mesma tabela, mas saem em campo separado:
    # nunca entram no array que o cliente reenvia ao modelo.
    conversa, eventos = chat_audit.separar(linhas)
    projeto = (
        db.query(Project).filter(Project.id == sessao.project_id).first()
        if sessao.project_id
        else None
    )
    return {
        **sessao_out(sessao, projeto),
        "messages": [
            {"role": m.role, "content": m.content} for m in conversa
        ],
        "events": [chat_audit.evento_out(e) for e in eventos],
    }


@router.patch("/chat/sessions/{session_id}")
def atualizar_contexto(
    session_id: str,
    payload: SessionUpdate,
    db: Session = Depends(get_db),
):
    """Troca o projeto ativo e/ou a autoridade da conversa.

    Omitir um campo não faz nada; mandar `project_id: null` devolve a conversa
    ao escopo global. A distinção é intencional e vem de `exclude_unset`.

    Toda troca de autoridade e de projeto deixa evento de auditoria.
    """
    sessao = _get_sessao(db, session_id)
    dados = payload.model_dump(exclude_unset=True)
    if not dados:
        raise HTTPException(status_code=422, detail="Nada a atualizar")

    projeto = (
        db.query(Project).filter(Project.id == sessao.project_id).first()
        if sessao.project_id
        else None
    )

    if "project_id" in dados:
        if getattr(sessao, 'task_id', None) and dados['project_id'] != sessao.project_id:
            raise HTTPException(409, 'Conversa vinculada a uma task: abra outra conversa para trocar de projeto.')
        anterior = projeto.slug if projeto else None
        if dados["project_id"] is not None:
            projeto = (
                db.query(Project)
                .filter(Project.id == dados["project_id"])
                .first()
            )
            if not projeto:
                raise HTTPException(
                    status_code=422, detail="Projeto não encontrado"
                )
            sessao.project_id = projeto.id
        else:
            projeto = None
            sessao.project_id = None
        novo = projeto.slug if projeto else None
        if anterior != novo:
            chat_audit.registrar_troca_projeto(db, sessao, anterior, novo)

    if "authority" in dados and dados["authority"] is not None:
        anterior = autoridade.normalizar(sessao.authority)
        novo = dados["authority"]
        if anterior != novo:
            chat_audit.registrar_troca_autoridade(db, sessao, anterior, novo)
            sessao.authority = novo

    db.commit()
    db.refresh(sessao)
    return sessao_out(sessao, projeto)


@router.delete("/chat/sessions/{session_id}")
def apagar_sessao(session_id: str, db: Session = Depends(get_db)):
    sessao = _get_sessao(db, session_id)
    db.delete(sessao)
    db.commit()
    return {"ok": True}
