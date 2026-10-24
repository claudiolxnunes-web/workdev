#!/usr/bin/env python3
"""Ingestor incremental do RAG WorkDev para PostgreSQL/pgvector.

Varre arquivos Markdown e texto nas raizes configuradas, projeta ADRs, Knowledge
e Backlog da API do WorkDev, adia arquivos ainda instaveis, gera embeddings somente para conteudo
novo/modificado e remove documentos apenas de fontes cuja leitura foi
integralmente validada.

Uso:
    ingestor.py --dry-run      # calcula o plano sem chamar API nem escrever
    ingestor.py                # executa a ingestao incremental
    ingestor.py --no-prune     # preserva documentos removidos do disco
"""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import requests


# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------

ENV_FILE = Path("/opt/rag-postgres/.env")
ROOT_PADRAO = Path("/opt/workdev")
LOCK_FILE = Path("/run/lock/workdev-rag-ingest.lock")
FONTE = "workdev"
ADR_FONTE = "workdev_api_adrs"
KNOWLEDGE_FONTE = "workdev_api_knowledge"
BACKLOG_FONTE = "workdev_api_backlog"
WORKDEV_API_URL_PADRAO = "http://127.0.0.1:8000/api"
WORKDEV_API_TIMEOUT = 20

MODELO = "text-embedding-3-small"
DIMENSOES = 1536
LIMITE_CHARS = 24000
ESTABILIDADE_SEGUNDOS = 60
RETRY_BACKOFF_SEGUNDOS = (2, 5)
HTTP_TRANSITORIOS = {408, 409, 425, 429, 500, 502, 503, 504}

# (subcaminho, tipo, e_diretorio)
ALVOS = [
    ("docs/adr", "adr", True),
    ("decisions", "decision", True),
]


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(chave: str, valor) -> None:
    print(f"{chave}={valor}", flush=True)


def metricas_vazias() -> dict:
    return {
        "documents_seen": 0,
        "documents_new": 0,
        "documents_modified": 0,
        "documents_deleted": 0,
        "documents_unchanged": 0,
        "unstable_files_deferred": 0,
        "embeddings_requested": 0,
        "embeddings_success": 0,
        "embeddings_failed": 0,
        "roots_available": 0,
        "roots_unavailable": 0,
    }


def emitir_resumo(inicio_monotonic: float, metricas: dict, status: str) -> None:
    log("finished_at", agora_iso())
    log("duration_seconds", f"{time.monotonic() - inicio_monotonic:.3f}")
    for chave in (
        "documents_seen",
        "documents_new",
        "documents_modified",
        "documents_deleted",
        "documents_unchanged",
        "unstable_files_deferred",
        "embeddings_requested",
        "embeddings_success",
        "embeddings_failed",
        "roots_available",
        "roots_unavailable",
    ):
        log(chave, metricas[chave])
    log("status", status)


# --------------------------------------------------------------------------
# Lock de processo
# --------------------------------------------------------------------------

