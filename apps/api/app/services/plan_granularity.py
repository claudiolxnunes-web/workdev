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

import hashlib
import re


MAX_ACCEPTANCE_CRITERIA = 8
MAX_VALIDATION_STEPS = 8
MAX_SCOPE_CHARS = 1500
MIN_SLICES_WHEN_OVERSIZED = 2
MAX_SLICE_TITLE_CHARS = 120
# 8 hex = 4 bilhões de valores para um punhado de fatias por plano. Curto o
# bastante para não poluir o título na UI.
SLICE_ID_CHARS = 8

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


def _slice_id(item: str) -> str:
    """Identificador estável derivado do texto ÍNTEGRO da frente.

    Derivado do conteúdo, não da posição: reordenar o escopo não renomeia as
    fatias já materializadas. Duas frentes de texto idêntico continuam com o
    mesmo id de propósito — são a mesma fatia, e é isso que mantém o gate
    satisfazível quando o escopo repete uma frente.
    """
    normalizado = _normalizar_titulo(item)
    digest = hashlib.sha256(normalizado.encode("utf-8")).hexdigest()
    return digest[:SLICE_ID_CHARS]


_SUFIXO_DE_ID = re.compile(r"\s\[[0-9a-f]{%d}\]$" % SLICE_ID_CHARS)


def _sem_identificador(titulo: str) -> str:
    """Título no formato antigo: só o corpo truncado, sem o `[id]`."""
    return _SUFIXO_DE_ID.sub("", titulo)


def slice_keys(fatias: list[dict]) -> dict[str, str]:
    """Chaves de título aceitas por fatia → chave canônica da fatia.

    Aceita dois formatos, para não exigir migração das 216 subtasks criadas
    antes do identificador: o título atual (`corpo [id]`) e o legado (só
    `corpo`). Sem isto, decompor de novo duplicaria toda subtask antiga.

    Um título legado que casaria com mais de uma fatia é exatamente a colisão
    por truncamento que o identificador veio corrigir — nesse caso ele não
    cobre fatia nenhuma, e a subtask precisa do formato novo.
    """
    canonico: dict[str, str] = {}
    legadas: dict[str, set[str]] = {}

    for fatia in fatias:
        chave = _normalizar_titulo(fatia["title"])
        canonico[chave] = chave
        legada = _normalizar_titulo(_sem_identificador(fatia["title"]))
        if legada != chave:
            legadas.setdefault(legada, set()).add(chave)

    for legada, alvos in legadas.items():
        if len(alvos) == 1 and legada not in canonico:
            canonico[legada] = next(iter(alvos))

    return canonico


def _titulo_de_fatia(item: str) -> str:
    """Título da fatia: texto truncado mais o identificador do conteúdo.

    O truncamento sozinho colidia: duas frentes distintas que compartilhassem
    os primeiros 120 caracteres viravam o mesmo título, `titulos_de_fatia`
    contava 1, e uma única subtask cobria as duas. O identificador vem do
    texto completo, antes do corte, então frentes diferentes nunca colapsam
    numa fatia só.
    """
    texto = item.strip()
    corpo = texto[:MAX_SLICE_TITLE_CHARS].rstrip()

    if len(texto) > MAX_SLICE_TITLE_CHARS:
        corpo += "…"

    return f"{corpo} [{_slice_id(texto)}]"


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

    # Frentes DISTINTAS, como o texto do sinal sempre prometeu. Contar itens
    # brutos sinalizava como grande um escopo que repete a mesma frente duas
    # vezes — e aí o gate exigia duas fatias que não existem. Contar distintas
    # resolve isso na origem, sem precisar afrouxar a exigência de cobertura.
    frentes_distintas = {_normalizar_titulo(item) for item in itens}

    if len(frentes_distintas) >= MIN_SLICES_WHEN_OVERSIZED:
        signals.append(
            f"escopo enumera {len(frentes_distintas)} frentes distintas"
        )

    oversized = bool(signals)
    fatias = suggest_slices(plan) if oversized else []

    # Contar subtask não basta. Uma subtask antiga, única e sem relação com as
    # fatias derivadas satisfazia o gate — era `bool(subtasks)`, e uma revisão
    # independente (Codex, 2026-09-09) mostrou que isso deixa passar
    # exatamente o trabalho monolítico que o gate existe para barrar.
    #
    # Agora vale correspondência: só conta a subtask cujo título bate com uma
    # das fatias derivadas do próprio plano — no formato atual ou no legado
    # (ver `slice_keys`). `decompose_plan` materializa essas fatias com esse
    # título, então o gate é satisfazível pela ferramenta oficial sempre que o
    # próprio texto do plano render fatias suficientes — e continua contornável
    # por `force=true`, decisão explícita e auditável do operador.
    aceitas = slice_keys(fatias)

    titulos_de_fatia: dict[str, str] = {}
    for fatia in fatias:
        titulos_de_fatia.setdefault(_normalizar_titulo(fatia["title"]), fatia["title"])

    correspondentes = [
        subtask
        for subtask in subtasks
        if _normalizar_titulo(getattr(subtask, "title", None)) in aceitas
    ]

    # O que decide é COBERTURA, não contagem de subtasks correspondentes.
    # Quatro subtasks duplicando a mesma fatia dão quatro correspondências e
    # cobrem uma frente só — passariam num teste de contagem e deixariam três
    # frentes sem unidade auditável, que é precisamente o que o gate existe
    # para impedir.
    cobertos = {
        aceitas[_normalizar_titulo(getattr(subtask, "title", None))]
        for subtask in correspondentes
    }

    # Uma unidade por fatia distinta, e nunca menos que o mínimo: UMA fatia não
    # é decomposição. Sem o piso, um plano marcado como grande por 9 etapas de
    # validação — ou por escopo extenso — com um único critério de aceite era
    # "decomposto" por uma subtask só.
    #
    # O piso não recria o gate insatisfazível de antes porque a causa daquele
    # caso foi corrigida na origem: o sinal de escopo agora conta frentes
    # DISTINTAS, então repetir a mesma frente não marca mais o plano como
    # grande. Quando ainda assim o texto não render fatias suficientes,
    # `decomposable` fica falso e a mensagem diz o que fazer, em vez de o
    # operador esbarrar num bloqueio mudo.
    exigidas = (
        max(MIN_SLICES_WHEN_OVERSIZED, len(titulos_de_fatia)) if oversized else 0
    )
    derivaveis = len(titulos_de_fatia)

    if oversized:
        decomposto = derivaveis >= exigidas and len(cobertos) >= exigidas
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
        "derivable_slices": derivaveis,
        # Falso quando o texto do plano não rende fatias distintas bastantes:
        # decompor não resolve, é preciso enumerar/detalhar as frentes.
        "decomposable": (not oversized) or derivaveis >= exigidas,
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
        titulo = _titulo_de_fatia(item)
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
