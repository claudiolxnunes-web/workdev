"""Granularidade do PLAN: trabalho grande vira fatias auditáveis.

Regra de qualidade que o WorkDev passa a cobrar: um plano aprovado precisa ser
executável em unidades pequenas, cada uma com objetivo único, escopo limitado e
gate próprio. Refatoração monolítica de um lote só não é auditável — quando
falha, não dá para saber qual parte falhou.

O módulo não adivinha o conteúdo: ele lê o que já está no plano (escopo com
itens numerados, critérios de aceite, etapas de validação) e (a) sinaliza
quando o plano está grande demais, (b) propõe as fatias a partir do próprio
texto do escopo.
"""

import re


MAX_ACCEPTANCE_CRITERIA = 8
MAX_VALIDATION_STEPS = 8
MAX_SCOPE_CHARS = 1500
MIN_SLICES_WHEN_OVERSIZED = 2

# Itens numerados do escopo: "1. algo", "2) outra coisa", "- item".
_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$")


def _scope_items(scope: str | None) -> list[str]:
    if not scope:
        return []

    itens = []

    for linha in scope.splitlines():
        match = _NUMBERED.match(linha)
        if match:
            texto = match.group(1).strip()
            if texto:
                itens.append(texto)

    if itens:
        return itens

    # Escopo em parágrafo único com enumeração inline: "1. a 2. b 3. c".
    inline = re.split(r"(?:(?<=\D)|^)\s*\d+[.)]\s+", scope)
    inline = [parte.strip() for parte in inline if parte.strip()]

    return inline if len(inline) > 1 else []


def _normalizar_titulo(valor) -> str:
    """Título comparável: espaços colapsados e caixa neutra."""
    return " ".join(str(valor or "").split()).casefold()


def assess(plan, subtasks=None) -> dict:
    """Diz se o plano está grande demais e por quê, sem alterar nada."""
    subtasks = list(subtasks or [])

    # scope é nullable no modelo; os demais campos podem faltar em planos
    # antigos. Nada aqui pode estourar por ausência de campo opcional.
    criterios = list(getattr(plan, "acceptance_criteria", None) or [])
    validacoes = list(getattr(plan, "validation_steps", None) or [])
    escopo = getattr(plan, "scope", None) or ""
    itens = _scope_items(escopo)

    signals: list[str] = []

    if len(criterios) > MAX_ACCEPTANCE_CRITERIA:
        signals.append(
            f"{len(criterios)} critérios de aceite "
            f"(acima de {MAX_ACCEPTANCE_CRITERIA})"
        )

    if len(validacoes) > MAX_VALIDATION_STEPS:
        signals.append(
            f"{len(validacoes)} etapas de validação "
            f"(acima de {MAX_VALIDATION_STEPS})"
        )

    if len(escopo) > MAX_SCOPE_CHARS:
        signals.append(
            f"escopo com {len(escopo)} caracteres "
            f"(acima de {MAX_SCOPE_CHARS})"
        )

    if len(itens) >= MIN_SLICES_WHEN_OVERSIZED:
        signals.append(
            f"escopo enumera {len(itens)} frentes distintas"
        )

    oversized = bool(signals)
    fatias = suggest_slices(plan) if oversized else []

    # Contar subtask não basta. Uma subtask antiga, única e sem relação com as
    # fatias derivadas satisfazia o gate — era `bool(subtasks)`, e uma revisão
    # independente (Codex, 2026-09-09) mostrou que isso deixa passar
    # exatamente o trabalho monolítico que o gate existe para barrar.
    #
    # Agora vale correspondência: só conta a subtask cujo título bate com uma
    # das fatias derivadas do próprio plano. `decompose_plan` materializa essas
    # fatias com esse título, então o gate é sempre satisfazível pela
    # ferramenta oficial — e continua contornável por `force=true`, que é
    # decisão explícita e auditável do operador.
    # Fatias distintas, na ordem em que o plano as declara. `suggest_slices`
    # pode repetir título quando o escopo enumera a mesma frente duas vezes;
    # exigir uma unidade por título repetido seria um gate insatisfazível.
    titulos_de_fatia: dict[str, str] = {}
    for fatia in fatias:
        titulos_de_fatia.setdefault(_normalizar_titulo(fatia["title"]), fatia["title"])

    correspondentes = [
        subtask
        for subtask in subtasks
        if _normalizar_titulo(getattr(subtask, "title", None))
        in titulos_de_fatia
    ]

    # O que decide é COBERTURA, não contagem de subtasks correspondentes.
    # Quatro subtasks duplicando a mesma fatia dão quatro correspondências e
    # cobrem uma frente só — passariam num teste de contagem e deixariam três
    # frentes sem unidade auditável, que é precisamente o que o gate existe
    # para impedir.
    cobertos = {
        _normalizar_titulo(getattr(subtask, "title", None))
        for subtask in correspondentes
    }

    # Uma unidade por fatia distinta, nunca menos que o mínimo.
    exigidas = (
        max(MIN_SLICES_WHEN_OVERSIZED, len(titulos_de_fatia)) if oversized else 0
    )

    if oversized:
        decomposto = len(cobertos) >= exigidas
    else:
        # Nada a corresponder: plano já é uma unidade auditável.
        decomposto = bool(subtasks)

    return {
        "oversized": oversized,
        "signals": signals,
        "subtask_count": len(subtasks),
        "matching_subtask_count": len(correspondentes),
        "covered_slices": len(cobertos),
        "required_slices": exigidas,
        "missing_slices": [
            titulo
            for normalizado, titulo in titulos_de_fatia.items()
            if normalizado not in cobertos
        ],
        "decomposed": decomposto,
        "suggested_slices": fatias,
        "requires_decomposition": oversized and not decomposto,
    }


def suggest_slices(plan) -> list[dict]:
    """Fatias propostas a partir do texto do próprio plano.

    Cada fatia carrega objetivo único e o lembrete de gate próprio: é assim que
    ela vira auditável isoladamente.
    """
    itens = _scope_items(getattr(plan, "scope", None))

    if not itens:
        # Sem enumeração no escopo, cada critério de aceite vira uma fatia
        # candidata — é a menor unidade verificável que o plano já declarou.
        itens = [
            str(criterio)
            for criterio in (getattr(plan, "acceptance_criteria", None) or [])
        ]

    fatias = []

    for ordem, item in enumerate(itens, start=1):
        titulo = item.strip()
        titulo = titulo[:120].rstrip() + ("…" if len(titulo) > 120 else "")
        fatias.append(
            {
                "order": ordem,
                "title": titulo,
                "description": (
                    f"Fatia {ordem} de {len(itens)} do plano "
                    f"'{getattr(plan, 'title', 'sem título')}'.\n\n"
                    f"Escopo desta fatia: {item.strip()}\n\n"
                    "Objetivo único, escopo limitado. Entregar com testes e "
                    "gates próprios e passar por revisão independente antes "
                    "de seguir para a fatia seguinte."
                ),
            }
        )

    return fatias
