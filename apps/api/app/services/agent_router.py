from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.ai_routing import AIModelCatalog
from app.services.task_complexity import ComplexityAssessment


PROVIDER_TO_AGENT = {
    "openai": "codex",
    "anthropic": "claude",
    "openrouter": None,
    "gemini": "gemini",
}


MODEL_AGENT_OVERRIDES = {
    "qwen/qwen3-coder": "qwen",
    "moonshotai/kimi-k2.7-code": "kimi",
    "moonshotai/kimi-k3": "kimi",
 }


COMPLEXITY_MIN_CATEGORY = {
    "low": {"free", "economic", "premium"},
    "medium": {"free", "economic", "premium"},
    "high": {"economic", "premium"},
    "critical": {"economic", "premium"},
}


MIN_CAPABILITY_COVERAGE = {
    "low": 100,
    "medium": 50,
    "high": 60,
    "critical": 75,
}


COMPLEXITY_WEIGHTS = {
    "low": {
        "capability": Decimal("3"),
        "cost": Decimal("7"),
    },
    "medium": {
        "capability": Decimal("5"),
        "cost": Decimal("5"),
    },
    "high": {
        "capability": Decimal("7"),
        "cost": Decimal("3"),
    },
    "critical": {
        "capability": Decimal("9"),
        "cost": Decimal("1"),
    },
}


DEFAULT_EFFORT_BY_COMPLEXITY = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "high",
}


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    provider: str
    model: str
    catalog_id: str
    reasoning_effort: str | None
    complexity: str
    complexity_score: int
    capability_score: int
    matched_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    category: str
    estimated_price_index: Decimal | None
    requires_confirmation: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "provider": self.provider,
            "model": self.model,
            "catalog_id": self.catalog_id,
            "reasoning_effort": self.reasoning_effort,
            "complexity": self.complexity,
            "complexity_score": self.complexity_score,
            "capability_score": self.capability_score,
            "matched_capabilities": list(
                self.matched_capabilities
            ),
            "missing_capabilities": list(
                self.missing_capabilities
            ),
            "category": self.category,
            "estimated_price_index": (
                str(self.estimated_price_index)
                if self.estimated_price_index is not None
                else None
            ),
            "requires_confirmation": (
                self.requires_confirmation
            ),
            "reason": self.reason,
        }


class AgentRoutingError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _agent_for_model(
    row: AIModelCatalog,
) -> str | None:
    override = MODEL_AGENT_OVERRIDES.get(
        row.provider_model_id
    )

    if override:
        return override

    return PROVIDER_TO_AGENT.get(
        row.provider
    )


def _price_index(
    row: AIModelCatalog,
) -> Decimal | None:
    if (
        row.input_cost_per_million is None
        or row.output_cost_per_million is None
    ):
        return None

    input_cost = Decimal(
        str(row.input_cost_per_million)
    )

    output_cost = Decimal(
        str(row.output_cost_per_million)
    )

    return input_cost + output_cost


def _capability_data(
    required: Iterable[str],
    available: Iterable[str],
) -> tuple[
    int,
    tuple[str, ...],
    tuple[str, ...],
]:
    required_set = set(required)
    available_set = set(available)

    if not required_set:
        return 100, (), ()

    matched = (
        required_set
        & available_set
    )

    missing = (
        required_set
        - available_set
    )

    score = round(
        100
        * len(matched)
        / len(required_set)
    )

    return (
        score,
        tuple(sorted(matched)),
        tuple(sorted(missing)),
    )


def _normalized_cost_score(
    price: Decimal | None,
    prices: list[Decimal],
) -> Decimal:
    if price is None:
        return Decimal("0")

    if not prices:
        return Decimal("50")

    minimum = min(prices)
    maximum = max(prices)

    if maximum == minimum:
        return Decimal("100")

    relative = (
        (price - minimum)
        / (maximum - minimum)
    )

    return (
        Decimal("100")
        - relative * Decimal("100")
    )


def _reasoning_effort(
    row: AIModelCatalog,
    complexity: str,
) -> str | None:
    allowed = list(
        row.allowed_reasoning_efforts
        or []
    )

    if not allowed:
        return None

    preferred = (
        DEFAULT_EFFORT_BY_COMPLEXITY.get(
            complexity
        )
    )

    if preferred in allowed:
        return preferred

    effort_order = [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]

    allowed_ordered = [
        effort
        for effort in effort_order
        if effort in allowed
    ]

    if not allowed_ordered:
        return None

    if complexity in {
        "high",
        "critical",
    }:
        return allowed_ordered[-1]

    return allowed_ordered[0]


def _all_eligible_rows(
    db: Session,
    assessment: ComplexityAssessment,
) -> list[AIModelCatalog]:
    allowed_categories = (
        COMPLEXITY_MIN_CATEGORY[
            assessment.level
        ]
    )

    rows = (
        db.query(AIModelCatalog)
        .filter(
            AIModelCatalog.active.is_(True)
        )
        .all()
    )

    result: list[AIModelCatalog] = []

    for row in rows:
        if (
            row.category
            not in allowed_categories
        ):
            continue

        if not _agent_for_model(row):
            continue

        result.append(row)

    return result


def _qualified_rows(
    rows: Iterable[AIModelCatalog],
    assessment: ComplexityAssessment,
) -> list[
    tuple[
        AIModelCatalog,
        int,
        tuple[str, ...],
        tuple[str, ...],
    ]
]:
    minimum = MIN_CAPABILITY_COVERAGE[
        assessment.level
    ]

    qualified = []

    for row in rows:
        capability_score, matched, missing = (
            _capability_data(
                assessment.required_capabilities,
                row.capabilities or [],
            )
        )

        if capability_score < minimum:
            continue

        qualified.append(
            (
                row,
                capability_score,
                matched,
                missing,
            )
        )

    return qualified