def adquirir_lock():
    """Adquire flock nao bloqueante; o descritor aberto mantem o lock vivo."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    descritor = LOCK_FILE.open("a+")
    try:
        fcntl.flock(descritor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        descritor.close()
        return None
    descritor.seek(0)
    descritor.truncate()
    descritor.write(f"pid={os.getpid()} started_at={agora_iso()}\n")
    descritor.flush()
    return descritor


# --------------------------------------------------------------------------
# Credenciais
# --------------------------------------------------------------------------

def carregar_env(caminho: Path) -> dict:
    """Le .env simples em KEY=VALUE sem registrar valores."""
    dados = {}
    if not caminho.exists():
        return dados
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        dados[chave.strip()] = valor.strip().strip('"').strip("'")
    return dados


def montar_dsn(env: dict) -> str:
    if os.environ.get("RAG_DSN"):
        return os.environ["RAG_DSN"]

    usuario = env.get("POSTGRES_USER") or env.get("RAG_USER") or "rag"
    banco = env.get("POSTGRES_DB") or env.get("RAG_DB") or "rag"
    senha = (
        env.get("POSTGRES_PASSWORD")
        or env.get("RAG_PASSWORD")
        or env.get("PGPASSWORD")
        or os.environ.get("PGPASSWORD")
    )
    if not senha:
        raise RuntimeError(
            "senha do PostgreSQL ausente; defina POSTGRES_PASSWORD no .env "
            "ou RAG_DSN no ambiente"
        )
    return f"postgresql://{usuario}:{senha}@127.0.0.1:5433/{banco}"


def obter_chave_openai(env: dict) -> str:
    chave = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    if not chave:
        raise RuntimeError("OPENAI_API_KEY ausente no ambiente e no .env")
    return chave


# --------------------------------------------------------------------------
# Coleta segura
# --------------------------------------------------------------------------

def _arquivo_estavel(arq: Path, agora: float):
    """Le arquivo apenas se idade, tamanho e mtime permanecerem estaveis."""
    try:
        antes = arq.stat()
        if agora - antes.st_mtime < ESTABILIDADE_SEGUNDOS:
            return None, "unstable"
        conteudo = arq.read_text(encoding="utf-8", errors="replace").strip()
        depois = arq.stat()
    except (OSError, PermissionError) as erro:
        return None, erro

    if (antes.st_mtime_ns, antes.st_size) != (depois.st_mtime_ns, depois.st_size):
        return None, "unstable"
    if time.time() - depois.st_mtime < ESTABILIDADE_SEGUNDOS:
        return None, "unstable"
    return conteudo, None



def _arquivo_sensivel(caminho: Path) -> bool:
    """Bloqueia arquivos que nunca devem virar embedding, mesmo que a
    raiz de varredura seja ampliada no futuro. Verifica nome do arquivo
    e cada segmento do caminho, sem exigir manutencao a cada nova raiz.
    """
    nome = caminho.name.lower()
    partes = [p.lower() for p in caminho.parts]

    NOMES_PROIBIDOS = {
        ".env", ".env.local", ".env.production", ".env.development",
        ".npmrc", ".pgpass", "id_rsa", "id_ed25519",
    }
    if nome in NOMES_PROIBIDOS or nome.startswith(".env"):
        return True

    SUFIXOS_PROIBIDOS = (
        ".pem", ".key", ".crt", ".p12", ".pfx",
        ".sql", ".dump", ".bak",
    )
    if nome.endswith(SUFIXOS_PROIBIDOS):
        return True

    PASTAS_PROIBIDAS = {
        "secrets", "credentials", "keys", ".git", "node_modules",
        "backups", "uploads",
    }
    if PASTAS_PROIBIDAS & set(partes):
        return True

    PALAVRAS_PROIBIDAS = ("secret", "password", "senha", "token", "apikey", "api_key", "credential")
    if any(palavra in nome for palavra in PALAVRAS_PROIBIDAS):
        return True

    return False


def _listar_markdown(alvo: Path):
    erros = []

    def ao_erro(erro):
        erros.append(erro)

    arquivos = []
    for diretorio, _, nomes in os.walk(alvo, onerror=ao_erro, followlinks=False):
        for nome in nomes:
            if nome.endswith((".md", ".txt")):
                caminho_arq = Path(diretorio) / nome
                if _arquivo_sensivel(caminho_arq):
                    continue
                arquivos.append(caminho_arq)
    return sorted(arquivos), erros


def _conteudo_adr(adr: dict) -> str:
    """Renderiza a projeção derivada sem criar um arquivo intermediário."""
    secoes = [
        f"# {str(adr.get('title') or '').strip()}",
        f"Status: {adr.get('status') or 'proposed'}",
        "## Contexto",
        str(adr.get("context") or "").strip(),
        "## Decisão",
        str(adr.get("decision") or "").strip(),
    ]
    consequencias = str(adr.get("consequences") or "").strip()
    if consequencias:
        secoes.extend(("## Consequências", consequencias))
    return "\n\n".join(parte for parte in secoes if parte).strip()


def coletar_adrs(env: dict):
    """Consulta a fonte canônica e devolve projeções com identidade estável."""
    chave = env.get("WORKDEV_API_KEY") or os.environ.get("WORKDEV_API_KEY")
    if not chave:
        return [], set(), {"available": False, "error": "WORKDEV_API_KEY ausente"}

    base = (env.get("WORKDEV_API_URL") or os.environ.get("WORKDEV_API_URL")
            or WORKDEV_API_URL_PADRAO).rstrip("/")
    try:
        resposta = requests.get(
            f"{base}/adrs",
            headers={"X-API-Key": chave},
            timeout=WORKDEV_API_TIMEOUT,
        )
        resposta.raise_for_status()
        registros = resposta.json()
        if not isinstance(registros, list):
            raise ValueError("resposta de ADRs não é uma lista")
    except (requests.RequestException, ValueError) as erro:
        return [], set(), {"available": False, "error": str(erro)}

    docs = []
    presentes = set()
    for adr in registros:
        identificador = str(adr.get("id") or "").strip()
        titulo = str(adr.get("title") or "").strip()
        if not identificador or not titulo:
            return [], set(), {
                "available": False,
                "error": "ADR sem id ou title na resposta da API",
            }
        fonte_id = f"adr:{identificador}"
        conteudo = _conteudo_adr(adr)
        presentes.add(fonte_id)
        docs.append({
            "fonte_id": fonte_id,
            "titulo": titulo[:300],
            "conteudo": conteudo,
            "hash": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
            "metadados": {
                "tipo": "adr",
                "adr_id": identificador,
                "project_id": str(adr.get("project_id") or ""),
                "status": str(adr.get("status") or "proposed"),
                "origem": "workdev_api",
                "linhas": conteudo.count("\n") + 1,
                "chars": len(conteudo),
            },
        })
    return docs, presentes, {"available": True, "error": None}


def _consultar_api(env: dict, recurso: str, nome: str):
    """Consulta uma coleção da API sem expor a chave nos erros ou logs."""
    chave = env.get("WORKDEV_API_KEY") or os.environ.get("WORKDEV_API_KEY")
    if not chave:
        return None, {"available": False, "error": "WORKDEV_API_KEY ausente"}

    base = (env.get("WORKDEV_API_URL") or os.environ.get("WORKDEV_API_URL")
            or WORKDEV_API_URL_PADRAO).rstrip("/")
    try:
        resposta = requests.get(
            f"{base}/{recurso}",
            headers={"X-API-Key": chave},
            timeout=WORKDEV_API_TIMEOUT,
        )
        resposta.raise_for_status()
        registros = resposta.json()
        if not isinstance(registros, list):
            raise ValueError(f"resposta de {nome} não é uma lista")
    except (requests.RequestException, ValueError) as erro:
        return None, {"available": False, "error": str(erro)}
    return registros, {"available": True, "error": None}


def _documento_api(fonte_id: str, titulo: str, conteudo: str, metadados: dict):
    return {
        "fonte_id": fonte_id,
        "titulo": titulo[:300],
        "conteudo": conteudo,
        "hash": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
        "metadados": {
            **metadados,
            "origem": "workdev_api",
            "linhas": conteudo.count("\n") + 1,
            "chars": len(conteudo),
        },
    }


def coletar_knowledge(env: dict):
    """Projeta cada entrada de Knowledge da API como documento individual."""
    registros, estado = _consultar_api(env, "knowledge", "Knowledge")
    if registros is None:
        return [], set(), estado

    docs = []
    presentes = set()
    for entrada in registros:
        identificador = str(entrada.get("id") or "").strip()
        titulo = str(entrada.get("title") or "").strip()
        corpo = str(entrada.get("content") or "").strip()
        if not identificador or not titulo:
            return [], set(), {
                "available": False,
                "error": "Knowledge sem id ou title na resposta da API",
            }
        fonte_id = f"knowledge:{identificador}"
        secoes = [f"# {titulo}"]
        categoria = str(entrada.get("category") or "licao").strip()
        tags = str(entrada.get("tags") or "").strip()
        if categoria:
            secoes.append(f"Categoria: {categoria}")
        if tags:
            secoes.append(f"Tags: {tags}")
        if corpo:
            secoes.extend(("## Conteúdo", corpo))
        conteudo = "\n\n".join(secoes).strip()
        presentes.add(fonte_id)
        docs.append(_documento_api(fonte_id, titulo, conteudo, {
            "tipo": "knowledge",
            "knowledge_id": identificador,
            "project_id": str(entrada.get("project_id") or ""),
            "backlog_id": str(entrada.get("backlog_id") or ""),
            "category": categoria,
            "tags": tags,
        }))
    return docs, presentes, estado


def coletar_backlog(env: dict):
    """Projeta cada item do Backlog da API como documento individual."""
    registros, estado = _consultar_api(env, "backlog", "Backlog")
    if registros is None:
        return [], set(), estado

    docs = []
    presentes = set()
    for item in registros:
        identificador = str(item.get("id") or "").strip()
        titulo = str(item.get("title") or "").strip()
        if not identificador or not titulo:
            return [], set(), {
                "available": False,
                "error": "Backlog sem id ou title na resposta da API",
            }
        fonte_id = f"backlog:{identificador}"
        campos = (
            ("Status", item.get("status")),
            ("Prioridade", item.get("priority")),
            ("Tipo", item.get("type")),
            ("Responsável", item.get("owner")),
            ("Sprint", item.get("sprint")),
            ("Esforço", item.get("effort")),
            ("Rank", item.get("rank")),
        )
        secoes = [f"# {titulo}"]
        secoes.extend(
            f"{rotulo}: {valor}" for rotulo, valor in campos
            if valor is not None and str(valor).strip()
        )
        descricao = str(item.get("description") or "").strip()
        if descricao:
            secoes.extend(("## Descrição", descricao))
        conteudo = "\n\n".join(secoes).strip()
        presentes.add(fonte_id)
        docs.append(_documento_api(fonte_id, titulo, conteudo, {
            "tipo": "backlog",
            "backlog_id": identificador,
            "project_id": str(item.get("project_id") or ""),
            "status": str(item.get("status") or "todo"),
            "priority": str(item.get("priority") or "medium"),
            "item_type": str(item.get("type") or "feature"),
        }))
    return docs, presentes, estado


def coletar(raiz: Path):
    """Retorna documentos estaveis, IDs presentes e estado de cada raiz."""
    docs = []
    presentes = set()
    adiados = []
    raizes = {}
    agora = time.time()

    for subcaminho, tipo, e_dir in ALVOS:
        alvo = raiz / subcaminho
        estado = {"available": True, "error": None}
        raizes[subcaminho] = estado

        try:
            existe = alvo.exists()
            tipo_correto = alvo.is_dir() if e_dir else alvo.is_file()
            permissao = os.access(alvo, os.R_OK | (os.X_OK if e_dir else 0))
        except OSError as erro:
            existe = tipo_correto = permissao = False
            estado["error"] = str(erro)

        if not existe or not tipo_correto or not permissao:
            estado["available"] = False
            estado["error"] = estado["error"] or "ausente, tipo incorreto ou inacessivel"
            log("root_unavailable", alvo)
            continue

        if e_dir:
            arquivos, erros = _listar_markdown(alvo)
            if erros:
                estado["available"] = False
                estado["error"] = "; ".join(str(e) for e in erros[:3])
                log("root_unavailable", alvo)
        else:
            arquivos = [alvo]

        for arq in arquivos:
            try:
                rel = str(arq.relative_to(raiz))
            except ValueError:
                estado["available"] = False
                estado["error"] = f"arquivo fora da raiz: {arq}"
                log("root_unavailable", alvo)
                continue

            presentes.add(rel)
            conteudo, erro = _arquivo_estavel(arq, agora)
            if erro == "unstable":
                adiados.append(rel)
                log("deferred_unstable_file", rel)
                continue
            if erro is not None:
                estado["available"] = False
                estado["error"] = str(erro)
                log("root_unavailable", alvo)
                continue
            if not conteudo:
                log("empty_file_skipped", rel)
                continue

            docs.append({
                "fonte_id": rel,
                "titulo": extrair_titulo(conteudo, arq),
                "conteudo": conteudo,
                "hash": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
                "metadados": {
                    "tipo": tipo,
                    "arquivo": rel,
                    "linhas": conteudo.count("\n") + 1,
                    "chars": len(conteudo),
                },
            })

    return docs, presentes, adiados, raizes


def extrair_titulo(conteudo: str, arq: Path) -> str:
    for linha in conteudo.splitlines():
        linha = linha.strip()
        if linha.startswith("# "):
            return linha[2:].strip()[:300]
    return arq.stem


def raiz_de_fonte_id(fonte_id: str):
    if fonte_id.startswith("adr:"):
        return ADR_FONTE
    if fonte_id.startswith("knowledge:") or fonte_id.startswith("knowledge/"):
        return KNOWLEDGE_FONTE
    if fonte_id.startswith("backlog:") or fonte_id == "backlog.md":
        return BACKLOG_FONTE
    for subcaminho, _, e_dir in ALVOS:
        if e_dir and (fonte_id == subcaminho or fonte_id.startswith(subcaminho + "/")):
            return subcaminho
        if not e_dir and fonte_id == subcaminho:
            return subcaminho
    return None


# --------------------------------------------------------------------------
# Embedding com retry limitado
# --------------------------------------------------------------------------

def gerar_embedding(texto: str, chave: str) -> list:
    if len(texto) > LIMITE_CHARS:
        log("embedding_input_truncated_chars", len(texto) - LIMITE_CHARS)
        texto = texto[:LIMITE_CHARS]

    total_tentativas = len(RETRY_BACKOFF_SEGUNDOS) + 1
    for tentativa in range(1, total_tentativas + 1):
        log("embedding_attempt", tentativa)
        try:
            resposta = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {chave}",
                    "Content-Type": "application/json",
                },
                json={"model": MODELO, "input": texto},
                timeout=60,
            )
        except requests.RequestException as erro:
            if tentativa == total_tentativas:
                raise RuntimeError(f"OpenAI indisponivel apos {tentativa} tentativas: {erro}") from erro
            espera = RETRY_BACKOFF_SEGUNDOS[tentativa - 1]
            log("embedding_retry_in_seconds", espera)
            time.sleep(espera)
            continue

        if resposta.status_code == 200:
            vetor = resposta.json()["data"][0]["embedding"]
            if len(vetor) != DIMENSOES:
                raise RuntimeError(
                    f"embedding com {len(vetor)} dimensoes, esperado {DIMENSOES}"
                )
            return vetor

        erro = f"OpenAI HTTP {resposta.status_code}: {resposta.text[:300]}"
        if resposta.status_code not in HTTP_TRANSITORIOS or tentativa == total_tentativas:
            raise RuntimeError(erro)
        espera = RETRY_BACKOFF_SEGUNDOS[tentativa - 1]
        log("embedding_retry_in_seconds", espera)
        time.sleep(espera)

    raise RuntimeError("falha inesperada ao gerar embedding")


def vetor_sql(vetor: list) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vetor) + "]"


# --------------------------------------------------------------------------
# Banco (schema ja inicializado; nenhuma DDL na rotina diaria)
# --------------------------------------------------------------------------

SQL_UPSERT = """
INSERT INTO documentos
    (fonte, fonte_id, titulo, conteudo, metadados, embedding, conteudo_hash, atualizado_em)
