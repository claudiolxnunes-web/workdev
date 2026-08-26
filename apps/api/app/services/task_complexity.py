from dataclasses import dataclass
from typing import Any, Iterable


COMPLEXITY_LEVELS = (
    "low",
    "medium",
    "high",
    "critical",
)


CRITICAL_MARKERS = {
    "produção",
    "production",
    "deploy",
    "deployment",
    "migração",
    "migration",
    "banco de dados",
    "database",
    "schema",
    "segurança",
    "security",
    "autenticação",
    "authentication",
    "authorization",
    "permissão",
    "permissions",
    "rls",
    "row level security",
    "secret",
    "secrets",
    "token",
    "credential",
    "credentials",
    "sudo",
    "sudoers",
    "systemd",
    "infraestrutura",
    "infrastructure",
    "rollback",
    "pagamento",
    "payment",
    "billing",
    "criptografia",
    "encryption",
}


HIGH_MARKERS = {
    "arquitetura",
    "architecture",
    "refactor",
    "refatoração",
    "integração",
    "integration",
    "api",
    "webhook",
    "concorrência",
    "concurrency",
    "async",
    "assíncrono",
    "fila",
    "queue",
    "cache",
    "docker",
    "traefik",
    "postgres",
    "supabase",
    "redis",
    "multi módulo",
    "multi-module",
    "cross module",
    "cross-module",
    "breaking change",
    "compatibilidade",
    "compatibility",
    "performance",
    "observabilidade",
    "monitoring",
}


MEDIUM_MARKERS = {
    "bug",
    "correção",
    "fix",
    "feature",
    "endpoint",
    "crud",
    "frontend",
    "backend",
    "componente",
    "component",
    "formulário",
    "form",
    "validação",
    "validation",
    "teste",
    "tests",
    "test",
    "consulta",
    "query",
    "relatório",
    "report",
    "importação",
    "import",
    "exportação",
    "export",
}


LOW_MARKERS = {
    "texto",
    "copy",
    "label",
    "rótulo",
    "typo",
    "ortografia",
    "documentação",
    "documentation",
    "docs",
    "renomear",
    "rename",
    "cor",
    "color",
    "ícone",
    "icon",
    "mensagem",
    "message",
}


CODE_MARKERS = {
    "código",
    "code",
    "python",
    "typescript",
    "javascript",
    "react",
    "fastapi",
    "sql",
    "endpoint",
    "api",
    "frontend",
    "backend",
    "bug",
    "feature",
    "refactor",
    "migration",
    "migração",
    "botão",
    "button",
    "label",
    "interface",
    "ui",
    "componente",
    "component",
    "formulário",
    "form",    
    "schema",
}


ARCHITECTURE_MARKERS = {
    "arquitetura",
    "architecture",
    "infraestrutura",
    "infrastructure",
    "microservice",
    "microsserviço",
    "service boundary",
    "boundary",
    "adr",
    "rfc",
    "systemd",
    "docker",
    "traefik",
}


REPOSITORY_ANALYSIS_MARKERS = {
    "refactor",
    "refatoração",
    "repositório",
    "repository",
    "codebase",
    "multi módulo",
    "multi-module",
    "cross module",
    "cross-module",
    "dependência",
    "dependency",
    "dependencies",
}


REVIEW_MARKERS = {
    "review",
    "revisão",
    "audit",
    "auditoria",
    "segurança",
    "security",
    "migration",
    "migração",
    "deploy",
    "production",
    "produção",
    "rollback",
}


@dataclass(frozen=True)
class ComplexityAssessment:
    level: str
    score: int
    required_capabilities: tuple[str, ...]
    reason: str
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "complexity": self.level,
            "complexity_score": self.score,
            "required_capabilities": list(
                self.required_capabilities
            ),
            "reason": self.reason,
            "signals": list(self.signals),
        }


