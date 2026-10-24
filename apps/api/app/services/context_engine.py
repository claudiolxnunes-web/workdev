"""Context Engine do AI Hub — monta o que o WorkDev sabe sobre si mesmo.

Fase E1.2 do WorkDev Conversational Core.

Dois escopos, uma mesma forma:

- **global**: "Como estão meus projetos?", "O que precisa da minha atenção?"
- **projeto**: "Continue de onde paramos", "Qual é o próximo passo?"

Desenho em duas camadas, porque elas falham de jeitos diferentes:

1. `coletar_*` — cada função faz **uma** consulta e devolve estrutura simples.
   Falha se o banco falhar; é onde mora o custo.
2. `renderizar_contexto` — função pura, dict → markdown. Não toca em nada, é
   testável sem banco e é o que de fato entra no prompt.

A camada de coleta reaproveita as mesmas fontes que `services/handoff.py`
já lê para montar o contexto de uma execução (`build_context`): projeto,
backlog, subtasks, knowledge, ADRs, planos. A diferença é o recorte — lá é uma
task; aqui é uma conversa.

O contexto é **somente leitura**. Nenhuma função deste módulo escreve.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, ExecutionPlan
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.subtask import BacklogSubtask


ESCOPO_GLOBAL = "global"
ESCOPO_PROJETO = "projeto"

# Limites de coleta. O contexto compete com a conversa pelo mesmo orçamento de
# tokens: melhor um recorte curto e sempre presente do que um dump que force
# truncamento no meio do histórico.
LIMITE_BACKLOG_ABERTO = 12
LIMITE_ATENCAO_GLOBAL = 8
LIMITE_KNOWLEDGE = 5
LIMITE_ADRS = 5
LIMITE_PLANOS = 5
LIMITE_EXECUCOES = 5
LIMITE_SUBTASKS = 10
# Corte de texto livre (objetivo de plano, erro de execução). Campos assim não
# têm teto no banco e sozinhos dominam o prompt se entrarem inteiros.
LIMITE_TEXTO_LIVRE = 160

STATUS_ABERTOS = ("todo", "doing", "blocked")
PRIORIDADES_ATENCAO = ("critical", "high")
RUN_STATUS_ATIVOS = ("queued", "running", "blocked", "review")
PLANO_STATUS_VIVOS = ("draft", "approved", "needs_revision")

# Ordem de exibição; qualquer status fora dela vai para o fim, em ordem alfabética.
ORDEM_STATUS = {"doing": 0, "blocked": 1, "todo": 2, "done": 3}
ORDEM_PRIORIDADE = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Coleta — uma consulta por função
# --------------------------------------------------------------------------


def coletar_projetos(db: Session) -> list[dict[str, Any]]:
    """Todos os projetos com slug e status. É o universo real, não uma lista fixa."""
    linhas = (
        db.query(Project.slug, Project.name, Project.status, Project.type)
        .order_by(Project.name.asc())
        .all()
    )
    return [
        {"slug": linha[0], "nome": linha[1], "status": linha[2], "tipo": linha[3]}
        for linha in linhas
    ]


def coletar_resumo_backlog(db: Session, project_id: Any = None) -> dict[str, int]:
    """Contagem de itens por status. Uma agregação, não 179 linhas."""
    consulta = db.query(BacklogItem.status, func.count(BacklogItem.id))
    if project_id is not None:
        consulta = consulta.filter(BacklogItem.project_id == project_id)
    linhas = consulta.group_by(BacklogItem.status).all()
    return {linha[0]: linha[1] for linha in linhas}


def coletar_backlog_aberto(
    db: Session, project_id: Any, limite: int = LIMITE_BACKLOG_ABERTO
) -> list[dict[str, Any]]:
    """Itens abertos do projeto, na ordem em que o Backlog os apresenta."""
    linhas = (
        db.query(BacklogItem)
        .filter(
            BacklogItem.project_id == project_id,
            BacklogItem.status.in_(STATUS_ABERTOS),
        )
        .order_by(
            BacklogItem.rank.asc().nullslast(),
            BacklogItem.created_at.desc(),
        )
        .limit(limite)
        .all()
    )
    return [_item_backlog(linha) for linha in linhas]


def coletar_atencao_global(
    db: Session, limite: int = LIMITE_ATENCAO_GLOBAL
) -> list[dict[str, Any]]:
    """Itens critical/high abertos em qualquer projeto, com o nome do projeto.

    É a resposta a "o que precisa da minha atenção?" apurada no Postgres. Os
    achados do Supervisor entram por outro caminho, na E1.5.
    """
    linhas = (
        db.query(BacklogItem, Project.name, Project.slug)
        .join(Project, Project.id == BacklogItem.project_id)
        .filter(
            BacklogItem.status.in_(STATUS_ABERTOS),
            BacklogItem.priority.in_(PRIORIDADES_ATENCAO),
        )
        .order_by(
            BacklogItem.rank.asc().nullslast(),
            BacklogItem.created_at.asc(),
        )
        .limit(limite)
        .all()
    )
    resultado = []
    for item, nome_projeto, slug_projeto in linhas:
        dados = _item_backlog(item)
        dados["projeto"] = nome_projeto
        dados["projeto_slug"] = slug_projeto
        resultado.append(dados)
    return resultado


def coletar_subtasks_em_andamento(
    db: Session, project_id: Any, limite: int = LIMITE_SUBTASKS
) -> list[dict[str, Any]]:
    """Subtasks das tasks que estão em `doing` — é literalmente "onde paramos"."""
    linhas = (
        db.query(BacklogSubtask, BacklogItem.title)
        .join(BacklogItem, BacklogItem.id == BacklogSubtask.backlog_id)
        .filter(
            BacklogItem.project_id == project_id,
            BacklogItem.status == "doing",
        )
        .order_by(BacklogSubtask.execution_order.asc())
        .limit(limite)
        .all()
    )
    return [
        {
            "task": titulo_task,
            "ordem": subtask.execution_order,
            "titulo": subtask.title,
            "status": subtask.status,
            "agente": subtask.assigned_agent,
        }
        for subtask, titulo_task in linhas
    ]


def coletar_knowledge(
    db: Session, project_id: Any = None, limite: int = LIMITE_KNOWLEDGE
) -> list[dict[str, Any]]:
    """Entradas recentes do Knowledge. Títulos e tags, não o conteúdo inteiro.

    O conteúdo continua acessível pela tool `buscar_conhecimento`; aqui a função
    é sinalizar ao modelo que o registro existe.
    """
    consulta = db.query(KnowledgeEntry)
    if project_id is not None:
        consulta = consulta.filter(KnowledgeEntry.project_id == project_id)
    linhas = (
        consulta.order_by(KnowledgeEntry.created_at.desc()).limit(limite).all()
    )
    return [
        {
            "titulo": linha.title,
            "categoria": linha.category,
            "tags": linha.tags,
        }
        for linha in linhas
    ]


def coletar_adrs(
    db: Session, project_id: Any, limite: int = LIMITE_ADRS
) -> list[dict[str, Any]]:
    linhas = (
        db.query(ADR)
        .filter(ADR.project_id == project_id)
        .order_by(ADR.created_at.desc())
        .limit(limite)
        .all()
    )
    return [
        {"titulo": linha.title, "status": linha.status} for linha in linhas
    ]


def coletar_planos(
    db: Session, project_id: Any = None, limite: int = LIMITE_PLANOS
) -> list[dict[str, Any]]:
    """Planos de execução vivos (draft/approved/needs_revision)."""
    consulta = (
        db.query(ExecutionPlan, BacklogItem.title)
        .join(BacklogItem, BacklogItem.id == ExecutionPlan.backlog_id)
        .filter(ExecutionPlan.status.in_(PLANO_STATUS_VIVOS))
    )
    if project_id is not None:
        consulta = consulta.filter(BacklogItem.project_id == project_id)
    linhas = (
        consulta.order_by(ExecutionPlan.created_at.desc()).limit(limite).all()
    )
    return [
        {
            "task": titulo_task,
            "versao": plano.version,
            "status": plano.status,
            "objetivo": plano.objective,
        }
        for plano, titulo_task in linhas
    ]


def coletar_execucoes(
    db: Session, project_id: Any = None, limite: int = LIMITE_EXECUCOES
) -> list[dict[str, Any]]:
    """Execuções de agente recentes — a entidade `agent_runs` que já existe.

    Ativas primeiro; depois as mais recentes, seja qual for o desfecho.
    """
    consulta = (
        db.query(AgentRun, BacklogItem.title)
        .join(BacklogItem, BacklogItem.id == AgentRun.backlog_id)
    )
    if project_id is not None:
        consulta = consulta.filter(BacklogItem.project_id == project_id)
    linhas = (
        consulta.order_by(AgentRun.created_at.desc()).limit(limite).all()
    )
    return [
        {
            "task": titulo_task,
            "agente": run.agent,
            "status": run.status,
            "ativa": run.status in RUN_STATUS_ATIVOS,
            "resumo": run.summary,
            "erro": run.error,
        }
        for run, titulo_task in linhas
    ]


def _item_backlog(item: BacklogItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "titulo": item.title,
        "status": item.status,
        "prioridade": item.priority,
        "tipo": item.type,
        "sprint": item.sprint,
    }


# --------------------------------------------------------------------------
# Montagem — compõe as coletas em um documento único
# --------------------------------------------------------------------------


def montar_contexto_global(db: Session) -> dict[str, Any]:
    """Contexto do WorkDev inteiro: o que existe e o que está pegando fogo."""
    return {
        "escopo": ESCOPO_GLOBAL,
        "gerado_em": agora_utc().isoformat(),
        "projetos": coletar_projetos(db),
        "backlog_por_status": coletar_resumo_backlog(db),
        "atencao": coletar_atencao_global(db),
        "planos": coletar_planos(db),
        "execucoes": coletar_execucoes(db),
        "knowledge": coletar_knowledge(db),
    }


def montar_contexto_projeto(db: Session, projeto: Project) -> dict[str, Any]:
    """Contexto de um projeto: estado, backlog aberto, onde paramos e o registro."""
    return {
        "escopo": ESCOPO_PROJETO,
        "gerado_em": agora_utc().isoformat(),
        "projeto": {
            "id": str(projeto.id),
            "nome": projeto.name,
            "slug": projeto.slug,
            "status": projeto.status,
            "tipo": projeto.type,
            "stack": projeto.stack,
            "descricao": projeto.description,
            "github_url": projeto.github_url,
            "vps": projeto.vps,
            "dev_branch": projeto.dev_branch,
            "prod_branch": projeto.prod_branch,
        },
        "backlog_por_status": coletar_resumo_backlog(db, projeto.id),
        "backlog_aberto": coletar_backlog_aberto(db, projeto.id),
        "em_andamento": coletar_subtasks_em_andamento(db, projeto.id),
        "planos": coletar_planos(db, projeto.id),
        "execucoes": coletar_execucoes(db, projeto.id),
        "adrs": coletar_adrs(db, projeto.id),
        "knowledge": coletar_knowledge(db, projeto.id),
    }


def build_chat_context(db: Session, project_slug: str | None = None) -> dict[str, Any] | None:
    """Ponto de entrada único. `None` quando o slug pedido não existe.

    Sem slug, devolve o contexto global — que é o padrão do AI Hub.
    """
    if not project_slug:
        return montar_contexto_global(db)
    projeto = db.query(Project).filter(Project.slug == project_slug).first()
    if projeto is None:
        return None
    return montar_contexto_projeto(db, projeto)


# --------------------------------------------------------------------------
# Renderização — pura, dict → markdown
# --------------------------------------------------------------------------


def _cortar(texto: str | None, limite: int) -> str:
    """Corta texto livre que entra no prompt.

    Sem isto, um `agent_runs.error` com stack trace inteiro sozinho ocupa mais
    espaço que todo o resto do contexto — foi o que a medição mostrou (4657 de
    7283 caracteres vinham de cinco execuções).
    """
    if not texto:
        return ""
    limpo = " ".join(str(texto).split())
    if len(limpo) <= limite:
        return limpo
    return limpo[: limite - 1].rstrip() + "…"


def _ordenar_status(par: tuple[str, int]) -> tuple[int, str]:
    return (ORDEM_STATUS.get(par[0], len(ORDEM_STATUS)), par[0])


def _linha_status(por_status: dict[str, int]) -> str:
    if not por_status:
        return "sem itens"
    partes = [
        f"{status} {quantidade}"
        for status, quantidade in sorted(por_status.items(), key=_ordenar_status)
    ]
    total = sum(por_status.values())
    return f"{total} itens ({', '.join(partes)})"


def _linha_item(item: dict[str, Any], com_projeto: bool = False) -> str:
    prefixo = f"{item['projeto']} · " if com_projeto and item.get("projeto") else ""
    sprint = f" · sprint {item['sprint']}" if item.get("sprint") else ""
    return (
        f"- {prefixo}[{item['status']}/{item['prioridade']}] "
        f"{item['titulo']}{sprint}"
    )


def _secao(titulo: str, linhas: list[str]) -> list[str]:
    """Seção só aparece se tiver conteúdo. Cabeçalho vazio é ruído no prompt."""
    if not linhas:
        return []
    return [f"### {titulo}", *linhas, ""]


def renderizar_contexto(dados: dict[str, Any]) -> str:
    """Converte o contexto em markdown para o system prompt. Função pura."""
    if dados.get("escopo") == ESCOPO_PROJETO:
        return _renderizar_projeto(dados)
    return _renderizar_global(dados)


def _renderizar_global(dados: dict[str, Any]) -> str:
    linhas: list[str] = ["## Estado atual do WorkDev", ""]

    projetos = dados.get("projetos") or []
    if projetos:
        linhas += _secao(
            f"Projetos ({len(projetos)})",
            [f"- {p['nome']} (`{p['slug']}`) — {p['status']}" for p in projetos],
        )

    linhas += _secao(
        "Backlog consolidado",
        [_linha_status(dados.get("backlog_por_status") or {})],
    )

    linhas += _secao(
        "Precisa de atenção (critical/high em aberto)",
        [_linha_item(item, com_projeto=True) for item in dados.get("atencao") or []],
    )

    linhas += _secao(
        "Planos de execução vivos",
        [
            f"- {p['task']} · v{p['versao']} · {p['status']}"
            for p in dados.get("planos") or []
        ],
    )

    linhas += _secao(
        "Execuções recentes",
        [_linha_execucao(execucao) for execucao in dados.get("execucoes") or []],
    )

    linhas += _secao(
        "Knowledge recente",
        [_linha_knowledge(entrada) for entrada in dados.get("knowledge") or []],
    )

    return "\n".join(linhas).strip()


def _renderizar_projeto(dados: dict[str, Any]) -> str:
    projeto = dados.get("projeto") or {}
    cabecalho = [
        f"## Projeto ativo: {projeto.get('nome')} (`{projeto.get('slug')}`)",
        "",
    ]

    ficha = [
        f"- Status: {projeto.get('status')}",
        f"- Tipo: {projeto.get('tipo')}",
    ]
    for rotulo, chave in (
        ("Stack", "stack"),
        ("Repositório", "github_url"),
        ("VPS", "vps"),
        ("Branch dev", "dev_branch"),
        ("Branch prod", "prod_branch"),
    ):
        if projeto.get(chave):
            ficha.append(f"- {rotulo}: {projeto[chave]}")
    if projeto.get("descricao"):
        ficha.append(f"- Descrição: {projeto['descricao']}")

    linhas = cabecalho + _secao("Ficha", ficha)

    linhas += _secao(
        "Backlog",
        [_linha_status(dados.get("backlog_por_status") or {})],
    )

    abertos = dados.get("backlog_aberto") or []
    linhas += _secao(
        "Itens em aberto",
        [_linha_item(item) for item in abertos] or ["- nenhum item em aberto"],
    )

    linhas += _secao(
        "Onde paramos (subtasks das tasks em doing)",
        [
            f"- {s['task']} · {s['ordem']}. {s['titulo']} [{s['status']}]"
            + (f" · {s['agente']}" if s.get("agente") else "")
            for s in dados.get("em_andamento") or []
        ],
    )

    linhas += _secao(
        "Planos de execução vivos",
        [
            f"- {p['task']} · v{p['versao']} · {p['status']} — "
            f"{_cortar(p['objetivo'], LIMITE_TEXTO_LIVRE)}"
            for p in dados.get("planos") or []
        ],
    )

    linhas += _secao(
        "Execuções recentes",
        [_linha_execucao(execucao) for execucao in dados.get("execucoes") or []],
    )

    linhas += _secao(
        "ADRs",
        [f"- {adr['titulo']} [{adr['status']}]" for adr in dados.get("adrs") or []],
    )

    linhas += _secao(
        "Knowledge do projeto",
        [_linha_knowledge(entrada) for entrada in dados.get("knowledge") or []],
    )

    return "\n".join(linhas).strip()


def _linha_execucao(execucao: dict[str, Any]) -> str:
    marca = " (ativa)" if execucao.get("ativa") else ""
    linha = (
        f"- {execucao['task']} · {execucao['agente']} · "
        f"{execucao['status']}{marca}"
    )
    if execucao.get("erro"):
        linha += f" — erro: {_cortar(execucao['erro'], LIMITE_TEXTO_LIVRE)}"
    return linha


def _linha_knowledge(entrada: dict[str, Any]) -> str:
    tags = f" · {entrada['tags']}" if entrada.get("tags") else ""
    return f"- [{entrada['categoria']}] {entrada['titulo']}{tags}"