VALUES
    (%s, %s, %s, %s, %s::jsonb, %s::vector, %s, now())
ON CONFLICT (fonte, fonte_id) WHERE fonte_id IS NOT NULL
DO UPDATE SET
    titulo        = EXCLUDED.titulo,
    conteudo      = EXCLUDED.conteudo,
    metadados     = EXCLUDED.metadados,
    embedding     = EXCLUDED.embedding,
    conteudo_hash = EXCLUDED.conteudo_hash,
    atualizado_em = now()
"""


def estado_atual(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fonte_id, conteudo_hash, embedding IS NULL "
            "FROM documentos WHERE fonte = %s AND fonte_id IS NOT NULL",
            (FONTE,),
        )
        return {
            fid: (None if sem_emb else conteudo_hash)
            for fid, conteudo_hash, sem_emb in cur.fetchall()
        }


def validar_schema(conn) -> None:
    try:
        conn.execute("SELECT conteudo_hash FROM documentos LIMIT 0")
    except psycopg.errors.UndefinedTable as erro:
        raise RuntimeError("schema RAG ausente: tabela documentos nao existe") from erro
    except psycopg.errors.UndefinedColumn as erro:
        raise RuntimeError("schema RAG desatualizado: conteudo_hash nao existe") from erro


# --------------------------------------------------------------------------
# Execucao
# --------------------------------------------------------------------------

def executar(args, metricas: dict) -> int:
    env = carregar_env(ENV_FILE)
    docs, presentes, adiados, raizes = coletar(args.root)
    fontes_api = (
        (ADR_FONTE, coletar_adrs),
        (KNOWLEDGE_FONTE, coletar_knowledge),
        (BACKLOG_FONTE, coletar_backlog),
    )
    for nome_fonte, coletor in fontes_api:
        documentos_api, presentes_api, estado = coletor(env)
        raizes[nome_fonte] = estado
        if estado["available"]:
            docs.extend(documentos_api)
            presentes.update(presentes_api)
        else:
            log("root_unavailable", nome_fonte)
    metricas["documents_seen"] = len(presentes)
    metricas["unstable_files_deferred"] = len(adiados)
    metricas["roots_available"] = sum(1 for r in raizes.values() if r["available"])
    metricas["roots_unavailable"] = len(raizes) - metricas["roots_available"]

    disponiveis = {nome for nome, estado in raizes.items() if estado["available"]}
    indisponiveis = set(raizes) - disponiveis
    for nome in sorted(indisponiveis):
        log("deletion_skipped_for_root", args.root / nome)

    with psycopg.connect(montar_dsn(env)) as conn:
        validar_schema(conn)
        indexado = estado_atual(conn)

        novos = [d for d in docs if d["fonte_id"] not in indexado]
        alterados = [
            d for d in docs
            if d["fonte_id"] in indexado and indexado[d["fonte_id"]] != d["hash"]
        ]
        iguais = [
            d for d in docs
            if d["fonte_id"] in indexado and indexado[d["fonte_id"]] == d["hash"]
        ]

        orfaos = []
        for fonte_id in sorted(set(indexado) - presentes):
            raiz = raiz_de_fonte_id(fonte_id)
            if raiz is None:
                log("deletion_skipped_unknown_root", fonte_id)
            elif raiz in indisponiveis:
                continue
            else:
                orfaos.append(fonte_id)

        metricas["documents_new"] = len(novos)
        metricas["documents_modified"] = len(alterados)
        metricas["documents_unchanged"] = len(iguais)
        log("documents_would_delete", len(orfaos) if not args.no_prune else 0)
        log("embeddings_would_request", len(novos) + len(alterados))

        if args.dry_run:
            conn.rollback()
            log("dry_run", "true")
            return 0

        chave = obter_chave_openai(env) if novos or alterados else None
        for documento in novos + alterados:
            metricas["embeddings_requested"] += 1
            log("embedding_document", documento["fonte_id"])
            try:
                vetor = gerar_embedding(documento["conteudo"], chave)
                with conn.cursor() as cur:
                    cur.execute(SQL_UPSERT, (
                        FONTE,
                        documento["fonte_id"],
                        documento["titulo"],
                        documento["conteudo"],
                        json.dumps(documento["metadados"], ensure_ascii=False),
                        vetor_sql(vetor),
                        documento["hash"],
                    ))
                conn.commit()
                metricas["embeddings_success"] += 1
            except Exception as erro:
                conn.rollback()
                metricas["embeddings_failed"] += 1
                print(
                    f"embedding_error document={documento['fonte_id']} error={erro}",
                    file=sys.stderr,
                    flush=True,
                )

        if orfaos and not args.no_prune and metricas["embeddings_failed"] == 0:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM documentos WHERE fonte = %s AND fonte_id = ANY(%s)",
                    (FONTE, orfaos),
                )
                metricas["documents_deleted"] = cur.rowcount
            conn.commit()
        elif orfaos and metricas["embeddings_failed"]:
            log("deletion_skipped_embedding_failures", len(orfaos))

    return 1 if metricas["embeddings_failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestor RAG WorkDev -> pgvector")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="calcula o plano sem chamar API nem escrever no banco",
    )
    parser.add_argument(
        "--root", type=Path, default=ROOT_PADRAO,
        help=f"raiz da varredura (padrao: {ROOT_PADRAO})",
    )
    parser.add_argument(
        "--no-prune", action="store_true",
        help="nao remove documentos que sumiram do disco",
    )
    args = parser.parse_args()

    inicio = time.monotonic()
    metricas = metricas_vazias()
    log("started_at", agora_iso())
    log("mode", "dry-run" if args.dry_run else "ingest")

    try:
        lock = adquirir_lock()
    except OSError as erro:
        print(f"lock_error={erro}", file=sys.stderr, flush=True)
        emitir_resumo(inicio, metricas, "failure")
        return 1

    if lock is None:
        log("ingestion_skipped", "already_running")
        emitir_resumo(inicio, metricas, "success")
        return 0

    try:
        codigo = executar(args, metricas)
    except Exception as erro:
        print(f"ingestion_error={erro}", file=sys.stderr, flush=True)
        emitir_resumo(inicio, metricas, "failure")
        return 1
    finally:
        lock.close()

    status = "partial_failure" if codigo else "success"
    emitir_resumo(inicio, metricas, status)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
