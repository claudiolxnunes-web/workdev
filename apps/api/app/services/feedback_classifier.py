"""Classificação determinística de feedback técnico de AgentRun.

Não usa LLM e não toma decisões de aprovação.
O veredito continua pertencendo ao revisor independente + gates objetivos.

A classificação serve para:
- pesquisa/RAG;
- métricas por tipo de erro;
- seleção posterior de exemplos de treino;
- comparação entre agentes/modelos.

Fail-safe: texto desconhecido vira ``other``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FeedbackClassification:
    category: str
    confidence: str
    reason: str


_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "schema_contradiction",
        (
            r"\bschema\b",
            r"\bcoluna\b",
            r"\btabela\b",
            r"\bmigration\b",
            r"\bmigra[cç][aã]o\b",
            r"\bcolumn\b",
            r"\btable\b",
            r"\balembic\b",
        ),
    ),
    (
        "missing_evidence",
        (
            r"\bevid[eê]ncia\b",
            r"\bn[aã]o foi fornecid",
            r"\bn[aã]o fornecid",
            r"\bsem prova\b",
            r"\bsem diff\b",
            r"\bsem log\b",
            r"\bsem teste\b",
            r"\bmissing evidence\b",
            r"\bnot provided\b",
        ),
    ),
    (
        "false_done",
        (
            r"\bmarcou .*done\b",
            r"\bmarcado .*done\b",
            r"\bcompleted sem\b",
            r"\bconclu[ií]d[oa] sem\b",
            r"\bafirmou .*conclu",
            r"\bfalso positivo\b",
            r"\bfalse done\b",
            r"\bclaimed .*completed\b",
        ),
    ),
    (
        "runtime_state_confusion",
        (
            r"\bruntime\b",
            r"\bprocesso\b",
            r"\btmux\b",
            r"\bstatus persist",
            r"\bestado persist",
            r"\bservi[cç]o ativo\b",
            r"\bollama ps\b",
            r"\bsystemd\b",
        ),
    ),
    (
        "scope_expansion",
        (
            r"\bfora do escopo\b",
            r"\bampliou? .*escopo\b",
            r"\bscope expansion\b",
            r"\bfora da task\b",
            r"\bn[aã]o solicitado\b",
        ),
    ),
    (
        "unsupported_assumption",
        (
            r"\bassum",
            r"\bsuposi[cç][aã]o\b",
            r"\binvent",
            r"\balucin",
            r"\bsem contexto\b",
            r"\bunsupported assumption\b",
            r"\bhallucin",
        ),
    ),
    (
        "test_failure",
        (
            r"\bpytest\b",
            r"\bteste[s]? falh",
            r"\btest[s]? fail",
            r"\bbuild falh",
            r"\blint falh",
            r"\bgate .*reprov",
            r"\bgate .*fail",
        ),
    ),
)


def classify_review_feedback(
    *,
    verdict: str,
    feedback: str | None,
    gate_passed: bool | None,
) -> FeedbackClassification:
    """Classifica uma revisão sem alterar seu veredito."""

    if verdict == "approved" and gate_passed is True:
        return FeedbackClassification(
            category="validated",
            confidence="high",
            reason="Revisão aprovada com gate objetivo aprovado",
        )

    texto = (feedback or "").strip().lower()

    if not texto:
        return FeedbackClassification(
            category="other",
            confidence="low",
            reason="Feedback textual ausente",
        )

    matches: list[tuple[str, int]] = []

    for category, patterns in _PATTERNS:
        score = sum(
            1 for pattern in patterns
            if re.search(pattern, texto, flags=re.IGNORECASE)
        )
        if score:
            matches.append((category, score))

    if not matches:
        return FeedbackClassification(
            category="other",
            confidence="low",
            reason="Nenhum padrão conhecido encontrado",
        )

    # Algumas categorias são semanticamente mais específicas que outras.
    # Exemplo: "assumiu endpoint que não foi fornecido" contém ausência de
    # evidência, mas o defeito principal é a suposição não suportada.
    priority = {
        "false_done": 70,
        "unsupported_assumption": 60,
        "runtime_state_confusion": 50,
        "scope_expansion": 40,
        "test_failure": 35,
        "missing_evidence": 30,
        "schema_contradiction": 20,
        "other": 0,
    }

    # Falta explícita de evidência deve vencer menções incidentais a schema,
    # migration, tabela etc.
    explicit_missing = bool(
        re.search(
            r"(n[aã]o foi fornecid|n[aã]o fornecid|sem evid[eê]ncia|"
            r"nenhum .*evid[eê]ncia|sem diff|sem log|sem teste)",
            texto,
            flags=re.IGNORECASE,
        )
    )

    ranked: list[tuple[str, int, int]] = []

    for category, score in matches:
        semantic_priority = priority.get(category, 0)

        if explicit_missing and category == "missing_evidence":
            semantic_priority += 50

        # Se houve suposição/invenção explícita, esse é o defeito principal,
        # mesmo que o texto também diga que a evidência não foi fornecida.
        if category == "unsupported_assumption":
            semantic_priority += 50

        ranked.append((category, score, semantic_priority))

    ranked.sort(
        key=lambda item: (item[2], item[1]),
        reverse=True,
    )

    category, score, _priority = ranked[0]

    confidence = "high" if score >= 2 else "medium"

    return FeedbackClassification(
        category=category,
        confidence=confidence,
        reason=f"{score} padrão(ões) compatível(is) com {category}",
    )
