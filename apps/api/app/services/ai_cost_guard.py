from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_routing import AIModelCatalog, AIBudget, AICallLog


MILLION = Decimal("1000000")
ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
PREMIUM_MARKERS = (
    "claude-opus", "claude-sonnet", "kimi-k3", "gpt-5.6-terra",
    "gpt-5.6-sol",
)


@dataclass(frozen=True)
class ModelPolicy:
    provider: str
    model: str
    category: str
    input_cost: Decimal | None
    output_cost: Decimal | None
    is_free: bool = False
    requires_confirmation: bool = False
    allowed_efforts: tuple[str, ...] = ()


# Fundação central da política. Na Etapa 2 estes registros serão administrados
# pelo catálogo persistido; por ora não há IDs ou preços espalhados no frontend.
MODEL_POLICIES: dict[tuple[str, str], ModelPolicy] = {
    ("openai", "gpt-5.6-luna"): ModelPolicy(
        "openai", "gpt-5.6-luna", "economic", None, None,
        allowed_efforts=("low", "medium"),
    ),
    ("openai", "gpt-5.6-terra"): ModelPolicy(
        "openai", "gpt-5.6-terra", "premium", None, None,
        requires_confirmation=True, allowed_efforts=("medium", "high"),
    ),
    ("openai", "gpt-5.6-sol"): ModelPolicy(
        "openai", "gpt-5.6-sol", "premium", None, None,
        requires_confirmation=True, allowed_efforts=("high", "max"),
    ),
    ("openai", "gpt-4o-mini"): ModelPolicy(
        "openai", "gpt-4o-mini", "economic", Decimal("0.15"), Decimal("0.60")
    ),
    ("openrouter", "qwen/qwen3-coder"): ModelPolicy(
        "openrouter", "qwen/qwen3-coder", "economic",
        Decimal("0.30"), Decimal("1.00"),
    ),
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"): ModelPolicy(
        "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", "free",
        Decimal("0"), Decimal("0"), is_free=True,
    ),
    ("openrouter", "moonshotai/kimi-k2.7-code"): ModelPolicy(
        "openrouter", "moonshotai/kimi-k2.7-code", "economic",
        Decimal("0.71"), Decimal("3.50"),
    ),
    ("openrouter", "moonshotai/kimi-k3"): ModelPolicy(
        "openrouter", "moonshotai/kimi-k3", "premium",
        Decimal("3.00"), Decimal("15.00"), requires_confirmation=True,
    ),
    ("anthropic", "claude-sonnet-5"): ModelPolicy(
        "anthropic", "claude-sonnet-5", "premium",
        Decimal("2.00"), Decimal("10.00"), requires_confirmation=True,
    ),
    ("anthropic", "claude-opus-5"): ModelPolicy(
        "anthropic", "claude-opus-5", "premium", None, None,
        requires_confirmation=True,
    ),
}


class CostGuardError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def policy_for(provider: str, model: str, db: Session | None = None) -> ModelPolicy:
    if db is not None:
        row = db.query(AIModelCatalog).filter(
            AIModelCatalog.provider == provider,
            AIModelCatalog.provider_model_id == model,
        ).first()
        if row is not None:
            if not row.active:
                raise CostGuardError(
                    "model_disabled", f"O modelo {model} foi desativado administrativamente"
                )
            return ModelPolicy(
                provider=row.provider, model=row.provider_model_id,
                category=row.category,
                input_cost=(Decimal(str(row.input_cost_per_million))
                            if row.input_cost_per_million is not None else None),
                output_cost=(Decimal(str(row.output_cost_per_million))
                             if row.output_cost_per_million is not None else None),
                is_free=row.is_free,
                requires_confirmation=row.requires_confirmation,
                allowed_efforts=tuple(row.allowed_reasoning_efforts or ()),
            )
    policy = MODEL_POLICIES.get((provider, model))
    if policy:
        return policy
    lowered = model.lower()
    premium = any(marker in lowered for marker in PREMIUM_MARKERS)
    # Preço desconhecido nunca é convertido em zero. Modelos premium conhecidos
    # por família continuam bloqueados mesmo antes de entrarem no catálogo.
    return ModelPolicy(
        provider, model, "premium" if premium else "unclassified",
        None, None, requires_confirmation=premium,
    )


