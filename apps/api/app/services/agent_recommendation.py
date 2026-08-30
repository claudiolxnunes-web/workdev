"""Recomendação consultiva de agente/modelo para um PLAN aprovado.

O WorkDev deixou de decidir e iniciar agente automaticamente como caminho
principal. Este serviço só **recomenda**: quem decide gastar (ou ignorar a
recomendação) é o usuário, que envia manualmente ao agente escolhido.

Reaproveita, sem duplicar:
  - `task_complexity.classify_task`  → complexidade e capacidades exigidas
  - `task_complexity.describe_workload` → que tipo de trabalho o PLAN é
  - `agent_router` (catálogo, preço, cobertura de capacidades, mapa provider→agente)
  - `AIModelCatalog` → preço, categoria, contexto e flag `active`

Nada de preço hardcoded: tudo vem do Model Catalog. Nada de saldo inventado:
cota só é reportada como esgotada quando existe erro real registrado.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai_routing import AICallLog, AIModelCatalog
from app.models.handoff import AgentRun
from app.services.agent_router import (
    COMPLEXITY_MIN_CATEGORY,
    MIN_CAPABILITY_COVERAGE,
    PROVIDER_TO_AGENT,
    _agent_for_model,
    _capability_data,
    _price_index,
)
from app.services.task_complexity import (
    ComplexityAssessment,
    WorkloadProfile,
    classify_task,
    describe_workload,
)


SUPPORTED_AGENTS = (
    "codex",
    "claude",
    "kimi",
    "qwen",
    "gemini",
)


AGENT_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "kimi": "Kimi Code",
    "qwen": "Qwen Code",
    "gemini": "Gemini",
}


# Heurísticas iniciais de adequação, conforme a decisão de produto. Não são
# regras rígidas: são pesos por dimensão de trabalho detectada no PLAN.
AGENT_WORKLOAD_WEIGHTS: dict[str, dict[str, Decimal]] = {
    "codex": {
        "implementation": Decimal("3.0"),
        "repository_analysis": Decimal("1.5"),
        "review": Decimal("1.0"),
        "architecture": Decimal("0.5"),
        "documentation": Decimal("0.4"),
        "large_context": Decimal("0.3"),
        "cost_sensitive": Decimal("0.5"),
        "multimodal": Decimal("0.0"),
    },
    "claude": {
        "architecture": Decimal("3.0"),
        "review": Decimal("2.5"),
        "repository_analysis": Decimal("2.2"),
        "documentation": Decimal("2.0"),
        "implementation": Decimal("1.0"),
        "large_context": Decimal("1.0"),
        "cost_sensitive": Decimal("0.0"),
        "multimodal": Decimal("0.4"),
    },
    "gemini": {
        "large_context": Decimal("3.0"),
        "multimodal": Decimal("3.0"),
        "documentation": Decimal("1.4"),
        "review": Decimal("1.0"),
        "repository_analysis": Decimal("1.0"),
        "architecture": Decimal("0.8"),
        "implementation": Decimal("0.8"),
        "cost_sensitive": Decimal("1.5"),
    },
    "kimi": {
        "large_context": Decimal("2.2"),
        "repository_analysis": Decimal("2.0"),
        "implementation": Decimal("1.8"),
        "cost_sensitive": Decimal("2.0"),
        "review": Decimal("0.8"),
        "architecture": Decimal("0.8"),
        "documentation": Decimal("0.8"),
        "multimodal": Decimal("0.3"),
    },
    "qwen": {
        "cost_sensitive": Decimal("3.0"),
        "implementation": Decimal("2.0"),
        "large_context": Decimal("0.5"),
        "repository_analysis": Decimal("0.5"),
        "documentation": Decimal("0.3"),
        "review": Decimal("0.3"),
        "architecture": Decimal("0.0"),
        "multimodal": Decimal("0.0"),
    },
}


# Complexidade alta empurra a recomendação para agentes de maior capacidade;
# não é o preço que decide uma tarefa difícil.
COMPLEXITY_BIAS: dict[str, dict[str, Decimal]] = {
    "low": {
        "qwen": Decimal("1.5"),
        "kimi": Decimal("0.8"),
        "gemini": Decimal("0.5"),
        "codex": Decimal("0.3"),
        "claude": Decimal("-0.5"),
    },
    "medium": {
        "codex": Decimal("0.5"),
        "kimi": Decimal("0.4"),
        "qwen": Decimal("0.3"),
        "gemini": Decimal("0.2"),
        "claude": Decimal("0.2"),
    },
    "high": {
        "claude": Decimal("1.5"),
        "codex": Decimal("1.0"),
        "gemini": Decimal("0.5"),
        "kimi": Decimal("0.0"),
        "qwen": Decimal("-1.5"),
    },
    "critical": {
        "claude": Decimal("2.5"),
        "codex": Decimal("1.5"),
        "gemini": Decimal("0.8"),
        "kimi": Decimal("-0.5"),
        "qwen": Decimal("-3.0"),
    },
}


AGENT_STRENGTHS = {
    "codex": "implementação, debugging e testes direto no repositório",
    "claude": "análise arquitetural extensa, revisão técnica e documentação complexa",
    "gemini": "contexto muito grande, síntese e comparação de grandes volumes",
    "qwen": "implementação simples ou média bem delimitada, com custo baixo",
    "kimi": "implementação e análise intermediária com contexto extenso",
}


DIMENSION_REASONS = {
    "implementation": "implementação, debugging e testes",
    "architecture": "análise arquitetural e decisão de design",
    "repository_analysis": "análise ampla do repositório",
    "review": "revisão técnica e auditoria",
    "documentation": "documentação técnica",
    "large_context": "contexto extenso e síntese de grande volume",
    "multimodal": "conteúdo multimodal",
    "cost_sensitive": "restrição explícita de custo",
}


COST_CLASSES = (
    "free",
    "economic",
    "moderate",
    "premium",
    "unknown",
)


COST_LABELS = {
    "free": "gratuito",
    "economic": "econômico",
    "moderate": "moderado",
    "premium": "premium",
    "unknown": "não informado",
}


COST_RANK = {
    "free": 0,
    "economic": 1,
    "moderate": 2,
    "premium": 3,
    "unknown": 2,
}


AVAILABILITY_LABELS = {
    "available": "disponível",
    "unavailable": "indisponível",
    "unknown": "não verificada",
}


QUOTA_LABELS = {
    "exhausted": "cota/crédito esgotado",
    "unknown": "não verificada",
}


AVAILABILITY_RANK = {
    "available": 2,
    "unknown": 1,
    "unavailable": 0,
}


# Só reconhecemos cota esgotada a partir de erro real já registrado. Nunca
# estimamos saldo, tokens restantes ou créditos.
QUOTA_ERROR_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bquota\b",
        r"\bcota\b",
        r"insufficient[_ ]?(quota|credit|balance|funds)",
        r"\bcr[eé]ditos?\b",
        r"\bcredits?\s+(exhausted|depleted|remaining)",
        r"\bsaldo\b",
        r"\bbilling\b",
        r"payment[_ ]required",
        r"\b402\b",
        r"\b429\b",
        r"rate[_ ]?limit",
        r"(usage|token)[_ ]?limit",
        r"limite de (uso|tokens|cr[eé]ditos)",
        r"out of (tokens|credits)",
        r"tokens? esgotad",
    )
)


QUOTA_LOOKBACK_HOURS = 24


@dataclass(frozen=True)
class AgentOption:
    agent: str
    agent_label: str
    fit_score: Decimal
    capable: bool
    capability_score: int | None
    missing_capabilities: tuple[str, ...]
    catalog_id: str | None
    provider: str | None
    model: str | None
    model_label: str | None
    category: str | None
    context_window: int | None
    requires_confirmation: bool
    cost_class: str
    price_index: Decimal | None
    availability: str
    availability_reason: str | None
    quota: str
    quota_reason: str | None
    reason: str
    models: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "agent_label": self.agent_label,
            "fit_score": str(
                self.fit_score.quantize(Decimal("0.01"))
            ),
            "capable": self.capable,
            "capability_score": self.capability_score,
            "missing_capabilities": list(
                self.missing_capabilities
            ),
            "catalog_id": self.catalog_id,
            "provider": self.provider,
            "model": self.model,
            "model_label": self.model_label,
            "category": self.category,
            "context_window": self.context_window,
            "requires_confirmation": self.requires_confirmation,
            "cost_class": self.cost_class,
            "cost_label": COST_LABELS[self.cost_class],
            "price_index": (
                str(self.price_index)
                if self.price_index is not None
                else None
            ),
            "availability": self.availability,
            "availability_label": AVAILABILITY_LABELS[
                self.availability
            ],
            "availability_reason": self.availability_reason,
            "quota": self.quota,
            "quota_label": QUOTA_LABELS[self.quota],
            "quota_reason": self.quota_reason,
            "reason": self.reason,
            # Somente os modelos permitidos deste agente — nunca o catálogo
            # inteiro. O seletor do PLAN é montado a partir daqui.
            "models": [dict(model) for model in self.models],
        }


def _catalog_rows(db: Session) -> list[AIModelCatalog]:
    return db.query(AIModelCatalog).all()


def _rows_by_agent(
    rows: Iterable[AIModelCatalog],
) -> tuple[dict[str, list[AIModelCatalog]], dict[str, list[AIModelCatalog]]]:
    """Separa o catálogo por agente, distinguindo ativos de inativos."""
    active: dict[str, list[AIModelCatalog]] = {
        agent: [] for agent in SUPPORTED_AGENTS
    }
    inactive: dict[str, list[AIModelCatalog]] = {
        agent: [] for agent in SUPPORTED_AGENTS
    }

    for row in rows:
        agent = _agent_for_model(row)

        if agent not in active:
            continue

        if getattr(row, "active", False):
            active[agent].append(row)
        else:
            inactive[agent].append(row)

    return active, inactive


def _agent_models(
    rows: Iterable[AIModelCatalog],
) -> tuple[
    dict[str, list[AIModelCatalog]],
    dict[str, list[AIModelCatalog]],
]:
    """Modelos permitidos por agente, na ordem de capacidade do operador.

    O catálogo inteiro nunca é candidato: só as linhas que o operador vinculou
    ao agente. Modelos sem `agent_slug` continuam no catálogo servindo o AI Hub.
    """
    active: dict[str, list[AIModelCatalog]] = {}
    inactive: dict[str, list[AIModelCatalog]] = {}

    for row in rows:
        agent = (
            getattr(row, "agent_slug", None) or ""
        ).strip()

        if agent not in AGENT_LABELS:
            continue

        target = (
            active
            if getattr(row, "active", False)
            else inactive
        )

        target.setdefault(agent, []).append(row)

    def by_rank(row: AIModelCatalog) -> tuple[int, str]:
        rank = getattr(row, "agent_preference_rank", None)

        return (
            rank if rank is not None else 9999,
            str(getattr(row, "id", "")),
        )

    for group in (active, inactive):
        for agent in group:
            group[agent].sort(key=by_rank)

    return active, inactive


def _select_allowed_model(
    rows: list[AIModelCatalog],
    assessment: ComplexityAssessment,
) -> tuple[AIModelCatalog | None, int | None, tuple[str, ...], bool]:
    """Escolhe entre os modelos permitidos do agente.

    Capacidade primeiro: quem não cobre o mínimo da complexidade não é
    apresentado como adequado. Depois:

    - complexidade alta/crítica → o mais capaz (menor rank declarado);
    - baixa/média → o mais econômico que ainda serve, usando o preço do
      catálogo; quando o provider não publica preço, o rank declarado desempata
      e a alternativa mais econômica é a de maior rank.

    A categoria do catálogo não filtra nada aqui: estes são os modelos que a CLI
    do agente está configurada para rodar.
    """
    if not rows:
        return None, None, (), False

    minimum = MIN_CAPABILITY_COVERAGE[assessment.level]

    scored = []

    for row in rows:
        capability_score, _matched, missing = _capability_data(
            assessment.required_capabilities,
            getattr(row, "capabilities", None) or [],
        )

        scored.append(
            (
                row,
                capability_score,
                missing,
                capability_score >= minimum,
            )
        )

    qualifying = [item for item in scored if item[3]]

    if not qualifying:
        best = max(
            scored,
            key=lambda item: (
                item[1],
                -_rank_of(item[0]),
            ),
        )

        return best[0], best[1], best[2], False

    if assessment.level in {"high", "critical"}:
        best = min(
            qualifying,
            key=lambda item: (
                _rank_of(item[0]),
                -item[1],
            ),
        )

        return best[0], best[1], best[2], True

    known_prices = {
        id(item[0]): _price_index(item[0])
        for item in qualifying
    }

    if any(
        price is not None
        for price in known_prices.values()
    ):
        best = min(
            qualifying,
            key=lambda item: (
                known_prices[id(item[0])]
                if known_prices[id(item[0])] is not None
                else Decimal("999999"),
                _rank_of(item[0]),
            ),
        )

    else:
        # Sem preço publicado, a alternativa econômica é a de maior rank.
        best = max(
            qualifying,
            key=lambda item: (
                _rank_of(item[0]),
                -item[1],
            ),
        )

    return best[0], best[1], best[2], True


def _rank_of(row: AIModelCatalog) -> int:
    rank = getattr(row, "agent_preference_rank", None)

    return rank if rank is not None else 9999


def _cost_bands(
    rows: Iterable[AIModelCatalog],
) -> Decimal | None:
    """Fronteira econômico/moderado derivada do próprio catálogo.

    Usa a mediana de preço entre os modelos que o catálogo já classificou como
    `economic`. Nenhum valor de preço é fixado em código.
    """
    prices = sorted(
        price
        for row in rows
        if (getattr(row, "category", "") or "").lower() == "economic"
        and (price := _price_index(row)) is not None
        and price > 0
    )

    if not prices:
        return None

    return prices[len(prices) // 2]


def _cost_class(
    row: AIModelCatalog | None,
    price: Decimal | None,
    economic_median: Decimal | None,
) -> str:
    """Classe de custo relativa, sempre a partir do Model Catalog."""
    if row is None:
        return "unknown"

    if getattr(row, "is_free", False):
        return "free"

    category = (getattr(row, "category", "") or "").lower()

    if (
        category == "premium"
        or getattr(row, "requires_confirmation", False)
    ):
        return "premium"

    if category == "free":
        return "free"

    if category != "economic":
        return "unknown"

    if price is None:
        # Catálogo classificou como econômico mas não publicou preço:
        # respeitamos a categoria em vez de estimar valor.
        return "economic"

    if price == 0:
        return "free"

    if economic_median is None or price <= economic_median:
        return "economic"

    return "moderate"


def _select_model(
    rows: list[AIModelCatalog],
    assessment: ComplexityAssessment,
) -> tuple[AIModelCatalog | None, int | None, tuple[str, ...], bool]:
    """Melhor modelo do agente: o mais barato entre os tecnicamente suficientes.

    Custo nunca supera capacidade — um modelo que não atinge a cobertura
    mínima da complexidade não é considerado suficiente.
    """
    if not rows:
        return None, None, (), False

    allowed_categories = COMPLEXITY_MIN_CATEGORY[assessment.level]
    minimum = MIN_CAPABILITY_COVERAGE[assessment.level]

    scored: list[
        tuple[AIModelCatalog, int, tuple[str, ...], bool]
    ] = []

    for row in rows:
        capability_score, _matched, missing = _capability_data(
            assessment.required_capabilities,
            getattr(row, "capabilities", None) or [],
        )

        category_ok = (
            (getattr(row, "category", "") or "").lower()
            in allowed_categories
        )

        qualifies = category_ok and capability_score >= minimum

        scored.append(
            (row, capability_score, missing, qualifies)
        )

    qualifying = [item for item in scored if item[3]]

    if qualifying:
        # Entre suficientes: primeiro os que não exigem confirmação de custo
        # premium, depois o mais barato.
        best = min(
            qualifying,
            key=lambda item: (
                bool(getattr(item[0], "requires_confirmation", False)),
                _price_index(item[0])
                if _price_index(item[0]) is not None
                else Decimal("999999"),
                -item[1],
                str(item[0].id),
            ),
        )

        return best[0], best[1], best[2], True

    # Nenhum modelo suficiente: reportamos o de maior cobertura como incapaz,
    # em vez de fingir adequação.
    best = max(
        scored,
        key=lambda item: (item[1], str(item[0].id)),
    )

    return best[0], best[1], best[2], False


def _describe_models(
    rows: list[AIModelCatalog],
    assessment: ComplexityAssessment,
    selected: AIModelCatalog | None,
    economic_median: Decimal | None,
) -> tuple[dict[str, Any], ...]:
    """Descreve os modelos permitidos do agente para o seletor do PLAN.

    Preço, categoria, contexto e classe de custo saem do catálogo — o frontend
    não conhece preço nenhum.
    """
    minimum = MIN_CAPABILITY_COVERAGE[assessment.level]

    described = []

    for row in rows:
        capability_score, _matched, missing = _capability_data(
            assessment.required_capabilities,
            getattr(row, "capabilities", None) or [],
        )

        price = _price_index(row)
        cost_class = _cost_class(row, price, economic_median)

        described.append(
            {
                "catalog_id": getattr(row, "id", None),
                "model": getattr(row, "provider_model_id", None),
                "model_label": getattr(row, "display_name", None),
                "provider": getattr(row, "provider", None),
                "category": getattr(row, "category", None),
                "context_window": getattr(row, "context_window", None),
                "capability_score": capability_score,
                "capable": capability_score >= minimum,
                "missing_capabilities": list(missing),
                "cost_class": cost_class,
                "cost_label": COST_LABELS[cost_class],
                "price_index": (
                    str(price) if price is not None else None
                ),
                "requires_confirmation": bool(
                    getattr(row, "requires_confirmation", False)
                ),
                "preference_rank": _rank_of(row),
                "recommended": (
                    selected is not None
                    and getattr(row, "id", None)
                    == getattr(selected, "id", None)
                ),
            }
        )

    return tuple(described)


def _fit_score(
    agent: str,
    profile: WorkloadProfile,
    assessment: ComplexityAssessment,
) -> Decimal:
    weights = AGENT_WORKLOAD_WEIGHTS[agent]

    score = sum(
        (
            weight * Decimal(profile.score(dimension))
            for dimension, weight in weights.items()
        ),
        Decimal("0"),
    )

    return score + COMPLEXITY_BIAS[assessment.level].get(
        agent,
        Decimal("0"),
    )


def _fit_reason(
    profile: WorkloadProfile,
    assessment: ComplexityAssessment,
) -> str:
    dominant = [
        DIMENSION_REASONS[dimension]
        for dimension in profile.dominant
        if dimension in DIMENSION_REASONS
    ][:2]

    if dominant:
        return (
            f"Tarefa envolve {' e '.join(dominant)}. "
            f"Complexidade {assessment.level}."
        )

    return (
        "Plano sem sinais fortes de especialização. "
        f"Complexidade {assessment.level}."
    )


def _availability(
    agent: str,
    model_row: AIModelCatalog | None,
    has_inactive_only: bool,
    runtime: dict[str, Any] | None,
    quota_state: tuple[str, str | None],
) -> tuple[str, str | None]:
    quota, quota_reason = quota_state

    if quota == "exhausted":
        return "unavailable", quota_reason or "cota/crédito esgotado"

    if model_row is None and has_inactive_only:
        return "unavailable", "sem modelo ativo no catálogo"

    if runtime is None:
        return "unknown", "estado do agente não verificado"

    if not runtime.get("checked", False):
        return "unknown", (
            runtime.get("error") or "estado do agente não verificado"
        )

    health = runtime.get("health")

    if runtime.get("running"):
        if health in {"blocked", "degraded"}:
            return "unavailable", f"agente em estado {health}"
        return "available", "sessão do agente ativa"

    if health == "offline":
        return "unavailable", "sessão do agente offline"

    return "unknown", "sessão do agente em standby"


def _provider_for_agent(agent: str) -> str | None:
    for provider, mapped in PROVIDER_TO_AGENT.items():
        if mapped == agent:
            return provider

    return None


def _matches_quota_error(text: str | None) -> str | None:
    if not text:
        return None

    for pattern in QUOTA_ERROR_PATTERNS:
        if pattern.search(text):
            return text.strip()[:180]

    return None


def detect_quota_blocks(
    db: Session,
    *,
    lookback_hours: int = QUOTA_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> dict[str, str]:
    """Cota esgotada só a partir de erro real já registrado no WorkDev.

    Fontes: execuções `agent_runs` que falharam e chamadas `ai_call_logs`
    malsucedidas. Se nada disso existir, a cota fica "não verificada" — o
    WorkDev não estima saldo, tokens ou créditos.
    """
    reference = now or datetime.now(timezone.utc)
    since = reference - timedelta(hours=lookback_hours)

    blocked: dict[str, str] = {}

    try:
        runs = (
            db.query(AgentRun)
            .filter(
                AgentRun.status == "failed",
                AgentRun.updated_at >= since,
                AgentRun.error.isnot(None),
            )
            .order_by(AgentRun.updated_at.desc())
            .limit(50)
            .all()
        )
    except Exception:
        runs = []

    for run in runs:
        agent = getattr(run, "agent", None)

        if agent not in AGENT_LABELS or agent in blocked:
            continue

        match = _matches_quota_error(getattr(run, "error", None))

        if match:
            blocked[agent] = f"erro registrado na execução: {match}"

    provider_to_agents: dict[str, list[str]] = {}

    for agent in SUPPORTED_AGENTS:
        provider = _provider_for_agent(agent)

        if provider:
            provider_to_agents.setdefault(provider, []).append(agent)

    try:
        calls = (
            db.query(AICallLog)
            .filter(
                AICallLog.success.is_(False),
                AICallLog.created_at >= since,
                or_(
                    AICallLog.error_type.isnot(None),
                    AICallLog.fallback_reason.isnot(None),
                ),
            )
            .order_by(AICallLog.created_at.desc())
            .limit(50)
            .all()
        )
    except Exception:
        calls = []

    for call in calls:
        match = _matches_quota_error(
            getattr(call, "error_type", None)
        ) or _matches_quota_error(
            getattr(call, "fallback_reason", None)
        )

        if not match:
            continue

        for agent in provider_to_agents.get(
            getattr(call, "provider", ""),
            [],
        ):
            blocked.setdefault(
                agent,
                f"erro registrado no provedor: {match}",
            )

    return blocked


def allowed_models_for_agent(
    db: Session,
    agent: str,
) -> list[AIModelCatalog]:
    """Modelos ativos que o agente está configurado para rodar, por rank."""
    active, _inactive = _agent_models(_catalog_rows(db))

    return active.get(agent, [])


def recommend_agents(
    db: Session,
    task: Any,
    plan: Any,
    subtasks: Iterable[Any] | None = None,
    *,
    runtime: dict[str, dict[str, Any]] | None = None,
    quota_signals: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Recomendação consultiva: sugere, explica e nunca executa."""
    subtasks = list(subtasks or [])

    assessment = classify_task(task, plan, subtasks)
    profile = describe_workload(task, plan, subtasks)

    rows = _catalog_rows(db)
    active, inactive = _rows_by_agent(rows)
    allowed_active, allowed_inactive = _agent_models(rows)
    economic_median = _cost_bands(
        [row for group in active.values() for row in group]
    )

    quota_signals = quota_signals or {}
    fit_reason = _fit_reason(profile, assessment)

    options: list[AgentOption] = []

    for agent in SUPPORTED_AGENTS:
        agent_rows = active.get(agent, [])
        allowed = allowed_active.get(agent, [])
        agent_models: tuple[dict[str, Any], ...] = ()

        if allowed:
            model_row, capability_score, missing, capable = (
                _select_allowed_model(
                    allowed,
                    assessment,
                )
            )
            has_inactive_only = False

        elif allowed_inactive.get(agent):
            # Todos os modelos configurados do agente estão inativos. Não
            # caímos em outra linha do provider: mostrar um modelo que a CLI
            # não roda é exatamente o erro que este vínculo evita.
            model_row = None
            capability_score = None
            missing = ()
            capable = False
            has_inactive_only = True

        else:
            model_row, capability_score, missing, capable = _select_model(
                agent_rows,
                assessment,
            )

            has_inactive_only = (
                not agent_rows and bool(inactive.get(agent))
            )

        if model_row is None and not has_inactive_only:
            # Agente sem entrada no catálogo (ex.: CLI por assinatura).
            # Não afirmamos custo nem capacidade que não podemos verificar.
            capable = True
            capability_score = None

        quota_reason = quota_signals.get(agent)
        quota_state = (
            ("exhausted", quota_reason)
            if quota_reason
            else ("unknown", None)
        )

        availability, availability_reason = _availability(
            agent,
            model_row,
            has_inactive_only,
            (runtime or {}).get(agent),
            quota_state,
        )

        price = _price_index(model_row) if model_row is not None else None
        cost_class = _cost_class(model_row, price, economic_median)

        if allowed:
            agent_models = _describe_models(
                allowed,
                assessment,
                model_row,
                economic_median,
            )

        options.append(
            AgentOption(
                agent=agent,
                agent_label=AGENT_LABELS[agent],
                fit_score=_fit_score(agent, profile, assessment),
                capable=capable,
                capability_score=capability_score,
                missing_capabilities=missing,
                catalog_id=(
                    getattr(model_row, "id", None)
                    if model_row is not None
                    else None
                ),
                provider=(
                    getattr(model_row, "provider", None)
                    if model_row is not None
                    else _provider_for_agent(agent)
                ),
                model=(
                    getattr(model_row, "provider_model_id", None)
                    if model_row is not None
                    else None
                ),
                model_label=(
                    getattr(model_row, "display_name", None)
                    if model_row is not None
                    else None
                ),
                category=(
                    getattr(model_row, "category", None)
                    if model_row is not None
                    else None
                ),
                context_window=(
                    getattr(model_row, "context_window", None)
                    if model_row is not None
                    else None
                ),
                requires_confirmation=bool(
                    getattr(model_row, "requires_confirmation", False)
                ),
                cost_class=cost_class,
                price_index=price,
                availability=availability,
                availability_reason=availability_reason,
                quota=quota_state[0],
                quota_reason=quota_state[1],
                reason=fit_reason,
                models=agent_models,
            )
        )

    # Recomendação = mérito técnico (adequação ao trabalho e capacidade real),
    # com o custo desempatando entre opções equivalentes. Disponibilidade é
    # informada, não silencia a melhor opção técnica.
    ranked = sorted(
        options,
        key=lambda option: (
            1 if option.capable else 0,
            option.fit_score,
            -COST_RANK[option.cost_class],
            option.agent,
        ),
        reverse=True,
    )

    recommended = ranked[0]

    # Alternativa = melhor opção **disponível** entre as demais.
    alternatives = sorted(
        (
            option
            for option in ranked[1:]
        ),
        key=lambda option: (
            AVAILABILITY_RANK[option.availability],
            1 if option.capable else 0,
            option.fit_score,
            -COST_RANK[option.cost_class],
            option.agent,
        ),
        reverse=True,
    )

    alternative = alternatives[0] if alternatives else None

    return {
        "complexity": assessment.level,
        "complexity_score": assessment.score,
        "complexity_reason": assessment.reason,
        "required_capabilities": list(
            assessment.required_capabilities
        ),
        "workload": profile.as_dict(),
        "recommended": recommended.as_dict(),
        "alternative": (
            {
                **alternative.as_dict(),
                "reason": _alternative_reason(
                    recommended,
                    alternative,
                ),
            }
            if alternative
            else None
        ),
        "options": [option.as_dict() for option in options],
        "runtime_checked": bool(runtime),
        "pricing_source": "ai_model_catalog",
    }


def _alternative_reason(
    recommended: AgentOption,
    alternative: AgentOption,
) -> str:
    """Texto curto: por que essa alternativa e como o custo se compara."""
    parts = [f"melhor para {AGENT_STRENGTHS[alternative.agent]}"]

    if (
        alternative.availability == "available"
        and recommended.availability != "available"
    ):
        parts.append("disponível agora")

    if alternative.cost_class == "unknown":
        parts.append("custo não informado no catálogo")
    else:
        delta = (
            COST_RANK[alternative.cost_class]
            - COST_RANK[recommended.cost_class]
        )
        label = COST_LABELS[alternative.cost_class]

        if delta > 0:
            parts.append(f"porém com custo maior ({label})")
        elif delta < 0:
            parts.append(f"e com custo menor ({label})")
        else:
            parts.append(f"custo {label}")

    if not alternative.capable:
        parts.append(
            "capacidade abaixo do exigido para esta complexidade"
        )

    return ", ".join(parts) + "."
