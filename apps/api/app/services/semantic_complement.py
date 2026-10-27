"""Complemento semântico da seleção lexical (ADR 011, decisão 3).

O `build_rag` continua sendo o **piso**: seleção lexical, sem rede, sem custo
e sempre presente. Este módulo acrescenta a recuperação semântica do
`rag_search` — mas só como **complemento**, nunca como critério de
completude (ADR 011, decisão 4).

As regras que valem para os dois caminhos:

- **mesmo teto de trechos** (`build_rag.MAX_SNIPPETS`) e **mesmo teto de
  caracteres** (`build_rag.MAX_SNIPPET_CHARS`): o semântico não abre espaço
  extra no prompt;
- **mesmo contrato de somente-leitura**: entra texto, nada mais;
- **o banco canônico continua sendo a fonte do texto**: o hit semântico
  *escolhe* a entrada, mas o trecho entregue ao agente sai da tabela
  `adrs`/`knowledge` do WorkDev, não da cópia do indexador;
- **escopo do projeto**: só entram entradas que já estão no contexto da run.
  Hit de outro projeto é ignorado, mesmo que o índice o traga;
- **degradação silenciosa**: RAG fora do ar, sem chave de embedding ou
  indexador atrasado não podem derrubar o Build — o piso lexical segue
  inteiro e o Build segue;
- **sem custo desproporcional**: a consulta semântica é cacheada por alguns
  minutos, porque a mesma task/plano é despachada mais de uma vez (worker,
  Ollama, `local-code`).

Limite conhecido e aceito: o indexador RAG publica ADR, knowledge e backlog —
**decision não é indexada**. Uma decision continua só alcançável pelo caminho
lexical ou pelo operador (ADR 014).
"""

from __future__ import annotations

import logging
import os
import time

from app.services import build_rag, rag_search


log = logging.getLogger(__name__)


# Teto de trechos: o mesmo do piso lexical. O semântico preenche o que
# sobrou, nunca abre espaço novo.
MAX_TRECHOS = build_rag.MAX_SNIPPETS

# Timeout do embedding. O Build não pode esperar por serviço externo por muito
# tempo: o piso lexical já está pronto, e o semântico é complemento.
TIMEOUT_PADRAO_SEGUNDOS = 8.0

# Quantos documentos o RAG devolve. Maior que o corte final porque parte dos
# hits é de outro projeto, de backlog ou já está no piso lexical.
LIMITE_BUSCA = 12

# Cache curto em memória: o mesmo texto de consulta não vira duas embeddings.
CACHE_TTL_SEGUNDOS = 300

# Só ADR e knowledge entram. Backlog não é referência canônica.
TIPOS_ACEITOS = {"adr", "knowledge"}


_cache: dict[str, tuple[float, list[dict]]] = {}


def _habilitado() -> bool:
    bruto = os.getenv("WORKDEV_SEMANTIC_COMPLEMENT", "1").strip().lower()

    return bruto not in {"0", "false", "off", "nao", "não", "sem"}


def _timeout() -> float:
    try:
        return max(
            1.0,
            float(
                os.getenv(
                    "WORKDEV_SEMANTIC_TIMEOUT",
                    str(TIMEOUT_PADRAO_SEGUNDOS),
                )
            ),
        )
    except (TypeError, ValueError):
        return TIMEOUT_PADRAO_SEGUNDOS


def consulta(context: dict) -> str:
    """Texto da consulta semântica: a task e o plano, em uma frase só."""
    task = context.get("task") or {}
    plan = context.get("plan") or {}

    partes = [
        task.get("title"),
        task.get("description"),
        plan.get("objective"),
        plan.get("scope"),
    ]

    return "\n".join(str(parte).strip() for parte in partes if parte and parte.strip()).strip()


def _identidade(hit: dict) -> tuple[str, str | None]:
    """Descobre (tipo, id) canônico de um hit do RAG.

    O indexador publica `fonte_id` no formato `adr:<id>` / `knowledge:<id>` e
    repete o id em `metadados` (`adr_id`, `knowledge_id`).
    """
    metadados = hit.get("metadados") or {}
    tipo = str(metadados.get("tipo") or "").strip().lower()
    identificador = metadados.get("adr_id") or metadados.get("knowledge_id")

    if not identificador:
        fonte_id = str(hit.get("fonte_id") or "")
        if ":" in fonte_id:
            prefixo, _, resto = fonte_id.partition(":")
            tipo = tipo or prefixo.strip().lower()
            identificador = resto

    if tipo not in TIPOS_ACEITOS:
        return tipo, None

    return tipo, str(identificador).strip() if identificador else None


def _buscar(texto: str) -> list[dict]:
    """Chama o RAG com cache curto em memória."""
    agora = time.monotonic()
    entrada = _cache.get(texto)

    if entrada and (agora - entrada[0]) < CACHE_TTL_SEGUNDOS:
        return entrada[1]

    hits = rag_search.search(texto, limit=LIMITE_BUSCA, timeout=_timeout())
    _cache[texto] = (agora, hits)

    return hits


def _limpar_cache() -> None:
    _cache.clear()


def completar(context: dict, ja_selecionados: list[dict]) -> list[dict]:
    """Trechos canônicos que o lexical deixou de fora, por relevância semântica.

    Devolve [] sempre que o semântico não puder responder — o piso lexical já
    está montado e é ele que garante o Build.
    """
    if not _habilitado():
        return []

    if len(ja_selecionados) >= MAX_TRECHOS:
        return []

    texto = consulta(context)
    if not texto:
        return []

    candidatos = {
        str(candidato.get("id")): candidato
        for candidato in build_rag.candidates(context)
        if candidato.get("id")
    }

    ja_vistos = {str(trecho.get("id")) for trecho in ja_selecionados}
    restantes = {
        identificador: candidato
        for identificador, candidato in candidatos.items()
        if identificador not in ja_vistos
    }

    if not restantes:
        return []

    try:
        hits = _buscar(texto)
    except Exception as erro:  # degradação: o Build não pode depender do RAG
        log.info(
            "rag_semantico_indisponivel: %s",
            type(erro).__name__,
        )
        return []

    limite = MAX_TRECHOS - len(ja_selecionados)
    saida: list[dict] = []

    for hit in hits:
        _tipo, identificador = _identidade(hit)
        if not identificador:
            continue

        candidato = restantes.get(identificador)
        if candidato is None:
            # Hit de outro projeto, ou entrada que não está no contexto da run.
            continue

        saida.append(
            {
                **candidato,
                "score": hit.get("score"),
                "origem": "semantico",
            }
        )

        if len(saida) >= limite:
            break

    return saida
