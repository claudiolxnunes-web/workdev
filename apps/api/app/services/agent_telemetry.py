"""Telemetria de consumo por AgentRun: tokens, custo e de onde o número veio.

Por que uma tabela própria (e não colunas em `agent_runs`):

- uma run pode acionar **mais de um** provedor; somar tudo na linha da run
  esconderia a composição do gasto;
- o número precisa carregar **a origem dele** — oficial (veio da API do
  provedor ou do runtime) ou estimado (derivado do transcript e do preço de
  catálogo). Sem isso, um número estimado apareceria ao lado de um faturado,
  como se fossem a mesma coisa;
- o dinheiro precisa carregar **o que ele significa** — despesa marginal
  (`paid_api`), o que já está pago por assinatura (`included_plan`),
  franquia (`free_quota`) ou runtime próprio (`local`).

Regra de honestidade que vale para todo este módulo: **não se inventa
número**. Sem contagem oficial, o registro é estimado a partir de fonte
declarada e marcado como tal; sem nenhuma fonte, **não se grava linha**.
Uma linha vazia é ruído que depois vira relatório.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
import uuid

from sqlalchemy.orm import Session


SOURCE_OFFICIAL = "official"
SOURCE_ESTIMATED = "estimated"

COST_LOCAL = "local"
COST_FREE_QUOTA = "free_quota"
COST_INCLUDED_PLAN = "included_plan"
COST_PAID_API = "paid_api"

# Runtime da própria VPS (ou dela): sem cobrança por token.
RUNTIMES_PROPRIOS = {
    "local",
    "local-code",
    "ollama",
    "llamacpp",
    "gpu-hostinger",
    "gpu-runpod",
}

# Agentes de CLI que rodam sob assinatura: o consumo não vira despesa
# marginal, ele consome cota que já foi paga.
AGENTES_POR_ASSINATURA = {"claude", "codex", "gemini"}


def custo_da_run(agent: str | None, provider: str | None) -> str:
    """Classifica o custo marginal de uma chamada, pelo agente e pelo provedor."""
    nome_provedor = (provider or "").strip().lower()
    nome_agente = (agent or "").strip().lower()

    if nome_provedor in RUNTIMES_PROPRIOS:
        return COST_LOCAL

    if nome_agente in AGENTES_POR_ASSINATURA:
        return COST_INCLUDED_PLAN

    return COST_PAID_API


def custo_do_catalogo(
    db: Session,
    model: str | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Decimal | None:
    """Custo estimado a partir do preço de catálogo (USD).

    Devolve None quando o modelo não está no catálogo: sem preço conhecido,
    não há número honesto — e um chute aqui apareceria como faturamento.
    """
    if not model:
        return None

    from app.models.ai_routing import AIModelCatalog

    alvo = model.strip().lower()

    linha = (
        db.query(AIModelCatalog)
        .filter(AIModelCatalog.active.is_(True))
        .filter(
            (AIModelCatalog.provider_model_id == model)
            | (AIModelCatalog.id == model)
        )
        .first()
    )

    if linha is None:
        linha = (
            db.query(AIModelCatalog)
            .filter(AIModelCatalog.active.is_(True))
            .filter(AIModelCatalog.provider_model_id.ilike(alvo))
            .first()
        )

    if linha is None:
        return None

    entrada = linha.input_cost_per_million
    saida = linha.output_cost_per_million

    if entrada is None and saida is None:
        return None

    total = Decimal("0")

    if input_tokens and entrada is not None:
        total += Decimal(input_tokens) * Decimal(entrada) / Decimal(1_000_000)

    if output_tokens and saida is not None:
        total += Decimal(output_tokens) * Decimal(saida) / Decimal(1_000_000)

    return total.quantize(Decimal("0.000001"))


def _inteiro(valor: Any) -> int | None:
    if valor is None:
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 0 else None


def _projeto_da_run(db: Session, run: Any) -> str | None:
    backlog_id = getattr(run, "backlog_id", None)
    if not backlog_id:
        return None

    from app.models.backlog import BacklogItem

    task = db.get(BacklogItem, backlog_id)

    return str(task.project_id) if task and task.project_id else None


def registrar(
    db: Session,
    run: Any,
    *,
    agent: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost: Decimal | None = None,
    actual_cost: Decimal | None = None,
    source: str = SOURCE_OFFICIAL,
    cost_class: str | None = None,
) -> Any | None:
    """Grava uma linha de telemetria para a run, se houver número a gravar.

    Devolve None (e não grava nada) quando não há token e não há custo: uma
    linha sem número não é telemetria, é ruído.
    """
    from app.models.handoff import AgentRunTelemetry

    entrada = _inteiro(input_tokens)
    cache = _inteiro(cached_input_tokens)
    saida = _inteiro(output_tokens)

    total = None
    if entrada is not None or saida is not None:
        total = (entrada or 0) + (saida or 0)

    if total is None and estimated_cost is None and actual_cost is None:
        return None

    nome_agente = agent or getattr(run, "agent", None) or "desconhecido"
    nome_provedor = provider or getattr(run, "provider", None) or "desconhecido"
    nome_modelo = model or getattr(run, "model", None) or "desconhecido"

    linha = AgentRunTelemetry(
        run_id=run.id,
        backlog_id=getattr(run, "backlog_id", None),
        project_id=_projeto_da_run(db, run),
        agent=nome_agente[:40],
        provider=nome_provedor[:60],
        model=nome_modelo[:120],
        input_tokens=entrada,
        cached_input_tokens=cache,
        output_tokens=saida,
        total_tokens=total,
        estimated_cost=estimated_cost,
        actual_cost=actual_cost,
        currency="USD",
        source=source,
        cost_class=cost_class or custo_da_run(nome_agente, nome_provedor),
    )

    db.add(linha)
    db.flush()

    return linha


def registrar_despacho(
    db: Session,
    run: Any,
    resultado: dict,
    *,
    runtime_id: str | None = None,
    agent: str | None = None,
    model: str | None = None,
) -> Any | None:
    """Telemetria de um despacho para runtime local (Ollama / llama.cpp).

    O runtime próprio não cobra por token: o que se registra é o consumo de
    contexto, com `cost_class = 'local'`, para que a soma de dinheiro do
    WorkDev não misture o que é despesa marginal.
    """
    entrada = _inteiro(
        resultado.get("input_tokens")
        or resultado.get("prompt_tokens")
        or resultado.get("prompt_eval_count")
    )
    saida = _inteiro(
        resultado.get("output_tokens")
        or resultado.get("completion_tokens")
        or resultado.get("eval_count")
    )

    if entrada is None and saida is None:
        return None

    return registrar(
        db,
        run,
        agent=agent or getattr(run, "agent", None),
        provider=runtime_id or "local",
        model=model or resultado.get("model"),
        input_tokens=entrada,
        output_tokens=saida,
        # Runtime próprio: não há cobrança por token. O zero aqui é o custo de
        # API, e o `cost_class` diz que o consumo foi de compute da própria VPS.
        estimated_cost=Decimal("0.000000"),
        actual_cost=None,
        source=SOURCE_OFFICIAL,
        cost_class=COST_LOCAL,
    )


def consulta_resumo(
    db: Session,
    *,
    project_id: str | None = None,
    agent: str | None = None,
    cost_class: str | None = None,
    source: str | None = None,
):
    """Consulta agregada do consumo, com os filtros aplicados.

    Fica separada do `resumo` para que o SQL possa ser conferido sem
    tocar o banco.
    """
    from sqlalchemy import func

    from app.models.handoff import AgentRunTelemetry

    consulta = db.query(AgentRunTelemetry)

    if project_id:
        # A coluna é UUID: comparar com texto brokenaria em produção.
        consulta = consulta.filter(
            AgentRunTelemetry.project_id == uuid.UUID(str(project_id))
        )
    if agent:
        consulta = consulta.filter(AgentRunTelemetry.agent == agent)
    if cost_class:
        consulta = consulta.filter(AgentRunTelemetry.cost_class == cost_class)
    if source:
        consulta = consulta.filter(AgentRunTelemetry.source == source)

    return (
        consulta.with_entities(
            AgentRunTelemetry.agent.label("agent"),
            AgentRunTelemetry.provider.label("provider"),
            AgentRunTelemetry.model.label("model"),
            AgentRunTelemetry.source.label("source"),
            AgentRunTelemetry.cost_class.label("cost_class"),
            AgentRunTelemetry.currency.label("currency"),
            func.count(AgentRunTelemetry.id).label("calls"),
            func.coalesce(
                func.sum(AgentRunTelemetry.input_tokens), 0
            ).label("input_tokens"),
            func.coalesce(
                func.sum(AgentRunTelemetry.output_tokens), 0
            ).label("output_tokens"),
            func.coalesce(
                func.sum(AgentRunTelemetry.total_tokens), 0
            ).label("total_tokens"),
            func.coalesce(
                func.sum(AgentRunTelemetry.estimated_cost), 0
            ).label("estimated_cost"),
        )
        .group_by(
            AgentRunTelemetry.agent,
            AgentRunTelemetry.provider,
            AgentRunTelemetry.model,
            AgentRunTelemetry.source,
            AgentRunTelemetry.cost_class,
            AgentRunTelemetry.currency,
        )
    )


def resumo(
    db: Session,
    *,
    project_id: str | None = None,
    agent: str | None = None,
    cost_class: str | None = None,
    source: str | None = None,
) -> list[dict]:
    """Consumo agregado por agente e provedor.

    A resposta vem agrupada por `source` e `cost_class`: somar oficial com
    estimado na mesma linha é exatamente o erro que a separação existe para
    evitar.
    """
    linhas = consulta_resumo(
        db,
        project_id=project_id,
        agent=agent,
        cost_class=cost_class,
        source=source,
    ).all()

    return [
        {
            "agent": agente,
            "provider": provedor,
            "model": modelo,
            "source": origem,
            "cost_class": classe,
            "currency": moeda,
            "calls": int(chamadas or 0),
            "input_tokens": int(entrada or 0),
            "output_tokens": int(saida or 0),
            "total_tokens": int(total or 0),
            "estimated_cost": float(custo or 0),
        }
        for (
            agente,
            provedor,
            modelo,
            origem,
            classe,
            moeda,
            chamadas,
            entrada,
            saida,
            total,
            custo,
        ) in linhas
    ]
