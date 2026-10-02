"""Planejador da Bancada Local: lê contexto e chama OpenRouter para gerar micro-tarefas.

Recebe task_id do backlog OU prompt livre. Lê CLAUDE.md + backlog recente,
monta prompt no padrão de `prompt-planejador.md` e chama OpenRouter.
Valida JSON e regras de tarefa antes de devolver.

A chave OpenRouter é lida do arquivo de ambiente, nunca impressa.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parent.parent
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_FILES = (Path("/etc/workdev/workdev-api.env"),)
MODELO_PADRAO = "deepseek/deepseek-v4-flash"
MAX_TOKENS_SAIDA = 4000
TIMEOUT = 120

ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_TRECHOS = 8
MAX_LINHAS_TRECHO = 400
MAX_INSTRUCAO = 8000


class PlanejadorErro(Exception):
    """Erro controlado do planejador."""
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _ler_chave_openrouter() -> str:
    """Lê OPENROUTER_API_KEY do arquivo de ambiente, nunca exibe."""
    valor = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if valor:
        return valor
    for arquivo in OPENROUTER_FILES:
        try:
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if linha.startswith("OPENROUTER_API_KEY="):
                    return linha.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            continue
    raise PlanejadorErro("sem_chave", "OPENROUTER_API_KEY não encontrada")


def _ler_claude_md() -> str:
    """Lê /opt/workdev/CLAUDE.md inteiro (contexto do projeto)."""
    try:
        return (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _ler_backlog_recente(limite: int = 50) -> list[dict]:
    """Lê as últimas N tasks abertas do backlog do Postgres.

    Conecta ao banco via DATABASE_URL no env do serviço e retorna
    [{"id": "uuid", "title": str, "description": str, ...}]
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return []

    # Tenta usar psycopg3 se disponível; senão, return vazio (não é crítico)
    try:
        import psycopg
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, description FROM tasks WHERE status IN ('todo', 'in_progress') "
                    "ORDER BY created_at DESC LIMIT %s",
                    (limite,)
                )
                return [
                    {"id": row[0], "title": row[1], "description": row[2]}
                    for row in cur.fetchall()
                ]
    except Exception:
        # Se falhar (psycopg não instalado, banco indisponível, etc), retorna vazio
        # Não interrompe o fluxo — o planejador continua com só CLAUDE.md
        return []


def _montar_contexto(tarefa_id: str | None, prompt_livre: str | None) -> tuple[str, str]:
    """Monta o contexto completo para o planejador.

    Se tarefa_id: lê a task específica do backlog + CLAUDE.md.
    Se prompt_livre: usa o prompt direto.

    Retorna (contexto_resumido_para_prompt, contexto_completo_para_referencia)
    """
    claude_md = _ler_claude_md()
    backlog = _ler_backlog_recente(50)

    if tarefa_id:
        tarefa = next((t for t in backlog if str(t["id"]).startswith(tarefa_id[:8])), None)
        if not tarefa:
            raise PlanejadorErro("tarefa_nao_encontrada", f"Task {tarefa_id} não encontrada no backlog")
        resumo = f"Task: {tarefa['title']}\n{tarefa.get('description', '')}"
    else:
        resumo = prompt_livre or ""

    # Contexto: CLAUDE.md (linhas 1-100) + resumo + backlog resumido
    claude_linhas = claude_md.split("\n")[:100]
    backlog_resumo = "\n".join(f"- [{t['id'][:8]}] {t['title']}" for t in backlog[:10])

    contexto_curto = f"""## Contexto do WorkDev

{chr(10).join(claude_linhas)}

## Tarefa ou pedido

{resumo}

## Backlog recente (referência)
{backlog_resumo}
"""
    return contexto_curto, claude_md


