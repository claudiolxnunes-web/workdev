"""Check: divergência entre os lugares onde o conhecimento do WorkDev mora.

Hoje a mesma decisão pode existir em quatro lugares — tabela `adrs`, tabela
`knowledge`, arquivo em `decisions/` e índice do RAG. ADRs e knowledge são
projetados por API; arquivos em `docs/adr` e `decisions/` continuam sendo
fontes em disco. Este check não resolve o problema: mede a distância entre as
fontes vigentes.

Achados de volume (ADRs e conhecimento fora do índice) são **um Fato por
subcheck**, com a contagem em `medidas`. Um Fato por registro produziria mais
de cem achados no primeiro dia, que é exatamente o modo de falha que a
deduplicação existe para evitar.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..contexto import Contexto
from ..modelo import Fato, classificar, normalizar_titulo


NOME = "knowledge_drift"

SQL_ADRS = "SELECT id::text AS id, title, status, created_at FROM adrs"
SQL_KNOWLEDGE = "SELECT id::text AS id, title, category, created_at FROM knowledge"
SQL_TABELA_VAZIA = "SELECT count(*) AS total FROM {tabela}"


def coletar(contexto: Contexto) -> list[Fato]:
    # Abre o RAG antes de qualquer trabalho: se estiver fora do ar, o check
    # inteiro degrada em vez de reportar meia verdade.
    documentos = contexto.rag().documentos()

    adrs = contexto.workdev.consultar(SQL_ADRS)
    conhecimento = contexto.workdev.consultar(SQL_KNOWLEDGE)
    vazias = []
    for tabela in config.TABELAS_VIGIADAS_VAZIAS:
        linhas = contexto.workdev.consultar(SQL_TABELA_VAZIA.format(tabela=tabela))
        if int(linhas[0]["total"]) == 0:
            vazias.append(tabela)

    repo = contexto.repo()
    arquivos = []
    for subcaminho, tipo, e_diretorio in config.RAG_RAIZES:
        for caminho in repo.arquivos_markdown(subcaminho, e_diretorio):
            arquivos.append(
                {
                    "caminho": caminho,
                    "tipo": tipo,
                    "titulo": repo.titulo_markdown(caminho),
                }
            )

    return avaliar(
        {
            "documentos": documentos,
            "adrs": adrs,
            "knowledge": conhecimento,
            "arquivos": arquivos,
            "tabelas_vazias": vazias,
        },
        contexto.agora,
    )


def avaliar(dados: dict, agora: datetime) -> list[Fato]:
    documentos = dados.get("documentos") or []
    titulos_indexados = {normalizar_titulo(d.get("titulo")) for d in documentos}
    titulos_indexados.discard("")
    fontes_indexadas = {d.get("fonte_id") for d in documentos}

    fatos: list[Fato] = []
    fatos += _fora_do_indice(
        "adr_fora_do_rag",
        "ADR",
        dados.get("adrs") or [],
        titulos_indexados,
        agora,
        "SELECT title FROM adrs ORDER BY created_at;",
    )
    fatos += _fora_do_indice(
        "knowledge_fora_do_rag",
        "registro de conhecimento",
        dados.get("knowledge") or [],
        titulos_indexados,
        agora,
        "SELECT title, category FROM knowledge ORDER BY created_at;",
    )
    fatos += _arquivos_nao_indexados(dados.get("arquivos") or [], fontes_indexadas, agora)
    fatos += _fontes_duplicadas(dados, agora)
    fatos += _estrutura_morta(dados.get("tabelas_vazias") or [], agora)
    return fatos


def _fato(subcheck: str, entidade: str, severidade: str, bucket: str, ordem: int,
          titulo: str, agora: datetime, medidas: dict, evidencia: tuple) -> Fato:
    return Fato(
        check=NOME,
        subcheck=subcheck,
        entity_type="conhecimento",
        entity_id=entidade,
        project_name="WorkDev Core",
        severity=severidade,
        bucket=bucket,
        bucket_ordem=ordem,
        titulo=titulo,
        detected_at=agora.isoformat(),
        medidas=medidas,
        evidencia=evidencia,
    )


def _fora_do_indice(subcheck, rotulo, registros, titulos_indexados, agora, consulta):
    ausentes = [
        r for r in registros if normalizar_titulo(r.get("title")) not in titulos_indexados
    ]
    if not ausentes:
        return []
    bucket, ordem = classificar(len(ausentes), config.FAIXAS_REGISTROS)
    return [
        _fato(
            subcheck,
            subcheck,
            "high" if len(ausentes) > 5 else "medium",
            bucket,
            ordem,
            f"{len(ausentes)} de {len(registros)} {rotulo}(s) do Postgres não estão "
            "no índice do RAG",
            agora,
            {
                "ausentes": len(ausentes),
                "total": len(registros),
                "exemplos": [r.get("title") for r in ausentes[:5]],
            },
            (consulta, "SELECT titulo FROM documentos WHERE fonte = 'workdev';"),
        )
    ]


def _arquivos_nao_indexados(arquivos, fontes_indexadas, agora):
    ausentes = [a["caminho"] for a in arquivos if a["caminho"] not in fontes_indexadas]
    if not ausentes:
        return []
    bucket, ordem = classificar(len(ausentes), config.FAIXAS_REGISTROS)
    return [
        _fato(
            "arquivo_nao_indexado",
            "arquivo_nao_indexado",
            "medium",
            bucket,
            ordem,
            f"{len(ausentes)} arquivo(s) textual(is) sob as raízes do ingestor não estão "
            "no índice",
            agora,
            {"ausentes": len(ausentes), "exemplos": ausentes[:5]},
            (
                "systemctl status workdev-rag-ingest.timer",
                "journalctl -u workdev-rag-ingest -n 50",
            ),
        )
    ]


def _fontes_duplicadas(dados: dict, agora: datetime):
    """Mesmo título normalizado em mais de um store **de escrita**.

    O índice do RAG fica fora da conta de propósito: ele é derivado do disco,
    não uma fonte concorrente. Contá-lo faria o check reportar como problema o
    estado saudável — um ADR em arquivo e o mesmo ADR indexado.

    Os stores que competem de verdade são três: a tabela `adrs`, a tabela
    `knowledge` e os arquivos em `decisions/`.
    """
    por_titulo: dict[str, set[str]] = {}
    for registro in dados.get("adrs") or []:
        por_titulo.setdefault(normalizar_titulo(registro.get("title")), set()).add("adrs")
    for registro in dados.get("knowledge") or []:
        por_titulo.setdefault(normalizar_titulo(registro.get("title")), set()).add("knowledge")
    for arquivo in dados.get("arquivos") or []:
        titulo = normalizar_titulo(arquivo.get("titulo"))
        if titulo:
            por_titulo.setdefault(titulo, set()).add("disco")

    duplicados = sorted(
        titulo for titulo, stores in por_titulo.items() if titulo and len(stores) > 1
    )
    if not duplicados:
        return []
    bucket, ordem = classificar(len(duplicados), config.FAIXAS_REGISTROS)
    return [
        _fato(
            "fonte_duplicada",
            "fonte_duplicada",
            "medium",
            bucket,
            ordem,
            f"{len(duplicados)} título(s) existem em mais de um store de escrita "
            "(adrs, knowledge, decisions/)",
            agora,
            {"duplicados": len(duplicados), "exemplos": duplicados[:5]},
            (
                "SELECT title FROM adrs;",
                "SELECT title FROM knowledge WHERE category = 'decisao';",
                "ls /opt/workdev/decisions/",
            ),
        )
    ]


def _estrutura_morta(tabelas_vazias, agora):
    if not tabelas_vazias:
        return []
    return [
        _fato(
            "estrutura_morta",
            "estrutura_morta",
            "info",
            ",".join(sorted(tabelas_vazias)),
            0,
            f"tabela(s) {', '.join(sorted(tabelas_vazias))} vazias com endpoint ativo — "
            "estrutura competindo com adrs e decisions/",
            agora,
            {"tabelas": sorted(tabelas_vazias)},
            tuple(f"SELECT count(*) FROM {t};" for t in sorted(tabelas_vazias)),
        )
    ]