def estimate_tokens(messages: list[dict], system: str = "") -> int:
    characters = len(system) + sum(len(str(item.get("content", ""))) for item in messages)
    return max(1, (characters + 3) // 4)


def estimate_cost(policy: ModelPolicy, input_tokens: int,
                  output_tokens: int) -> Decimal | None:
    if policy.input_cost is None or policy.output_cost is None:
        return None
    return (
        Decimal(input_tokens) * policy.input_cost
        + Decimal(output_tokens) * policy.output_cost
    ) / MILLION


def normalize_effort(policy: ModelPolicy, requested: str | None) -> str | None:
    if requested is None:
        return policy.allowed_efforts[0] if policy.allowed_efforts else None
    requested = requested.lower()
    if requested not in ALLOWED_EFFORTS:
        raise CostGuardError("invalid_reasoning_effort", "Nível de raciocínio inválido")
    if policy.allowed_efforts and requested not in policy.allowed_efforts:
        raise CostGuardError(
            "reasoning_effort_not_allowed",
            f"O modelo {policy.model} não permite reasoning.effort={requested}",
        )
    if requested == "max":
        raise CostGuardError(
            "max_effort_confirmation_required",
            "reasoning.effort=max exige uma autorização separada",
        )
    return requested


def output_limit(requested: int | None) -> int:
    # 16000, não 4096: com modelos que pensam, max_tokens limita thinking +
    # texto juntos, e 4096 truncava a resposta no meio. É teto, não alvo — o
    # custo real continua sendo só o que o modelo gerar de fato.
    configured = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "16000"))
    if configured < 1:
        configured = 16000
    if requested is None:
        return configured
    if requested < 1 or requested > configured:
        raise CostGuardError(
            "output_token_limit",
            f"max_output_tokens deve estar entre 1 e {configured}",
        )
    return requested


def input_limit(input_tokens: int) -> None:
    configured = int(os.getenv("AI_MAX_INPUT_TOKENS", "120000"))
    if input_tokens > configured:
        raise CostGuardError(
            "input_token_limit",
            f"Contexto estimado em {input_tokens} tokens excede o limite {configured}",
        )


def correlation_id(value: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(value) if value else uuid.uuid4()
    except (ValueError, TypeError, AttributeError) as exc:
        raise CostGuardError("invalid_correlation_id", "correlation_id inválido") from exc


def reject_duplicate(db: Session, value: uuid.UUID) -> None:
    if db.query(AICallLog.id).filter(AICallLog.correlation_id == value).first():
        raise CostGuardError(
            "duplicate_call", "Esta chamada já foi processada; repetição automática bloqueada"
        )


def _period_start(period: str, now: datetime) -> datetime:
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def enforce_budgets(db: Session, *, provider: str, project_id,
                    estimated_cost: Decimal | None) -> list[dict]:
    if estimated_cost is None:
        return []
    budgets = db.query(AIBudget).filter(AIBudget.active.is_(True)).all()
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []
    for budget in budgets:
        applies = (
            budget.scope_type == "global"
            or (budget.scope_type == "provider" and budget.scope_key == provider)
            or (budget.scope_type == "project" and project_id is not None
                and budget.scope_key == str(project_id))
        )
        if not applies or budget.period not in {"daily", "monthly"}:
            continue
        charged = func.coalesce(AICallLog.actual_cost_usd,
                                AICallLog.estimated_cost_usd, 0)
        query = db.query(func.coalesce(func.sum(charged), 0)).filter(
            AICallLog.success.is_(True),
            AICallLog.created_at >= _period_start(budget.period, now),
        )
        if budget.scope_type == "provider":
            query = query.filter(AICallLog.provider == provider)
        elif budget.scope_type == "project":
            query = query.filter(AICallLog.project_id == project_id)
        spent = Decimal(str(query.scalar() or 0))
        projected = spent + estimated_cost
        limit = Decimal(str(budget.limit_usd))
        ratio = projected / limit if limit else Decimal("1")
        if ratio >= 1:
            raise CostGuardError(
                "budget_exceeded", "Orçamento de IA atingido; chamada paga bloqueada",
                {"scope": budget.scope_type, "period": budget.period},
            )
        threshold = next((n for n in (90, 75, 50) if ratio >= Decimal(n) / 100), None)
        if threshold:
            alerts.append({"scope": budget.scope_type, "period": budget.period,
                           "threshold": threshold})
    return alerts


def require_premium_confirmation(policy: ModelPolicy, confirmed: bool,
                                 estimated_cost: Decimal | None) -> None:
    if not policy.requires_confirmation:
        return
    if estimated_cost is None:
        raise CostGuardError(
            "premium_price_unknown",
            "Modelo premium sem preço vigente: chamada bloqueada até configurar o custo",
            {"model": policy.model},
        )
    if not confirmed:
        raise CostGuardError(
            "premium_confirmation_required",
            "Confirmação explícita de custo obrigatória antes da chamada premium",
            {"model": policy.model, "estimated_cost_usd": str(estimated_cost)},
        )


def enforce_per_call_limit(estimated_cost: Decimal | None) -> None:
    configured = os.getenv("AI_MAX_COST_PER_CALL_USD")
    if not configured or estimated_cost is None:
        return
    if estimated_cost > Decimal(configured):
        raise CostGuardError(
            "per_call_budget_exceeded", "Estimativa excede o limite máximo por chamada",
            {"estimated_cost_usd": str(estimated_cost), "limit_usd": configured},
        )