def _value(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(
        obj,
        name,
        default,
    )


def _list_value(
    obj: Any,
    name: str,
) -> list[Any]:
    value = _value(
        obj,
        name,
        [],
    )

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return [value]


def _text_value(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return " ".join(
            _text_value(item)
            for item in value
        )

    if isinstance(value, dict):
        return " ".join(
            _text_value(item)
            for item in value.values()
        )

    return str(value)


def _combined_text(
    task: Any,
    plan: Any,
    subtasks: Iterable[Any],
) -> str:
    parts = [
        _value(task, "title"),
        _value(task, "description"),
        _value(task, "type"),
        _value(task, "priority"),
        _value(plan, "title"),
        _value(plan, "objective"),
        _value(plan, "scope"),
        _value(plan, "implementation_notes"),
        _list_value(
            plan,
            "constraints",
        ),
        _list_value(
            plan,
            "acceptance_criteria",
        ),
        _list_value(
            plan,
            "validation_steps",
        ),
    ]

    for subtask in subtasks:
        parts.extend(
            [
                _value(
                    subtask,
                    "title",
                ),
                _value(
                    subtask,
                    "description",
                ),
            ]
        )

    return " ".join(
        _text_value(part)
        for part in parts
        if part is not None
    ).lower()


def _matches(
    text: str,
    markers: set[str],
) -> list[str]:
    return sorted(
        marker
        for marker in markers
        if marker in text
    )

def _level_for_score(
    score: int,
) -> str:
    if score >= 55:
        return "high"

    if score >= 30:
        return "medium"

    return "low"

def _required_capabilities(
    text: str,
    level: str,
) -> tuple[str, ...]:
    capabilities: set[str] = set()

    if any(
        marker in text
        for marker in CODE_MARKERS
    ):
        capabilities.add("code")

    if any(
        marker in text
        for marker in ARCHITECTURE_MARKERS
    ):
        capabilities.add("architecture")

    if any(
        marker in text
        for marker in REPOSITORY_ANALYSIS_MARKERS
    ):
        capabilities.add(
            "repository_analysis"
        )

    if any(
        marker in text
        for marker in REVIEW_MARKERS
    ):
        capabilities.add("review")

    if level == "low":
        if not capabilities:
            capabilities.add("planning")

    elif level == "medium":
        capabilities.add("reasoning")

    elif level == "high":
        capabilities.add("reasoning")
        capabilities.add("review")

    elif level == "critical":
        capabilities.add(
            "deep_reasoning"
        )
        capabilities.add("review")
        capabilities.add("audit")

    return tuple(
        sorted(capabilities)
    )


def _critical_domain_count(
    text: str,
) -> int:
    domains = 0

    if any(
        marker in text
        for marker in {
            "produção",
            "production",
        }
    ):
        domains += 1

    if any(
        marker in text
        for marker in {
            "migração",
            "migration",
            "schema",
            "banco de dados",
            "database",
        }
    ):
        domains += 1

    if any(
        marker in text
        for marker in {
            "segurança",
            "security",
            "autenticação",
            "authentication",
            "authorization",
            "permissão",
            "permissions",
            "rls",
            "row level security",
            "secret",
            "secrets",
            "credential",
            "credentials",
            "token",
            "criptografia",
            "encryption",
        }
    ):
        domains += 1

    if any(
        marker in text
        for marker in {
            "deploy",
            "deployment",
            "rollback",
            "sudo",
            "sudoers",
            "systemd",
            "infraestrutura",
            "infrastructure",
        }
    ):
        domains += 1

    if any(
        marker in text
        for marker in {
            "pagamento",
            "payment",
            "billing",
        }
    ):
        domains += 1

    return domains


def classify_task(
    task: Any,
    plan: Any,
    subtasks: Iterable[Any] | None = None,
) -> ComplexityAssessment:
    subtasks = list(
        subtasks or []
    )

    text = _combined_text(
        task,
        plan,
        subtasks,
    )

    score = 10
    signals: list[str] = []

    critical_hits = _matches(
        text,
        CRITICAL_MARKERS,
    )

    high_hits = _matches(
        text,
        HIGH_MARKERS,
    )

    medium_hits = _matches(
        text,
        MEDIUM_MARKERS,
    )

    low_hits = _matches(
        text,
        LOW_MARKERS,
    )

    if critical_hits:
        score += min(
            45,
            18 * len(
                critical_hits
            ),
        )
        signals.append(
            "risco crítico: "
            + ", ".join(
                critical_hits[:5]
            )
        )

    if high_hits:
        score += min(
            30,
            10 * len(
                high_hits
            ),
        )
        signals.append(
            "complexidade alta: "
            + ", ".join(
                high_hits[:5]
            )
        )

    if medium_hits:
        score += min(
            18,
            4 * len(
                medium_hits
            ),
        )
        signals.append(
            "complexidade funcional: "
            + ", ".join(
                medium_hits[:5]
            )
        )

    if (
        low_hits
        and not critical_hits
        and not high_hits
    ):
        score -= min(
            8,
            2 * len(
                low_hits
            ),
        )
        signals.append(
            "sinais simples: "
            + ", ".join(
                low_hits[:5]
            )
        )

    subtask_count = len(
        subtasks
    )

    if subtask_count >= 10:
        score += 15
        signals.append(
            f"{subtask_count} subtasks"
        )

    elif subtask_count >= 5:
        score += 10
        signals.append(
            f"{subtask_count} subtasks"
        )

    elif subtask_count >= 2:
        score += 4
        signals.append(
            f"{subtask_count} subtasks"
        )

    constraints = _list_value(
        plan,
        "constraints",
    )

    acceptance = _list_value(
        plan,
        "acceptance_criteria",
    )

    validation = _list_value(
        plan,
        "validation_steps",
    )

    if len(constraints) >= 5:
        score += 8
        signals.append(
            "múltiplas restrições"
        )

    elif len(constraints) >= 2:
        score += 4

    if len(acceptance) >= 6:
        score += 6
        signals.append(
            "muitos critérios de aceite"
        )

    if len(validation) >= 5:
        score += 6
        signals.append(
            "validação extensa"
        )

    priority = str(
        _value(
            task,
            "priority",
            "",
        )
        or ""
    ).lower()

    if priority in {
        "critical",
        "critica",
        "crítica",
        "urgent",
        "urgente",
    }:
        score += 12
        signals.append(
            f"prioridade {priority}"
        )

    elif priority in {
        "high",
        "alta",
    }:
        score += 6
        signals.append(
            f"prioridade {priority}"
        )

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    critical_domains = (
        _critical_domain_count(
            text
        )
    )

    priority_is_critical = (
        priority
        in {
            "critical",
            "critica",
            "crítica",
            "urgent",
            "urgente",
        }
    )

    if (
        priority_is_critical
        and critical_domains >= 2
    ) or critical_domains >= 3:
        level = "critical"
        score = max(
            score,
            80,
        )
        signals.append(
            f"{critical_domains} domínios críticos combinados"
        )

    else:
        level = _level_for_score(
            score
        )

    capabilities = (
        _required_capabilities(
            text,
            level,
        )
    )

    if not signals:
        signals.append(
            "nenhum fator de risco relevante detectado"
        )

    reason = (
        f"Classificação {level} com score {score}/100. "
        + "; ".join(
            signals[:5]
        )
        + "."
    )

    return ComplexityAssessment(
        level=level,
        score=score,
        required_capabilities=capabilities,
        reason=reason,
        signals=tuple(
            signals
        ),
    )