def _montar_prompt_planejador(contexto: str) -> str:
    """Monta o prompt no padrão de docs/bancada-local/prompt-planejador.md."""
    return f"""Você é o planejador da Bancada Local do WorkDev. Vai quebrar o pedido abaixo em
micro-tarefas para um modelo local pequeno (Qwen ~30B MoE, contexto curto, sem
ferramentas). O modelo local NÃO lê arquivos: ele só vê os trechos que você
indicar, com número de linha. Ele inventa nomes com facilidade quando o
contexto não traz o que precisa.

Regras de cada micro-tarefa:
- Uma ação só: um diff pequeno, uma docstring, um teste, um resumo, uma lista.
  Nada de "refatore o módulo".
- Trechos mínimos e suficientes: inclua a definição de TODO nome que a resposta
  vai precisar usar (função, constante, import). Se o diff mexe em X e chama Y,
  o trecho de Y também entra. Na dúvida, inclua o bloco de imports do arquivo.
- Linhas reais do arquivo atual, [caminho relativo à raiz do repo, início, fim],
  inclusivas. No máximo 8 trechos e 400 linhas por trecho; prefira bem menos.
- Nunca use .env, .git, chaves, certificados, node_modules ou caminhos fora do
  repo: a Bancada recusa.
- Instrução autocontida e explícita sobre o formato de saída. Para mudança de
  código: "Saída: diff unificado (--- a/… +++ b/…) contra os trechos, e nada
  mais." Para análise: diga o formato (lista, JSON com chaves X/Y).
- Sempre inclua na instrução: "Use só nomes que aparecem nos trechos. Se faltar
  algo, responda FALTA: <o que falta> em vez de inventar."
- espera_diff: true quando a saída esperada é um diff. As checagens rodam
  `git apply --check` contra a base e acusam erro se não vier diff.
- exige: até 5 pares {{regex: explicação}} com o essencial que a resposta precisa
  ACRESCENTAR (ex.: {{"current\\\\(\\\\)": "usar current() para ler a chave"}}).
  É expressão regular Python, procurada só no código NOVO: linhas "+" do diff
  (ou blocos de código, se não houver diff). Linha de contexto não conta — não use
  exige para "manter X"; para remoções puras, omita. Escape parênteses e pontos.
  Até 200 caracteres cada. Use só para o que é inequívoco.
- max_tokens: o suficiente para a saída, entre 64 e 4000 (diff pequeno ~400-800,
  teste ~800-1500, resumo ~300-600).
- id: único, só letras, números, _ e -, até 80 caracteres, descritivo
  (ex.: "docstring_load_subtasks").
- Ordene as tarefas para que cada uma seja independente: o modelo local não vê
  a resposta das anteriores.
- Se o pedido não cabe em micro-tarefas (precisa de muitos arquivos, decisão de
  arquitetura, migração de banco), NÃO force: devolva {{"tarefas": [],
  "fora_do_alcance": "<motivo>"}}.

Responda APENAS com JSON válido, sem texto antes ou depois:
{{"tarefas": [ {{"id": "...", "instrucao": "...", "trechos": [["caminho", ini, fim]],
               "max_tokens": 800, "espera_diff": true, "exige": {{"regex": "explicação"}}}} ]}}

## Contexto e pedido

{contexto}
"""


def validar_tarefas(dados: dict | list) -> list[dict]:
    """Valida o JSON retornado: formato, IDs, regras de tarefa.

    Retorna lista de tarefas válidas ou levanta PlanejadorErro.
    """
    if isinstance(dados, dict):
        tarefas = dados.get("tarefas", [])
    elif isinstance(dados, list):
        tarefas = dados
    else:
        raise PlanejadorErro("formato_invalido", "resposta não é dict ou list")

    if not isinstance(tarefas, list):
        raise PlanejadorErro("tarefas_invalido", "campo 'tarefas' não é array")

    if not tarefas:
        raise PlanejadorErro("tarefas_vazio", "nenhuma tarefa retornada")

    validas = []
    ids_vistos = set()

    for i, tarefa in enumerate(tarefas):
        if not isinstance(tarefa, dict):
            raise PlanejadorErro("tarefa_invalida", f"tarefa {i} não é dict")

        tid = str(tarefa.get("id", "")).strip()
        if not ID_VALIDO.match(tid):
            raise PlanejadorErro("id_invalido", f"tarefa {i}: id={tid!r} inválido")

        if tid in ids_vistos:
            raise PlanejadorErro("id_duplicado", f"tarefa {i}: id={tid} duplicado")
        ids_vistos.add(tid)

        instrucao = str(tarefa.get("instrucao", "")).strip()
        if not instrucao or len(instrucao) > MAX_INSTRUCAO:
            raise PlanejadorErro("instrucao_invalida", f"tarefa {tid}: instrução vazia ou > 8000 chars")

        trechos = tarefa.get("trechos") or []
        if not isinstance(trechos, list) or len(trechos) > MAX_TRECHOS:
            raise PlanejadorErro("trechos_invalidos", f"tarefa {tid}: não é array ou > 8 trechos")

        # Valida cada trecho (não lê arquivo, só confere formato)
        for j, trecho in enumerate(trechos):
            if not isinstance(trecho, (list, tuple)) or len(trecho) != 3:
                raise PlanejadorErro("trecho_invalido", f"tarefa {tid}, trecho {j}: não é [caminho, ini, fim]")
            caminho, ini, fim = trecho
            if not isinstance(caminho, str) or not caminho.strip():
                raise PlanejadorErro("caminho_invalido", f"tarefa {tid}, trecho {j}: caminho vazio")
            if not isinstance(ini, int) or not isinstance(fim, int) or ini < 1 or fim < ini:
                raise PlanejadorErro("intervalo_invalido", f"tarefa {tid}, trecho {j}: intervalo inválido")
            if fim - ini + 1 > MAX_LINHAS_TRECHO:
                raise PlanejadorErro("trecho_longo", f"tarefa {tid}, trecho {j}: > 400 linhas")

        max_tokens = int(tarefa.get("max_tokens") or 1024)
        if not (64 <= max_tokens <= 4000):
            raise PlanejadorErro("max_tokens_invalido", f"tarefa {tid}: fora de [64, 4000]")

        validas.append({
            "id": tid,
            "instrucao": instrucao,
            "trechos": [[str(c).strip(), int(i), int(f)] for c, i, f in trechos],
            "max_tokens": max_tokens,
            "espera_diff": bool(tarefa.get("espera_diff", False)),
            "exige": tarefa.get("exige") or {}
        })

    return validas


