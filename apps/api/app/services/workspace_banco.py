"""Fatias de banco do Workspace Local (etapa 6 do plano, decisões de 2026-10-25).

O worktree da sessão isola o código, não o dado: aqui a escrita é no Postgres
real do WorkDev. Por isso cada fatia de banco passa por:

1. **Validação do SQL** — um comando só; INSERT, UPDATE ou DELETE numa das
   tabelas de registro (`TABELAS`); UPDATE/DELETE com WHERE; nada de DDL,
   controle de transação, `SET`, cópia de arquivo nem funções de sistema
   (`pg_*`, `lo_*`, `dblink`). O `RETURNING` é nosso, não do modelo.
2. **Simulação** — numa transação: "antes" das linhas, o comando, o "depois",
   as consultas de verificação da fatia e ROLLBACK. Nada fica gravado.
3. **Aplicar** — clique do operador (decisão 2). Refaz na transação e só
   commita se o conjunto de linhas é o mesmo da simulação, o total cabe no
   limite (`MAX_LINHAS`) e a verificação passa. "Antes" e "depois" vão para a
   trilha da sessão.
4. **Reverter** — restaura a partir do "antes"; recusa se a linha mudou depois
   da aplicação (a não ser que o operador force).

O modelo lê só a estrutura das tabelas (`ler_schema`), nunca os dados.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.services.workspace import WorkspaceErro

TABELAS = ("projects", "backlog", "backlog_subtasks", "knowledge", "decisions", "adrs", "rfcs")
MAX_LINHAS = 50
MAX_SQL = 4000
MAX_VERIFICACOES = 5
TIMEOUT_MS = 10_000
VALIDADE_SIMULACAO_S = 900

# Tipo do nó no Engineering Graph e relação com o pai, como os routers fazem.
GRAFO = {"adrs": ("ADR", "LINKED_TO_ADR"), "rfcs": ("RFC", "LINKED_TO_RFC"),
         "decisions": ("Decision", "HAS_DECISION"), "knowledge": ("Knowledge", "LINKED_TO_KNOWLEDGE")}

# SET/RESET não entram: o comando é um só e começa por INSERT/UPDATE/DELETE, então
# um SET solto não tem como aparecer — e o do UPDATE ... SET é legítimo.
_PROIBIDAS = re.compile(
    r"\b(create|alter|drop|truncate|grant|revoke|copy|vacuum|analyze|cluster|reindex|"
    r"do|call|execute|prepare|deallocate|listen|notify|unlisten|lock|comment|"
    r"security|begin|commit|rollback|savepoint|release|start|abort|returning|into\s+outfile)\b",
    re.IGNORECASE)
_FUNCOES_PROIBIDAS = re.compile(r"\b(pg_\w+|lo_\w+|dblink\w*|set_config|current_setting|query_to_xml\w*)\s*\(",
                                re.IGNORECASE)
_ALVO = re.compile(r"^\s*(insert\s+into|update|delete\s+from)\s+(?:public\.)?\"?([a-z_]+)\"?", re.IGNORECASE)


def _engine() -> Engine:
    from app.database import engine
    return engine


# ---------------------------------------------------------------- validação

def _sem_literais(sql: str) -> str:
    """Tira strings e identificadores entre aspas, para as checagens não olharem dentro deles."""
    return re.sub(r"'(?:[^']|'')*'", "''", re.sub(r'"(?:[^"]|"")*"', '""', sql))


def validar_sql(sql: str, tabelas: list[str] | None = None) -> dict:
    """{"comando", "tabela", "sql"} ou WorkspaceErro 422 com o motivo."""
    if not isinstance(sql, str) or not sql.strip():
        raise WorkspaceErro(422, "sql_vazio", "a fatia não trouxe SQL")
    sql = sql.strip().rstrip(";").strip()
    if len(sql) > MAX_SQL:
        raise WorkspaceErro(422, "sql_longo", f"SQL acima de {MAX_SQL} caracteres")
    limpo = _sem_literais(sql)
    if "--" in limpo or "/*" in limpo:
        raise WorkspaceErro(422, "sql_com_comentario", "SQL com comentário não é aceito; mande só o comando")
    if ";" in limpo:
        raise WorkspaceErro(422, "sql_multiplo", "um comando por fatia")
    alvo = _ALVO.match(limpo)
    if not alvo:
        raise WorkspaceErro(422, "sql_nao_permitido",
                            "só INSERT, UPDATE ou DELETE; mudança de estrutura vira fatia de código com migration")
    comando = alvo.group(1).split()[0].upper()
    tabela = alvo.group(2).lower()
    permitidas = [t for t in (tabelas or TABELAS) if t in TABELAS]
    if tabela not in permitidas:
        raise WorkspaceErro(422, "tabela_nao_permitida",
                            f"tabela '{tabela}' fora das liberadas: {', '.join(permitidas)}")
    proibida = _PROIBIDAS.search(limpo)
    if proibida:
        raise WorkspaceErro(422, "sql_nao_permitido", f"palavra não permitida no SQL: {proibida.group(1).upper()}")
    funcao = _FUNCOES_PROIBIDAS.search(limpo)
    if funcao:
        raise WorkspaceErro(422, "funcao_proibida", f"função não permitida: {funcao.group(1)}")
    if comando in ("UPDATE", "DELETE") and not re.search(r"\bwhere\b", limpo, re.IGNORECASE):
        raise WorkspaceErro(422, "sem_where", f"{comando} sem WHERE não é aceito")
    return {"comando": comando, "tabela": tabela, "sql": sql}


def validar_verificacao(consulta: str) -> str:
    if not isinstance(consulta, str) or not consulta.strip():
        raise WorkspaceErro(422, "verificacao_vazia", "verificação vazia")
    consulta = consulta.strip().rstrip(";").strip()
    limpo = _sem_literais(consulta)
    if not re.match(r"^\s*select\b", limpo, re.IGNORECASE) or ";" in limpo or "--" in limpo or "/*" in limpo:
        raise WorkspaceErro(422, "verificacao_invalida", f"verificação precisa ser um SELECT só: {consulta[:120]}")
    if re.search(r"\b(insert|update|delete|merge)\b", limpo, re.IGNORECASE) or _PROIBIDAS.search(limpo) \
            or _FUNCOES_PROIBIDAS.search(limpo):
        raise WorkspaceErro(422, "verificacao_invalida", f"verificação só lê: {consulta[:120]}")
    return consulta


# ---------------------------------------------------------------- schema (para o modelo)

def ler_schema(tabela: str) -> dict:
    """Colunas, tipos e chaves de uma tabela liberada. Nunca linhas."""
    tabela = (tabela or "").strip().lower()
    if tabela not in TABELAS:
        raise WorkspaceErro(422, "tabela_nao_permitida", f"tabelas liberadas: {', '.join(TABELAS)}")
    inspetor = inspect(_engine())
    colunas = [{"nome": c["name"], "tipo": str(c["type"]), "nulo": bool(c.get("nullable")),
                "padrao": str(c["default"]) if c.get("default") is not None else None}
               for c in inspetor.get_columns(tabela)]
    estrangeiras = [{"colunas": f["constrained_columns"], "referencia": f["referred_table"]}
                    for f in inspetor.get_foreign_keys(tabela)]
    return {"tabela": tabela, "colunas": colunas, "chaves_estrangeiras": estrangeiras}


# ---------------------------------------------------------------- execução

def _json(valor):
    if isinstance(valor, (uuid.UUID, Decimal)):
        return str(valor)
    if isinstance(valor, (datetime, date, dtime)):
        return valor.isoformat()
    if isinstance(valor, (bytes, memoryview)):
        return None
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    return valor


def _linha(row) -> dict:
    return {k: _json(v) for k, v in row._mapping.items()}


def _rodar(conexao, validado: dict, verificacoes: list[str]) -> dict:
    """Executa o comando dentro da transação já aberta e devolve o resultado (sem commit)."""
    if conexao.dialect.name == "postgresql":
        conexao.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
        conexao.execute(text(f"SET LOCAL lock_timeout = {TIMEOUT_MS}"))
    tabela = validado["tabela"]
    antes_por_id = {}
    if validado["comando"] == "UPDATE":
        # Tabelas de registro são pequenas: o "antes" é a tabela lida dentro da transação.
        antes_por_id = {str(r["id"]): r for r in (_linha(x) for x in conexao.execute(text(f'SELECT * FROM "{tabela}"')))}
    afetadas = [_linha(r) for r in conexao.execute(text(validado["sql"] + " RETURNING *"))]
    ids = [str(r["id"]) for r in afetadas]
    if validado["comando"] == "DELETE":
        antes, depois = afetadas, []
    elif validado["comando"] == "UPDATE":
        antes, depois = [antes_por_id[i] for i in ids if i in antes_por_id], afetadas
    else:
        antes, depois = [], afetadas
    resultados = []
    for consulta in verificacoes:
        try:
            linha = conexao.execute(text(consulta)).first()
            valor = linha[0] if linha is not None else None
            resultados.append({"consulta": consulta, "passou": bool(valor), "valor": _json(valor)})
        except Exception as erro:  # noqa: BLE001 — erro de verificação vira reprovação, não exceção
            resultados.append({"consulta": consulta, "passou": False, "valor": None,
                               "erro": f"{type(erro).__name__}: {str(erro).splitlines()[0][:300]}"})
            break
    return {"comando": validado["comando"], "tabela": tabela, "ids": ids, "linhas": len(ids),
            "antes": antes, "depois": depois, "verificacoes": resultados}


def _hash(sql: str, verificacoes: list[str]) -> str:
    return hashlib.sha256(json.dumps([sql, verificacoes]).encode()).hexdigest()


def simular(sql: str, verificacoes: list[str], tabelas: list[str] | None = None) -> dict:
    """Roda tudo numa transação e desfaz. Nunca grava."""
    validado = validar_sql(sql, tabelas)
    verificacoes = [validar_verificacao(v) for v in verificacoes or []][:MAX_VERIFICACOES]
    if not verificacoes:
        raise WorkspaceErro(422, "sem_verificacao", "a fatia de banco precisa de pelo menos uma verificação (SELECT)")
    with _engine().connect() as conexao:
        transacao = conexao.begin()
        try:
            resultado = _rodar(conexao, validado, verificacoes)
        except Exception as erro:  # noqa: BLE001 — erro do banco volta como motivo
            transacao.rollback()
            raise WorkspaceErro(422, "sql_falhou", f"o banco recusou: {str(erro).splitlines()[0][:500]}") from erro
        transacao.rollback()
    resultado.update(sql=validado["sql"], hash=_hash(validado["sql"], verificacoes),
                     simulado_em=datetime.now().timestamp(), passou=_passou(resultado))
    return resultado


def _passou(resultado: dict) -> bool:
    return (0 < resultado["linhas"] <= MAX_LINHAS) and all(v["passou"] for v in resultado["verificacoes"])


def aplicar(simulacao: dict, verificacoes: list[str], tabelas: list[str] | None = None) -> dict:
    """Refaz a simulação aprovada e commita só se nada mudou desde ela."""
    if not simulacao or not simulacao.get("passou"):
        raise WorkspaceErro(409, "simulacao_reprovada", "simule (e passe na verificação) antes de aplicar")
    if datetime.now().timestamp() - simulacao["simulado_em"] > VALIDADE_SIMULACAO_S:
        raise WorkspaceErro(409, "simulacao_vencida", "a simulação tem mais de 15 min; simule de novo")
    validado = validar_sql(simulacao["sql"], tabelas)
    verificacoes = [validar_verificacao(v) for v in verificacoes][:MAX_VERIFICACOES]
    if _hash(validado["sql"], verificacoes) != simulacao["hash"]:
        raise WorkspaceErro(409, "simulacao_diferente", "o SQL ou a verificação mudou desde a simulação; simule de novo")
    with _engine().connect() as conexao:
        transacao = conexao.begin()
        try:
            resultado = _rodar(conexao, validado, verificacoes)
        except Exception as erro:  # noqa: BLE001
            transacao.rollback()
            raise WorkspaceErro(422, "sql_falhou", f"o banco recusou: {str(erro).splitlines()[0][:500]}") from erro
        if resultado["linhas"] > MAX_LINHAS:
            transacao.rollback()
            raise WorkspaceErro(409, "linhas_demais", f"{resultado['linhas']} linhas; o limite é {MAX_LINHAS}")
        if validado["comando"] != "INSERT" and sorted(resultado["ids"]) != sorted(simulacao["ids"]):
            transacao.rollback()
            raise WorkspaceErro(409, "linhas_mudaram",
                                f"o comando agora pega {resultado['linhas']} linha(s), diferentes das "
                                f"{simulacao['linhas']} da simulação; nada foi gravado — simule de novo")
        if validado["comando"] == "INSERT" and resultado["linhas"] != simulacao["linhas"]:
            transacao.rollback()
            raise WorkspaceErro(409, "linhas_mudaram", "o INSERT agora gera outro número de linhas; simule de novo")
        if not all(v["passou"] for v in resultado["verificacoes"]):
            transacao.rollback()
            raise WorkspaceErro(409, "verificacao_reprovada", "a verificação não passou na aplicação; nada foi gravado")
        transacao.commit()
    resultado.update(sql=validado["sql"], aplicado_em=datetime.now().isoformat(timespec="seconds"))
    return resultado


# ---------------------------------------------------------------- reverter

def _tipos(tabela: str) -> dict:
    return {c["name"]: c["type"] for c in inspect(_engine()).get_columns(tabela)}


def _valor(coluna: str, valor, tipos: dict, dialeto) -> tuple[str, object]:
    """Placeholder com CAST para o tipo real da coluna (o "antes" foi guardado como JSON)."""
    tipo = tipos[coluna]
    nome = str(tipo).upper()
    if isinstance(valor, (dict, list)) and "JSON" in nome:
        valor = json.dumps(valor)
    if dialeto.name != "postgresql" or valor is None:
        return f":{coluna}", valor
    return f"CAST(:{coluna} AS {tipo.compile(dialect=dialeto)})", valor


def reverter(aplicacao: dict, forcar: bool = False) -> dict:
    """Desfaz uma aplicação a partir do "antes" e do "depois" gravados."""
    tabela, comando = aplicacao["tabela"], aplicacao["comando"]
    if tabela not in TABELAS:
        raise WorkspaceErro(422, "tabela_nao_permitida", tabela)
    tipos = _tipos(tabela)
    depois_por_id = {str(r["id"]): r for r in aplicacao["depois"]}
    with _engine().connect() as conexao:
        transacao = conexao.begin()
        try:
            dialeto = conexao.dialect
            ids = aplicacao["ids"]
            atuais = {}
            if ids:
                marcadores = ", ".join(f":i{n}" for n in range(len(ids)))
                id_sql = 'CAST("id" AS TEXT)' if dialeto.name == "postgresql" else '"id"'
                atuais = {str(r["id"]): r for r in (_linha(x) for x in conexao.execute(
                    text(f'SELECT * FROM "{tabela}" WHERE {id_sql} IN ({marcadores})'),
                    {f"i{n}": i for n, i in enumerate(ids)}))}
            if not forcar:
                if comando == "DELETE":
                    voltaram = [i for i in ids if i in atuais]
                    if voltaram:
                        raise WorkspaceErro(409, "linha_existe", f"{len(voltaram)} linha(s) já existem de novo; nada foi revertido")
                else:
                    mudaram = [i for i in ids if atuais.get(i) != depois_por_id.get(i)]
                    if mudaram:
                        raise WorkspaceErro(409, "linha_mudou",
                                            f"{len(mudaram)} linha(s) mudaram depois da aplicação; nada foi revertido "
                                            "(reverter por cima apagaria essa mudança)")
            if comando == "INSERT":
                for i in ids:
                    conexao.execute(text(f'DELETE FROM "{tabela}" WHERE "id" = {_valor("id", i, tipos, dialeto)[0]}'), {"id": i})
            elif comando == "DELETE":
                for linha in aplicacao["antes"]:
                    colunas = [c for c in linha if c in tipos]
                    partes = [_valor(c, linha[c], tipos, dialeto) for c in colunas]
                    conexao.execute(text(f'INSERT INTO "{tabela}" ({", ".join(chr(34) + c + chr(34) for c in colunas)}) '
                                         f'VALUES ({", ".join(p[0] for p in partes)})'),
                                    {c: p[1] for c, p in zip(colunas, partes)})
            else:
                for linha in aplicacao["antes"]:
                    colunas = [c for c in linha if c in tipos and c != "id"]
                    partes = {c: _valor(c, linha[c], tipos, dialeto) for c in colunas}
                    id_placeholder, id_valor = _valor("id", linha["id"], tipos, dialeto)
                    conexao.execute(text(f'UPDATE "{tabela}" SET {", ".join(chr(34) + c + chr(34) + " = " + partes[c][0] for c in colunas)} '
                                         f'WHERE "id" = {id_placeholder}'),
                                    {**{c: p[1] for c, p in partes.items()}, "id": id_valor})
        except WorkspaceErro:
            transacao.rollback()
            raise
        except Exception as erro:  # noqa: BLE001
            transacao.rollback()
            raise WorkspaceErro(422, "reversao_falhou", f"o banco recusou a reversão: {str(erro).splitlines()[0][:500]}") from erro
        transacao.commit()
    return {"tabela": tabela, "comando": comando, "linhas": len(aplicacao["ids"]),
            "revertido_em": datetime.now().isoformat(timespec="seconds"), "forcado": forcar}


# ---------------------------------------------------------------- grafo

def sincronizar_grafo(aplicacao: dict) -> None:
    """INSERT cria o nó no Engineering Graph, como os routers fazem. Falha não derruba nada."""
    if aplicacao["comando"] != "INSERT":
        return
    import threading

    from app.services.engineering_graph import graph_sync
    tabela = aplicacao["tabela"]
    for linha in aplicacao["depois"]:
        if tabela == "projects":
            args = ("sync_project", linha["id"])
        elif tabela == "backlog":
            args = ("sync_backlog", linha["id"], linha.get("project_id"), linha.get("type") or "feature")
        elif tabela in GRAFO and linha.get("project_id"):
            tipo, relacao = GRAFO[tabela]
            args = ("sync_related", tipo, linha["id"], linha["project_id"], relacao)
        else:
            continue  # subtask sem project_id na linha: o nó nasce no próximo sync completo
        threading.Thread(target=graph_sync.sync_safely, args=args, daemon=True).start()


def trilha(pasta: Path, ident: str, n: int, acao: str, dados: dict) -> Path:
    """Grava o registro de uma ação de banco da sessão; é dele que o reverter lê."""
    destino = pasta / f"{ident}-banco"
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"fatia{n:02d}-{acao}-{datetime.now():%Y%m%d-%H%M%S}.json"
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return arquivo
