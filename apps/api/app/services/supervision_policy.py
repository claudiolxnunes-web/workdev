"""Política determinística; opinião de modelo pode acrescentar exigência, nunca dispensar gate."""
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Complexity(StrEnum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'
    CRITICAL = 'CRITICAL'


class JevDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    complexity: Complexity
    complexity_confidence: float = Field(ge=0, le=1)
    supervision: Literal['NONE', 'OBSERVER', 'REVIEWER', 'OBSERVER_AND_REVIEWER']
    supervision_confidence: float = Field(ge=0, le=1)
    decompose_score: float = Field(ge=0, le=1)
    human_approval: Literal['YES', 'NO']
    human_approval_confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, dict[str, float]]


class SupervisionPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    complexity: Complexity
    observer_required: bool
    review_required: bool
    human_approval_required: bool
    human_approval_recommended: bool
    decompose_recommended: bool
    conservative_fallback: bool
    reason: str


class ObserverFinding(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['ok', 'alert']
    severity: Literal['none', 'low', 'medium', 'high', 'critical']
    category: Literal['scope_violation', 'unsupported_success_claim', 'test_failure',
                      'gate_failure', 'unexpected_architecture_change', 'missing_evidence',
                      'persistent_action_risk', 'security_risk', 'execution_anomaly'] | None = None
    scope: Literal['within', 'outside', 'unknown'] = 'unknown'
    evidence_quality: Literal['good', 'missing', 'uncertain'] = 'uncertain'
    finding: str | None = Field(default=None, max_length=1000)
    evidence: str | None = Field(default=None, max_length=1000)
    escalate: bool

    @model_validator(mode='after')
    def consistent(self):
        if self.status == 'ok' and (self.severity != 'none' or self.category or self.escalate
                                   or self.scope != 'within' or self.evidence_quality != 'good'):
            raise ValueError('Achado OK inconsistente')
        if self.status == 'alert' and (not self.category or not self.finding or not self.escalate):
            raise ValueError('Alerta precisa escalar com categoria de evidência')
        return self


def decide_supervision(decision: JevDecision | None, deterministic_complexity: str,
                       *, threshold=.75, human_approval_threshold=.75,
                       mandatory_review=False, mandatory_human=False):
    levels = list(Complexity)
    try:
        floor = Complexity(deterministic_complexity.upper())
    except (ValueError, AttributeError):
        floor = Complexity.HIGH
    # Roteamento (complexidade/supervisão) e aprovação humana têm riscos
    # diferentes — cada eixo tem seu próprio piso de confiança.
    routing_confident = bool(decision and min(decision.complexity_confidence,
        decision.supervision_confidence) >= threshold)
    approval_confident = bool(decision and decision.human_approval_confidence >= human_approval_threshold)
    # Modelo indisponível/incerto nunca produz dispensa de supervisão.
    chosen = max((floor, decision.complexity), key=levels.index) if routing_confident else max((floor, Complexity.HIGH), key=levels.index)
    review = mandatory_review or chosen in (Complexity.HIGH, Complexity.CRITICAL)
    observe = chosen != Complexity.LOW
    if routing_confident:
        review |= decision.supervision in ('REVIEWER', 'OBSERVER_AND_REVIEWER')
        observe |= decision.supervision in ('OBSERVER', 'OBSERVER_AND_REVIEWER')
    return SupervisionPolicy(complexity=chosen, observer_required=observe,
        review_required=review, human_approval_required=mandatory_human,
        human_approval_recommended=bool(approval_confident and decision.human_approval == 'YES'),
        decompose_recommended=bool(decision and decision.decompose_score >= .5),
        conservative_fallback=not routing_confident,
        reason='Jev confiante, limitado pela política determinística' if routing_confident
               else 'Jev incerto no roteamento: piso conservador HIGH')