def _stream_openrouter(prompt: str, modelo: str) -> Iterator[dict]:
    """Chama OpenRouter e faz stream de tokens.

    Yield: {"tipo": "token", "texto": str} | {"tipo": "fim", "completo": str, "tokens": int}
    """
    corpo = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS_SAIDA,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True}
    }

    chave = _ler_chave_openrouter()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(corpo).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {chave}",
            "X-Title": "WorkDev Bancada Planejador"
        },
        method="POST"
    )

    texto_completo = ""
    tokens = None

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resposta:
            for linha in resposta:
                linha = linha.decode("utf-8", "replace").strip()
                if not linha.startswith("data:"):
                    continue
                dado = linha[5:].strip()
                if dado == "[DONE]":
                    break
                try:
                    pedaco = json.loads(dado)
                    tokens = (pedaco.get("usage") or {}).get("completion_tokens", tokens)
                    delta = ((pedaco.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                    if delta:
                        texto_completo += delta
                        yield {"tipo": "token", "texto": delta}
                except ValueError:
                    pass
    except urllib.error.HTTPError as e:
        raise PlanejadorErro("erro_openrouter", f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    except urllib.error.URLError as e:
        raise PlanejadorErro("erro_rede", str(e))

    yield {"tipo": "fim", "completo": texto_completo, "tokens": tokens}


def planejar_stream(tarefa_id: str | None, prompt_livre: str | None, modelo: str = MODELO_PADRAO) -> Iterator[dict]:
    """Orquestra o planejamento: contexto → prompt → OpenRouter → validação.

    Yield:
    - {"tipo": "contexto", "resumo": str}
    - {"tipo": "token", "texto": str}  # do streaming
    - {"tipo": "validando", "texto_completo": str}
    - {"tipo": "ok", "tarefas": [...], "tokens": int}
    - {"tipo": "erro", "codigo": str, "mensagem": str}
    """
    try:
        if not tarefa_id and not prompt_livre:
            raise PlanejadorErro("entrada_vazia", "forneça task_id ou prompt")

        # Lê contexto
        try:
            contexto, _ = _montar_contexto(tarefa_id, prompt_livre)
        except PlanejadorErro as e:
            yield {"tipo": "erro", "codigo": e.codigo, "mensagem": e.mensagem}
            return

        yield {"tipo": "contexto", "resumo": contexto[:500]}  # primeiros 500 chars

        # Monta prompt e chama OpenRouter
        prompt_planejador = _montar_prompt_planejador(contexto)
        texto_completo = ""
        tokens = None

        for evento in _stream_openrouter(prompt_planejador, modelo):
            if evento["tipo"] == "token":
                texto_completo += evento["texto"]
                yield evento
            elif evento["tipo"] == "fim":
                tokens = evento["tokens"]
                break

        yield {"tipo": "validando", "tokens": tokens}

        # Valida JSON e regras
        try:
            dados = json.loads(texto_completo)
        except json.JSONDecodeError as e:
            raise PlanejadorErro("json_invalido", f"JSON malformado: {str(e)[:200]}")

        tarefas = validar_tarefas(dados)

        yield {"tipo": "ok", "tarefas": tarefas, "tokens": tokens}

    except PlanejadorErro as e:
        yield {"tipo": "erro", "codigo": e.codigo, "mensagem": e.mensagem}
    except Exception as e:
        yield {"tipo": "erro", "codigo": "erro_interno", "mensagem": f"{type(e).__name__}: {e}"}