def route_agent(
    db: Session,
    assessment: ComplexityAssessment,
    *,
    allow_premium: bool = False,
) -> RoutingDecision:
    all_rows = _all_eligible_rows(
        db,
        assessment,
    )

    if not all_rows:
        raise AgentRoutingError(
            "no_models_available",
            "Nenhum modelo ativo possui agente associado",
        )

    qualified = _qualified_rows(
        all_rows,
        assessment,
    )

    nonpremium = [
        item
        for item in qualified
        if not item[0].requires_confirmation
    ]

    premium = [
        item
        for item in qualified
        if item[0].requires_confirmation
    ]

    if allow_premium:
        candidates = qualified

    else:
        candidates = nonpremium

    if not candidates:
        if premium:
            premium = sorted(
                premium,
                key=lambda item: (
                    -item[1],
                    _price_index(item[0]) is None,
                    _price_index(item[0]) or Decimal("0"),
                ),
            )
            premium_options = [
                {
                    "catalog_id": row.id,
                    "model": row.provider_model_id,
                    "provider": row.provider,
                    "agent": _agent_for_model(row),
                    "capability_score": capability_score,
                    "category": row.category,
                }
                for (
                    row,
                    capability_score,
                    _matched,
                    _missing,
                ) in premium
            ]

            raise AgentRoutingError(
                "premium_confirmation_required",
                (
                    f"A tarefa {assessment.level} "
                    "não possui modelo não-premium "
                    "com capacidade mínima suficiente. "
                    "É necessária autorização para "
                    "um modelo premium."
                ),
                {
                    "complexity": assessment.level,
                    "complexity_score": (
                        assessment.score
                    ),
                    "minimum_capability_score": (
                        MIN_CAPABILITY_COVERAGE[
                            assessment.level
                        ]
                    ),
                    "premium_options": (
                        premium_options
                    ),
                    "recommended": premium_options[0],
                },
            )

        coverage = []

        for row in all_rows:
            (
                capability_score,
                matched,
                missing,
            ) = _capability_data(
                assessment.required_capabilities,
                row.capabilities or [],
            )

            coverage.append(
                {
                    "catalog_id": row.id,
                    "model": row.provider_model_id,
                    "capability_score": capability_score,
                    "matched": list(matched),
                    "missing": list(missing),
                }
            )

        raise AgentRoutingError(
            "insufficient_model_capability",
            (
                f"Nenhum modelo ativo atinge "
                f"{MIN_CAPABILITY_COVERAGE[assessment.level]}% "
                f"das capacidades exigidas para uma tarefa "
                f"{assessment.level}."
            ),
            {
                "required_capabilities": list(
                    assessment.required_capabilities
                ),
                "models": coverage,
            },
        )

    known_prices = [
        price
        for price in (
            _price_index(row)
            for (
                row,
                _score,
                _matched,
                _missing,
            ) in candidates
        )
        if price is not None
    ]

    weights = (
        COMPLEXITY_WEIGHTS[
            assessment.level
        ]
    )

    ranked = []

    for (
        row,
        capability_score,
        matched,
        missing,
    ) in candidates:
        price = _price_index(row)

        cost_score = (
            _normalized_cost_score(
                price,
                known_prices,
            )
        )

        weighted_score = (
            Decimal(capability_score)
            * weights["capability"]
            + cost_score
            * weights["cost"]
        )

        if row.is_free:
            weighted_score += Decimal("5")

        if (
            assessment.level == "critical"
            and capability_score == 100
        ):
            weighted_score += Decimal("25")

        elif (
            assessment.level == "high"
            and capability_score == 100
        ):
            weighted_score += Decimal("10")

        ranked.append(
            (
                weighted_score,
                capability_score,
                price,
                row,
                matched,
                missing,
            )
        )

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
            -(
                item[2]
                if item[2] is not None
                else Decimal("999999")
            ),
        ),
        reverse=True,
    )

    (
        weighted_score,
        capability_score,
        price,
        selected,
        matched,
        missing,
    ) = ranked[0]

    agent = _agent_for_model(
        selected
    )

    if not agent:
        raise AgentRoutingError(
            "agent_not_mapped",
            "Modelo selecionado não possui agente associado",
        )

    effort = _reasoning_effort(
        selected,
        assessment.level,
    )

    matched_text = (
        ", ".join(matched)
        if matched
        else "nenhuma"
    )

    missing_text = (
        ", ".join(missing)
        if missing
        else "nenhuma"
    )

    reason = (
        f"Tarefa {assessment.level} "
        f"({assessment.score}/100). "
        f"Modelo {selected.display_name} selecionado "
        f"com cobertura de capacidades de "
        f"{capability_score}%. "
        f"Atende: {matched_text}. "
        f"Não cobre explicitamente: {missing_text}. "
        f"Categoria: {selected.category}. "
        f"Score de roteamento: "
        f"{weighted_score.quantize(Decimal('0.01'))}."
    )

    return RoutingDecision(
        agent=agent,
        provider=selected.provider,
        model=selected.provider_model_id,
        catalog_id=selected.id,
        reasoning_effort=effort,
        complexity=assessment.level,
        complexity_score=assessment.score,
        capability_score=capability_score,
        matched_capabilities=matched,
        missing_capabilities=missing,
        category=selected.category,
        estimated_price_index=price,
        requires_confirmation=(
            selected.requires_confirmation
        ),
        reason=reason,
    )
