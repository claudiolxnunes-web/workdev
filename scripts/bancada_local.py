#!/usr/bin/env python3
"""Bancada Local: usa o llama-server (127.0.0.1:8080) fora do harness do CLI qwen.

Toda saída é PROPOSTA. Este script nunca aplica patch no repositório, nunca roda
shell e nunca escreve nele — só grava em tmp/bancada/. O `verificar` só lê a base
com `git archive` e testa o patch numa cópia em tmp/bancada/_trabalho/.
Não lê .env do repositório nem usa a WORKDEV_API_KEY; só o observer lê a
OPENROUTER_API_KEY do arquivo de ambiente do serviço, sem exibir.

Subcomandos:
  rodar tarefas.json [--stream]      executa as tarefas; --stream mostra token a token e
                                     interrompe/reenvia 1 vez se citar símbolo inexistente;
                                     pula id que já tem proposta (--sobrescrever refaz)
  planejar "<task>"                  o modelo local fatia a task em tmp/bancada/planos/<lote>.json
  ferramentas "<pergunta>"           exploração somente leitura com function calling
  broker "<pergunta>"                o modelo pede LER/PROCURAR por texto; o broker só lê
  verificar --caso <id>              checagens mecânicas (git apply na base, símbolos, imports)
  observar <caso> --observer <slug>  checagens + parecer de um observer via OpenRouter
  comparar [--observers ...]         mesmas entradas em vários observers -> comparativo
  avaliar <id> <veredito> [nota]     registra o aproveitamento em registro.jsonl
  extrair <id>                       grava o diff da proposta em tmp/bancada/patches/<id>.patch
                                     e roda git apply --recount --check (nunca aplica)
  resumo                             aproveitamento por modelo e por quem avaliou

Observer e comparar usam a OPENROUTER_API_KEY do WorkDev (lida do arquivo de
ambiente, nunca exibida). O modelo local nunca lê arquivos nem aplica nada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAIDA = REPO / "tmp" / "bancada"
REGISTRO = SAIDA / "registro.jsonl"
KEY_FILE = Path("/var/lib/workdev-llama/model")
URL_PADRAO = os.environ.get("BANCADA_URL", "http://127.0.0.1:8080")
ALIAS = "workdev-qwen"

BLOQUEADOS = (".env", ".git", "secret", ".key", ".pem", "node_modules",
              "credential", "id_rsa", "id_ed25519", ".p12", ".pfx")
# Pastas enormes ou sem interesse que a busca nem percorre.
PULAR_NA_BUSCA = {"venv", ".venv", "__pycache__", "dist", "build"}
LIMITE_FERRAMENTA = 6000
MAX_VOLTAS = 10
VEREDITOS = ("aproveitada", "correcao_pequena", "descartada")
ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
# Ids que o planejador costuma devolver sem significado: "1", "t1", "tarefa1".
ID_GENERICO = re.compile(r"^(?:\d+|t[-_]?\d+|tarefa[-_]?\d+)$", re.IGNORECASE)
# Um lote por plano: AAMMDD-NN, numerado pelo próximo livre em tmp/bancada/planos/.
LOTE = re.compile(r"^(\d{6})-(\d{2,})$")


def proximo_lote(pasta_planos: Path, hoje: str | None = None) -> str:
    """Retorna o id do próximo lote no formato AAMMDD-NN.

    AAMMDD = ano (2 dígitos), mês (2 dígitos), dia (2 dígitos).
    NN = número sequencial com pelo menos 2 dígitos (ex.: 260101-01).

    O parâmetro opcional `hoje` é uma string no formato "yymmdd" que força a data;
    quando None (padrão), usa a data atual via datetime.now().

    Se `pasta_planos` não existir ou não for um diretório, o glob não itera
    (lista vazia) e a função retorna sempre "AAMMDD-01" (sequencial 1).
    A função NÃO cria a pasta.
    """
    hoje = hoje or datetime.now().strftime("%y%m%d")
    usados = [int(m.group(2)) for p in (pasta_planos.glob(f"{hoje}-*.json") if pasta_planos.is_dir() else [])
              if (m := LOTE.match(p.stem)) and m.group(1) == hoje]
    return f"{hoje}-{max(usados, default=0) + 1:02d}"


class Recusado(Exception):
    pass


# ---------------------------------------------------------------- caminhos

def caminho_seguro(relativo: str, raiz: Path | None = None) -> Path:
    """Resolve com realpath e recusa o que sai da raiz ou bate na lista negra."""
    raiz = raiz or REPO
    if not isinstance(relativo, str) or not relativo.strip():
        raise Recusado("caminho vazio")
    bruto = relativo.strip()
    alvo = Path(os.path.realpath(raiz / bruto))
    if alvo != raiz and raiz not in alvo.parents:
        raise Recusado(f"fora do repositório: {bruto}")
    rel = alvo.relative_to(raiz).as_posix().lower()
    # Confere o pedido e o destino real (um symlink não pode disfarçar o nome).
    for texto in (bruto.lower(), rel):
        for proibido in BLOQUEADOS:
            if proibido in texto:
                raise Recusado(f"caminho bloqueado ({proibido}): {bruto}")
    return alvo


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix() or "."


def cortar(texto: str, limite: int = LIMITE_FERRAMENTA) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n[... cortado: {len(texto) - limite} caracteres omitidos]"


def ler_linhas(path: str, inicio: int, fim: int) -> tuple[Path, list[str], int, int]:
    alvo = caminho_seguro(path)
    if not alvo.is_file():
        raise Recusado(f"não é arquivo: {path}")
    linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    inicio = max(1, int(inicio))
    fim = min(len(linhas), int(fim))
    if fim < inicio:
        raise Recusado(f"intervalo vazio {inicio}-{fim} em {path} ({len(linhas)} linhas)")
    return alvo, linhas[inicio - 1:fim], inicio, fim


# ---------------------------------------------------------------- servidor

def modelo_ativo() -> str:
    """Mesma normalização do wrapper workdev-llama-run."""
    try:
        bruto = KEY_FILE.read_bytes()[:32].decode("ascii", "ignore")
    except OSError:
        return "desconhecido"
    chave = "".join(c for c in bruto if c.isascii() and (c.islower() or c.isdigit()))
    return chave or "desconhecido"


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=5) as r:
            return json.loads(r.read() or b"{}").get("status") == "ok"
    except (OSError, ValueError):
        return False


def chat(url: str, corpo: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url + "/v1/chat/completions",
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def corpo_base(mensagens: list, max_tokens: int, thinking: bool) -> dict:
    return {
        "model": ALIAS,
        "messages": mensagens,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": bool(thinking)},
    }


def pasta_modelo(chave: str) -> Path:
    destino = SAIDA / (chave if ID_VALIDO.match(chave) else "desconhecido")
    destino.mkdir(parents=True, exist_ok=True)
    return destino


# ---------------------------------------------------------------- rodar

def montar_prompt(tarefa: dict) -> str:
    partes = [str(tarefa["instrucao"]).strip()]
    for trecho in tarefa.get("trechos") or []:
        caminho, ini, fim = trecho
        _, linhas, ini, fim = ler_linhas(caminho, ini, fim)
        partes.append(f"### {caminho} (linhas {ini}-{fim})\n```\n" + "\n".join(linhas) + "\n```")
    return "\n\n".join(partes)


def cmd_rodar(args) -> int:
    arquivo = Path(args.tarefas)
    tarefas = json.loads(arquivo.read_text(encoding="utf-8"))
    if isinstance(tarefas, dict):
        tarefas = tarefas.get("tarefas", [])
    if args.so:
        tarefas = [t for t in tarefas if t.get("id") in args.so]
    if not tarefas:
        print("nenhuma tarefa para rodar")
        return 1
    if not health(args.url):
        print(f"llama-server não respondeu em {args.url}/health — nada foi executado.")
        return 2

    chave = modelo_ativo()
    destino = pasta_modelo(chave)
    resumo_path = destino / "_resumo.json"
    try:
        resumo = json.loads(resumo_path.read_text())
    except (OSError, ValueError):
        resumo = {}
    print(f"modelo ativo: {chave}  ->  {rel(destino)}/")

    for tarefa in tarefas:
        tid = str(tarefa.get("id", ""))
        if not ID_VALIDO.match(tid):
            print(f"  [pulada] id inválido: {tid!r}")
            continue
        if (destino / f"{tid}.txt").exists() and not args.sobrescrever:
            print(f"  [pulada] {tid}: já existe proposta em {rel(destino)}/ (use --sobrescrever para refazer)")
            continue
        inicio = time.monotonic()
        tokens = None
        extra = {}
        try:
            prompt = montar_prompt(tarefa)
            if args.stream:
                print(f"\n--- {tid} ---")
                resultado = rodar_stream(args.url, prompt, int(tarefa.get("max_tokens") or 1024),
                                         bool(tarefa.get("thinking", False)), args.timeout)
                texto, tokens = resultado["texto"].strip(), resultado["tokens"]
                extra = {k: resultado[k] for k in ("retentativa", "suspeitos", "ainda_suspeitos") if k in resultado}
            else:
                resposta = chat(
                    args.url,
                    corpo_base(
                        [{"role": "user", "content": prompt}],
                        int(tarefa.get("max_tokens") or 1024),
                        bool(tarefa.get("thinking", False)),
                    ),
                    args.timeout,
                )
                texto = (resposta["choices"][0]["message"].get("content") or "").strip()
                tokens = (resposta.get("usage") or {}).get("completion_tokens")
            ok = True
        except urllib.error.HTTPError as erro:
            texto = f"ERRO: HTTP {erro.code}: {cortar(erro.read().decode('utf-8', 'replace'), 1000)}"
            ok = False
        except Exception as erro:  # um erro não derruba o lote
            texto = f"ERRO: {type(erro).__name__}: {erro}"
            ok = False
        segundos = round(time.monotonic() - inicio, 1)
        (destino / f"{tid}.txt").write_text(texto + "\n", encoding="utf-8")
        resumo[tid] = {"segundos": segundos, "tokens": tokens, "ok": ok, **extra,
                       "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        resumo_path.write_text(json.dumps(resumo, ensure_ascii=False, indent=2))
        print(f"  {tid:<28} {'ok  ' if ok else 'ERRO'} {segundos:>7}s  tokens={tokens}")
    return 0


# ---------------------------------------------------------------- streaming com vigia de símbolos

# Métodos e nomes comuns que não são símbolos do projeto: não disparam o vigia.
COMUNS = {"get", "items", "keys", "values", "append", "extend", "join", "split", "strip", "format",
          "replace", "startswith", "endswith", "lower", "upper", "encode", "decode", "read_text",
          "write_text", "query", "filter", "filter_by", "first", "all", "add", "commit", "refresh",
          "flush", "rollback", "setdefault", "pop", "update", "copy", "exists", "open", "close",
          "assert_called_once", "assert_called_once_with", "setattr", "setenv", "raises", "fixture",
          "mark", "parametrize", "dumps", "loads", "isoformat", "now", "sleep", "monotonic"}
IGNORAR_CONSTANTES = {"TODO", "NOTE", "FIXME", "HTTP", "JSON", "SQL", "API", "URL", "UUID", "UTF",
                      "NULL", "TRUE", "FALSE", "NONE"}


def suspeitos(linha: str, conhecido: str, definidos: set[str]) -> list[str]:
    """Nomes usados na linha que não aparecem no texto real fornecido."""
    def existe(nome: str) -> bool:
        return nome in definidos or re.search(rf"\b{re.escape(nome)}\b", conhecido) is not None
    achados = []
    for _modulo, nome in re.findall(r"from\s+([\w.]+)\s+import\s+(\w+)", linha):
        if not existe(nome):
            achados.append(nome)
    for objeto, atributo in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(", linha):
        if atributo not in COMUNS and not existe(atributo):
            achados.append(f"{objeto}.{atributo}")
    for constante in re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", linha):
        if constante not in IGNORAR_CONSTANTES and not existe(constante):
            achados.append(constante)
    return achados


def _stream(url: str, corpo: dict, timeout: float, conhecido: str, vigiar: bool) -> dict:
    """Mostra token a token; com vigia, interrompe no primeiro símbolo inexistente."""
    corpo = {**corpo, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    texto, linha_atual, em_codigo, tokens = "", "", False, None
    definidos: set[str] = set()
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        for bruto in resposta:
            bruto = bruto.decode("utf-8", "replace").strip()
            if not bruto.startswith("data:"):
                continue
            dado = bruto[5:].strip()
            if dado == "[DONE]":
                break
            pedaco = json.loads(dado)
            tokens = (pedaco.get("usage") or {}).get("completion_tokens", tokens)
            escolhas = pedaco.get("choices") or [{}]
            delta = (escolhas[0].get("delta") or {}).get("content") or ""
            if not delta:
                continue
            sys.stdout.write(delta)
            sys.stdout.flush()
            texto += delta
            linha_atual += delta
            while "\n" in linha_atual:
                linha, linha_atual = linha_atual.split("\n", 1)
                if linha.lstrip().startswith("```"):
                    em_codigo = not em_codigo
                    continue
                if not em_codigo or linha.startswith(("-", "@@", " ")):
                    continue  # contexto e remoções do diff vêm do código real
                codigo = linha[1:] if linha.startswith("+") else linha
                for par in re.findall(r"\b(?:def|class)\s+(\w+)|^\s*(\w+)\s*=", codigo):
                    definidos.update(nome for nome in par if nome)
                ruins = suspeitos(codigo, conhecido, definidos)
                if vigiar and ruins:
                    return {"texto": texto, "tokens": tokens, "interrompido": ruins}
    return {"texto": texto, "tokens": tokens, "interrompido": []}


def rodar_stream(url: str, prompt: str, max_tokens: int, thinking: bool, timeout: float) -> dict:
    mensagens = [{"role": "user", "content": prompt}]
    primeira = _stream(url, corpo_base(mensagens, max_tokens, thinking), timeout, prompt, vigiar=True)
    if not primeira["interrompido"]:
        print()
        return {**primeira, "retentativa": False, "suspeitos": []}
    nomes = ", ".join(f"`{n}`" for n in primeira["interrompido"])
    print(f"\n\n[vigia] interrompido: {nomes} não aparece nos trechos fornecidos. Reenviando 1 vez.\n")
    mensagens += [{"role": "assistant", "content": primeira["texto"]},
                  {"role": "user", "content": f"Pare. {nomes} não existe nos trechos fornecidos. Refaça a "
                                              "resposta inteira usando só nomes que aparecem nos trechos abaixo. "
                                              "Se faltar informação, diga exatamente o que falta.\n\n" + prompt}]
    segunda = _stream(url, corpo_base(mensagens, max_tokens, thinking), timeout, prompt, vigiar=False)
    print()
    restantes = sorted({n for linha in segunda["texto"].splitlines() for n in suspeitos(linha, prompt, set())})
    return {**segunda, "retentativa": True, "suspeitos": primeira["interrompido"], "ainda_suspeitos": restantes}


# ---------------------------------------------------------------- ferramentas

FERRAMENTAS = [
    {"type": "function", "function": {
        "name": "ler_arquivo",
        "description": "Lê linhas de um arquivo do repositório (numeradas). Máx. 400 linhas por chamada.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "caminho relativo à raiz do repo"},
            "inicio": {"type": "integer"}, "fim": {"type": "integer"}},
            "required": ["path", "inicio", "fim"]}}},
    {"type": "function", "function": {
        "name": "listar_pasta",
        "description": "Lista o conteúdo de uma pasta do repositório.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "caminho relativo; '.' é a raiz"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "buscar_texto",
        "description": "Busca texto literal em arquivos .py dentro de uma pasta.",
        "parameters": {"type": "object", "properties": {
            "texto": {"type": "string"}, "path": {"type": "string"}},
            "required": ["texto", "path"]}}},
]


def f_ler_arquivo(path, inicio=1, fim=200):
    inicio = int(inicio)
    fim = min(int(fim), inicio + 399)
    _, linhas, ini, _ = ler_linhas(path, inicio, fim)
    return "\n".join(f"{ini + i:>5}| {l}" for i, l in enumerate(linhas))


def f_listar_pasta(path="."):
    alvo = caminho_seguro(path)
    if not alvo.is_dir():
        raise Recusado(f"não é pasta: {path}")
    saida = []
    for item in sorted(alvo.iterdir()):
        nome = rel(item)
        if any(b in nome.lower() for b in BLOQUEADOS):
            continue
        saida.append(nome + ("/" if item.is_dir() else ""))
    return "\n".join(saida) or "(vazia)"


def f_buscar_texto(texto, path="."):
    if not texto:
        raise Recusado("texto vazio")
    alvo = caminho_seguro(path)
    arquivos = [alvo] if alvo.is_file() else []
    if alvo.is_dir():
        for raiz, pastas, nomes in os.walk(alvo):
            pastas[:] = [p for p in pastas if p not in PULAR_NA_BUSCA
                         and not any(b in p.lower() for b in BLOQUEADOS)]
            arquivos += [Path(raiz) / n for n in nomes]
    achados = []
    for arq in sorted(arquivos):
        if arq.suffix != ".py":
            continue
        try:
            caminho_seguro(rel(arq))
        except Recusado:
            continue
        for n, linha in enumerate(arq.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if texto in linha:
                achados.append(f"{rel(arq)}:{n}: {linha.strip()}")
                if len(achados) >= 80:
                    return "\n".join(achados) + "\n[... limite de 80 ocorrências]"
    return "\n".join(achados) or "(nenhuma ocorrência)"


EXECUTORES = {"ler_arquivo": f_ler_arquivo, "listar_pasta": f_listar_pasta, "buscar_texto": f_buscar_texto}

SISTEMA_FERRAMENTAS = (
    "Você explora o repositório WorkDev em modo SOMENTE LEITURA. Use as ferramentas "
    "para ler o código real antes de afirmar algo. Não invente nomes de arquivos, "
    "funções ou variáveis. Qualquer mudança deve ser apresentada como PROPOSTA "
    "(ex.: diff), nunca como algo já feito. Se faltar informação, diga exatamente o que falta."
)


def cmd_ferramentas(args) -> int:
    if not health(args.url):
        print(f"llama-server não respondeu em {args.url}/health — nada foi executado.")
        return 2
    mensagens = [{"role": "system", "content": SISTEMA_FERRAMENTAS},
                 {"role": "user", "content": args.pergunta}]
    for volta in range(1, MAX_VOLTAS + 1):
        corpo = corpo_base(mensagens, args.max_tokens, args.thinking)
        corpo["tools"] = FERRAMENTAS
        try:
            resposta = chat(args.url, corpo, args.timeout)
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")
            if volta == 1:
                print("O servidor recusou a requisição com tools. O llama-server precisa "
                      "ser iniciado com --jinja para function calling.")
            print(f"HTTP {erro.code}: {cortar(detalhe, 800)}")
            return 3
        msg = resposta["choices"][0]["message"]
        chamadas = msg.get("tool_calls") or []
        if not chamadas:
            print("\n=== RESPOSTA (proposta) ===\n" + (msg.get("content") or "").strip())
            return 0
        mensagens.append({"role": "assistant", "content": msg.get("content") or "",
                          "tool_calls": chamadas})
        for chamada in chamadas:
            nome = chamada["function"]["name"]
            params = {}
            try:
                params = json.loads(chamada["function"].get("arguments") or "{}")
                if nome not in EXECUTORES:
                    raise Recusado(f"ferramenta desconhecida: {nome}")
                resultado = EXECUTORES[nome](**params)
            except Recusado as erro:
                resultado = f"RECUSADO: {erro}"
            except Exception as erro:
                resultado = f"ERRO: {type(erro).__name__}: {erro}"
            resultado = cortar(resultado)
            print(f"[volta {volta}] {nome}({json.dumps(params, ensure_ascii=False)})"
                  f" -> {len(resultado)} caracteres")
            mensagens.append({"role": "tool", "tool_call_id": chamada.get("id", nome),
                              "content": resultado})
    print(f"\nLimite de {MAX_VOLTAS} voltas atingido sem resposta final.")
    return 4


# ---------------------------------------------------------------- avaliar / resumo

def cmd_avaliar(args) -> int:
    if not ID_VALIDO.match(args.id):
        print("id inválido")
        return 1
    modelo = args.modelo
    if not modelo:
        candidatos = sorted(SAIDA.glob(f"*/{args.id}.txt"), key=lambda p: p.stat().st_mtime)
        if not candidatos:
            print(f"nenhuma saída tmp/bancada/*/{args.id}.txt — use --modelo")
            return 1
        modelo = candidatos[-1].parent.name
    registrar({"id": args.id, "modelo": modelo, "veredito": args.veredito, "origem": "operador",
               "nota": " ".join(args.nota)})
    print(f"registrado: {args.id} [{modelo}] = {args.veredito}")
    return 0


def cmd_extrair(args) -> int:
    """Diff da proposta -> tmp/bancada/patches/<id>.patch + git apply --check. Aplicar é com o operador."""
    import subprocess

    import bancada_checks as checks

    if not ID_VALIDO.match(args.id):
        print("id inválido")
        return 1
    if args.modelo:
        if not ID_VALIDO.match(args.modelo):
            print("modelo inválido")
            return 1
        proposta = SAIDA / args.modelo / f"{args.id}.txt"
    else:
        candidatos = sorted(SAIDA.glob(f"*/{args.id}.txt"), key=lambda p: p.stat().st_mtime)
        proposta = candidatos[-1] if candidatos else SAIDA / "_" / f"{args.id}.txt"
    if not proposta.is_file():
        print(f"nenhuma proposta {rel(proposta)} — confira o id ou use --modelo")
        return 1
    diff = checks.extrair_diff(proposta.read_text(encoding="utf-8", errors="replace"))
    if not diff:
        print(f"{rel(proposta)} não traz diff (resposta de análise ou FALTA:) — nada a extrair")
        return 1
    patch = SAIDA / "patches" / f"{args.id}.patch"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(diff.rstrip("\n") + "\n", encoding="utf-8")
    arquivos = re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)
    print(f"proposta: {rel(proposta)}")
    print(f"patch:    {rel(patch)}  ({', '.join(arquivos) or 'sem cabeçalho +++ b/'})")
    teste = subprocess.run(["git", "-C", str(REPO), "apply", "--recount", "--check", str(patch)],
                           capture_output=True, text=True, timeout=30)
    if teste.returncode != 0:
        print("NÃO APLICA no checkout atual:\n" + (teste.stderr or teste.stdout).strip())
        return 3
    print("aplica no checkout atual. Para aplicar (revise antes):")
    print(f"  git -C {REPO} apply --recount {patch}")
    return 0


def cmd_resumo(args) -> int:
    try:
        registros = [
            r for r in (
                json.loads(l)
                for l in REGISTRO.read_text(encoding="utf-8").splitlines()
                if l.strip()
            )
            if r.get("veredito")
        ]
    except OSError:
        print("sem registro.jsonl ainda — use `avaliar` ou `observar` primeiro")
        return 1
    # A última avaliação de cada (modelo, id, quem avaliou) vale. O veredito do
    # operador e o de cada observer ficam em linhas separadas.
    ultimo = {(r["modelo"], r["id"], r.get("origem", "operador"), r.get("observer", "")): r for r in registros}
    grupos: dict[tuple[str, str], list] = {}
    for (modelo, _, origem, observer), r in ultimo.items():
        grupos.setdefault((modelo, observer or origem), []).append(r)
    print(f"{'modelo':<10}{'avaliado por':<30}{'tarefas':>8}" + "".join(f"{v:>18}" for v in VEREDITOS) + f"{'tempo médio':>13}")
    for (modelo, quem), itens in sorted(grupos.items()):
        try:
            tempos = json.loads((SAIDA / modelo / "_resumo.json").read_text())
        except (OSError, ValueError):
            tempos = {}
        segs = [tempos[r["id"]]["segundos"] for r in itens if r["id"] in tempos]
        total = len(itens)
        colunas = "".join(
            f"{100 * sum(r['veredito'] == v for r in itens) / total:>17.0f}%" for v in VEREDITOS)
        media = f"{sum(segs) / len(segs):.1f}s" if segs else "-"
        print(f"{modelo:<10}{quem:<30}{total:>8}{colunas}{media:>13}")
    return 0


def registrar(linha: dict) -> None:
    linha = {**linha, "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    SAIDA.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- corpus / verificar

CORPUS_PADRAO = REPO / "docs" / "bancada-local" / "corpus-observers.json"
# Lidos pela página Bancada Local (só GET): tudo o que ela mostra fica em tmp/bancada/.
VERIFICACOES = SAIDA / "verificacoes"
PARECERES = SAIDA / "pareceres"


def _gravar_json(pasta: Path, nome: str, dados: dict) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    dados = {**dados, "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (pasta / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def salvar_verificacao(caso: dict, tarefa_nome: str, proposta: str, resultado: dict) -> None:
    _gravar_json(VERIFICACOES, caso["id"], {
        "id": caso["id"], "modelo": caso.get("modelo", "desconhecido"), "tarefa": tarefa_nome,
        "esperado": caso.get("esperado"), "proposta": proposta[:20000], **resultado})


def salvar_parecer(caso: dict, observer: str, resultado: dict) -> None:
    _gravar_json(PARECERES, f"{caso['id']}__{observer.replace('/', '--')}", {
        "id": caso["id"], "modelo": caso.get("modelo", "desconhecido"), "observer": observer,
        **resultado})


def carregar_corpus(caminho: str | None) -> dict:
    return json.loads(Path(caminho or CORPUS_PADRAO).read_text(encoding="utf-8"))


def trechos_da_base(tarefa: dict) -> str:
    """Trechos reais no commit de base da tarefa, no mesmo formato do `rodar`."""
    import bancada_checks as checks
    raiz = checks.base(tarefa["base"], [c for c, *_ in tarefa.get("trechos") or []])
    partes = []
    for caminho, ini, fim in tarefa.get("trechos") or []:
        linhas = checks.ler_base(raiz, caminho, ini, fim)
        partes.append(f"### {caminho} (linhas {ini}-{ini + len(linhas) - 1})\n```\n" + "\n".join(linhas) + "\n```")
    return "\n\n".join(partes)


def ler_proposta(caminho: str) -> str:
    alvo = Path(os.path.realpath(REPO / caminho))
    if REPO not in alvo.parents or not str(alvo).startswith(str(REPO / "tmp")):
        raise Recusado(f"proposta precisa estar em tmp/: {caminho}")
    return alvo.read_text(encoding="utf-8", errors="replace")


def imprimir_checagens(resultado: dict) -> None:
    for a in resultado["achados"]:
        marca = {"erro": "ERRO ", "aviso": "AVISO", "info": "ok   "}[a["severidade"]]
        print(f"  {marca} {a['categoria']:<20} {a['mensagem']}")
    print(f"  => {resultado['erros']} erro(s); {'passa' if resultado['aprovada'] else 'não passa'} nas checagens mecânicas")


def cmd_verificar(args) -> int:
    import bancada_checks as checks
    corpus = carregar_corpus(args.corpus)
    if args.caso:
        caso = next((c for c in corpus["casos"] if c["id"] == args.caso), None)
        if caso is None:
            print(f"caso {args.caso} não existe no corpus")
            return 1
        tarefa, proposta = corpus["tarefas"][caso["tarefa"]], ler_proposta(caso["proposta"])
        resultado = checks.verificar(proposta, tarefa)
        salvar_verificacao(caso, caso["tarefa"], proposta, resultado)
        imprimir_checagens(resultado)
        return 0 if resultado["aprovada"] else 3
    else:
        if not (args.proposta and args.tarefa):
            print("informe --caso, ou --proposta e --tarefa")
            return 1
        tarefa, proposta = corpus["tarefas"][args.tarefa], ler_proposta(args.proposta)
    resultado = checks.verificar(proposta, tarefa)
    imprimir_checagens(resultado)
    return 0 if resultado["aprovada"] else 3


# ---------------------------------------------------------------- observer / comparativo

def _rodar_observer(caso: dict, tarefa: dict, observer: str, verdade: dict) -> dict:
    import bancada_observer as obs
    mensagens = obs.montar_mensagens(tarefa["instrucao"], trechos_da_base(tarefa),
                                     ler_proposta(caso["proposta"]), verdade)
    resultado = obs.observar(observer, mensagens)
    salvar_parecer(caso, observer, resultado)
    registrar({"id": caso["id"], "modelo": caso.get("modelo", "desconhecido"), "origem": "observer",
               "observer": observer, "ok": resultado["ok"],
               "veredito": (resultado["parecer"] or {}).get("veredito", "falhou"),
               "erros": [e.get("categoria") for e in (resultado["parecer"] or {}).get("erros", [])],
               "custo_usd": resultado["custo_usd"], "segundos": resultado["segundos"],
               "falhas": resultado["falhas"]})
    return resultado


from bancada_observer import SEGUNDA_OPINIAO_ARBITRO, SEGUNDA_OPINIAO_PRIMARIO  # noqa: E402


def _imprimir_parecer(observer: str, resultado: dict) -> None:
    parecer = resultado["parecer"]
    print(f"\nObserver {observer}: {parecer['veredito']}  ({resultado['segundos']}s, US$ {resultado['custo_usd']})")
    for erro in parecer["erros"]:
        print(f"  - {erro.get('categoria')}: {erro.get('descricao')}")
    if parecer["prompt_correcao"]:
        print(f"Prompt de correção sugerido (não enviado):\n{parecer['prompt_correcao']}")


def cmd_observar(args) -> int:
    import bancada_checks as checks
    corpus = carregar_corpus(args.corpus)
    caso = next((c for c in corpus["casos"] if c["id"] == args.caso), None)
    if caso is None:
        print(f"caso {args.caso} não existe no corpus")
        return 1
    tarefa = corpus["tarefas"][caso["tarefa"]]
    proposta = ler_proposta(caso["proposta"])
    verdade = checks.verificar(proposta, tarefa)
    salvar_verificacao(caso, caso["tarefa"], proposta, verdade)
    print("Checagens mecânicas:")
    imprimir_checagens(verdade)

    if not getattr(args, "segunda_opiniao", False):
        resultado = _rodar_observer(caso, tarefa, args.observer, verdade)
        if not resultado["ok"]:
            print(f"\nObserver {args.observer} falhou: {' | '.join(resultado['falhas'])}")
            return 4
        _imprimir_parecer(args.observer, resultado)
        return 0

    # Modo segunda opinião: primário barato decide os casos simples (aproveitada);
    # nos demais, um árbitro mais calibrado dá a palavra final sobre a severidade.
    # Escopo: só a bancada local (scripts/bancada_local.py) — não toca o fluxo de
    # produção dos agentes (tmux code/codex/grok). Decisão de 02/out/2026.
    primario = SEGUNDA_OPINIAO_PRIMARIO
    arbitro = SEGUNDA_OPINIAO_ARBITRO
    resultado_primario = _rodar_observer(caso, tarefa, primario, verdade)
    if not resultado_primario["ok"]:
        print(f"\nObserver {primario} (primário) falhou: {' | '.join(resultado_primario['falhas'])}")
        return 4
    _imprimir_parecer(primario, resultado_primario)

    veredito_primario = resultado_primario["parecer"]["veredito"]
    if veredito_primario == "aproveitada":
        print(f"\n[segunda opinião] {primario} deu \"aproveitada\" — caso simples, não escalou para {arbitro}.")
        return 0

    print(f"\n[segunda opinião] {primario} apontou \"{veredito_primario}\" — escalando para {arbitro}...")
    resultado_arbitro = _rodar_observer(caso, tarefa, arbitro, verdade)
    if not resultado_arbitro["ok"]:
        print(f"\nObserver {arbitro} (árbitro) falhou: {' | '.join(resultado_arbitro['falhas'])} — mantendo veredito do primário.")
        return 0
    _imprimir_parecer(arbitro, resultado_arbitro)

    veredito_arbitro = resultado_arbitro["parecer"]["veredito"]
    custo_total = resultado_primario["custo_usd"] + resultado_arbitro["custo_usd"]
    if veredito_arbitro == veredito_primario:
        print(f"\n[segunda opinião] concordam em \"{veredito_arbitro}\" — custo total US$ {custo_total:.5f}")
    else:
        print(f"\n[segunda opinião] divergência: {primario}=\"{veredito_primario}\" vs {arbitro}=\"{veredito_arbitro}\". "
              f"{arbitro} decide (mais calibrado, dado de 02/out/2026). Veredito final: \"{veredito_arbitro}\" — "
              f"custo total US$ {custo_total:.5f}")
    return 0


def _qualidade_prompt(prompt: str, verdade: dict) -> int:
    """0 vazio, 1 genérico, 2 cita um nome real dos erros mecânicos (heurística)."""
    if not prompt.strip():
        return 0
    nomes = set()
    for a in verdade["achados"]:
        if a["severidade"] == "erro":
            nomes |= set(re.findall(r"\b([a-z_]+_[a-z_]+|[a-z_]+(?=\(\)))", a["mensagem"]))
    return 2 if any(n in prompt for n in nomes) else 1


def cmd_comparar(args) -> int:
    import bancada_checks as checks
    import bancada_observer as obs
    corpus = carregar_corpus(args.corpus)
    observers = args.observers or list(obs.OBSERVERS)
    casos = [c for c in corpus["casos"] if not args.so or c["id"] in args.so]
    verdades = {}
    for c in casos:
        proposta = ler_proposta(c["proposta"])
        verdades[c["id"]] = checks.verificar(proposta, corpus["tarefas"][c["tarefa"]])
        salvar_verificacao(c, c["tarefa"], proposta, verdades[c["id"]])
    linhas, total = [], 0.0
    for observer in observers:
        m = {"observer": observer, "tp": 0, "fp": 0, "fn": 0, "veredito_exato": 0, "bom_ruim": 0,
             "custo": 0.0, "segundos": [], "prompt": [], "falhas": [], "casos": []}
        for caso in casos:
            verdade = verdades[caso["id"]]
            r = _rodar_observer(caso, corpus["tarefas"][caso["tarefa"]], observer, verdade)
            m["custo"] += r["custo_usd"] or 0.0
            total += r["custo_usd"] or 0.0
            if not r["ok"]:
                m["falhas"].append(f"{caso['id']}: {r['falhas'][-1] if r['falhas'] else '?'}")
                m["casos"].append((caso["id"], "FALHOU", "-", "-"))
                print(f"  {observer:<30} {caso['id']:<22} FALHOU  (acumulado US$ {total:.4f})")
                continue
            parecer = r["parecer"]
            reais = set(verdade["categorias_erro"])
            apontados = {e.get("categoria") for e in parecer["erros"] if e.get("categoria") in checks.CATEGORIAS}
            m["tp"] += len(reais & apontados)
            m["fp"] += len(apontados - reais)
            m["fn"] += len(reais - apontados)
            m["veredito_exato"] += parecer["veredito"] == caso["esperado"]
            m["bom_ruim"] += (parecer["veredito"] == "aproveitada") == (caso["esperado"] == "aproveitada")
            m["segundos"].append(r["segundos"])
            if caso["esperado"] != "aproveitada":
                m["prompt"].append(_qualidade_prompt(parecer["prompt_correcao"], verdade))
            m["casos"].append((caso["id"], parecer["veredito"], ",".join(sorted(apontados)) or "-",
                               ",".join(sorted(reais)) or "-"))
            print(f"  {observer:<30} {caso['id']:<22} {parecer['veredito']:<17} "
                  f"US$ {r['custo_usd'] or 0:.5f}  {r['segundos']}s  (acumulado US$ {total:.4f})")
        linhas.append(m)
    print(f"\nCusto acumulado do comparativo: US$ {total:.4f}")
    # A tabela versionada só é regravada com o conjunto completo de observers e casos.
    if args.observers or args.so:
        print("Rodada parcial: tabela versionada não foi alterada (pareceres gravados em tmp/bancada/pareceres/).")
    else:
        _escrever_comparativo(linhas, casos, verdades, total)
        print(f"Tabela: {rel(REPO / 'docs' / 'bancada-local' / 'comparativo-observers.md')}")
    return 0


def _escrever_comparativo(linhas: list[dict], casos: list[dict], verdades: dict, total: float) -> None:
    n = len(casos)
    tabela = ["| Observer | Erros reais apontados | Falsos positivos | Erros perdidos | Veredito exato | Bom/ruim certo "
              "| Prompt de correção (0–2) | Custo US$ | Tempo médio | Falhas | Acerto por centavo |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in linhas:
        acertos = m["tp"] + m["bom_ruim"]
        centavos = m["custo"] * 100
        por_centavo = f"{acertos / centavos:.1f}" if centavos else "-"
        tempo = f"{sum(m['segundos']) / len(m['segundos']):.1f}s" if m["segundos"] else "-"
        prompt = f"{sum(m['prompt']) / len(m['prompt']):.1f}" if m["prompt"] else "-"
        tabela.append(f"| `{m['observer']}` | {m['tp']} | {m['fp']} | {m['fn']} | {m['veredito_exato']}/{n} "
                      f"| {m['bom_ruim']}/{n} | {prompt} | {m['custo']:.4f} | {tempo} | {len(m['falhas'])} | {por_centavo} |")
    detalhe = ["| Caso | Esperado | Erros mecânicos | " + " | ".join(f"`{m['observer']}`" for m in linhas) + " |",
               "|---|---|---|" + "---|" * len(linhas)]
    for i, caso in enumerate(casos):
        celulas = [f"{m['casos'][i][1]} ({m['casos'][i][2]})" for m in linhas]
        detalhe.append(f"| {caso['id']} | {caso['esperado']} | {','.join(verdades[caso['id']]['categorias_erro']) or '-'} | "
                       + " | ".join(celulas) + " |")
    falhas = [f"- `{m['observer']}`: " + "; ".join(m["falhas"]) for m in linhas if m["falhas"]]
    texto = "\n".join([
        "# Comparativo de observers — Bancada Local", "",
        f"Gerado por `scripts/bancada_local.py comparar` em {datetime.now(timezone.utc).isoformat(timespec='minutes')}. "
        f"{n} casos de `docs/bancada-local/corpus-observers.json`, mesmas entradas para todos.", "",
        "**Verdade de referência:** as checagens mecânicas (`verificar`): git apply na base, função do `@@`, "
        "imports, símbolos, compilação, escopo e o pedido do enunciado. O observer recebe essas checagens; "
        "o que se mede é se ele mantém os erros reais, não inventa outros e dá um bom prompt de correção.", "",
        "- **Acerto por centavo** = (erros reais apontados + bom/ruim certo) ÷ custo em centavos de dólar.",
        "- **Prompt de correção** é heurístico: 0 vazio, 1 genérico, 2 cita um nome real do erro. Vale revisar à mão.", "",
        *tabela, "", "## Por caso (veredito do observer e categorias que ele apontou)", "", *detalhe, "",
        *(["## Falhas", "", *falhas, ""] if falhas else []),
        f"**Custo acumulado:** US$ {total:.4f}", ""])
    destino = REPO / "docs" / "bancada-local" / "comparativo-observers.md"
    destino.write_text(texto, encoding="utf-8")


# ---------------------------------------------------------------- broker de leitura

PROTOCOLO_BROKER = (
    "Você está numa bancada SOMENTE LEITURA do repositório WorkDev. Você não lê arquivos sozinho: "
    "para ver código, responda APENAS com linhas de pedido, uma por linha (até 3 por vez):\n"
    "LER caminho/relativo.py 10-60\n"
    "PROCURAR termo [pasta]\n"
    "Você receberá o trecho real. Quando tiver o suficiente, responda começando com a palavra "
    "PROPOSTA: e dê a resposta. Não invente nomes nem código que você não leu. Nada será aplicado."
)
PEDIDO = re.compile(r"^\s*(LER|PROCURAR)\s+(.+?)\s*$", re.M)
BROKER_MAX_LINHAS = 200
BROKER_MAX_VOLTAS = 8


def _executar_pedido(tipo: str, argumento: str) -> str:
    if tipo == "LER":
        casado = re.match(r"(\S+)(?:\s+(\d+)\s*[-:]\s*(\d+))?$", argumento)
        if not casado:
            raise Recusado("formato: LER caminho inicio-fim")
        inicio = int(casado.group(2) or 1)
        fim = min(int(casado.group(3) or inicio + BROKER_MAX_LINHAS - 1), inicio + BROKER_MAX_LINHAS - 1)
        return f_ler_arquivo(casado.group(1), inicio, fim)
    partes = argumento.split()
    termo, pasta = (" ".join(partes[:-1]), partes[-1]) if len(partes) > 1 and "/" in partes[-1] else (argumento, ".")
    return f_buscar_texto(termo.strip("\"'"), pasta)


def cmd_broker(args) -> int:
    if not health(args.url):
        print(f"llama-server não respondeu em {args.url}/health — nada foi executado.")
        return 2
    mensagens = [{"role": "system", "content": PROTOCOLO_BROKER}, {"role": "user", "content": args.pergunta}]
    pedidos_feitos = 0
    for volta in range(1, BROKER_MAX_VOLTAS + 1):
        resposta = chat(args.url, corpo_base(mensagens, args.max_tokens, args.thinking), args.timeout)
        texto = (resposta["choices"][0]["message"].get("content") or "").strip()
        pedidos = PEDIDO.findall(texto)
        if texto.upper().startswith("PROPOSTA") or not pedidos:
            destino = pasta_modelo(modelo_ativo()) / f"broker-{int(time.time())}.txt"
            destino.write_text(texto + "\n", encoding="utf-8")
            print(f"\n=== RESPOSTA (proposta, {pedidos_feitos} pedido(s) de leitura) ===\n{texto}")
            print(f"\n(gravado em {rel(destino)})")
            return 0 if pedidos_feitos else 5
        resultados = []
        for tipo, argumento in pedidos[:3]:
            pedidos_feitos += 1
            try:
                conteudo = cortar(_executar_pedido(tipo, argumento))
                print(f"[volta {volta}] {tipo} {argumento} -> {len(conteudo)} caracteres")
            except Recusado as erro:
                conteudo = f"RECUSADO: {erro}"
                print(f"[volta {volta}] {tipo} {argumento} -> {conteudo}")
            resultados.append(f"RESULTADO de {tipo} {argumento}:\n{conteudo}")
        mensagens += [{"role": "assistant", "content": texto},
                      {"role": "user", "content": "\n\n".join(resultados)}]
    print(f"Limite de {BROKER_MAX_VOLTAS} voltas sem PROPOSTA.")
    return 4


# ---------------------------------------------------------------- planejador simplificado

PROTOCOLO_PLANEJADOR = (
    "Você é o PLANEJADOR SIMPLIFICADO da Bancada Local do WorkDev. "
    "Sua função é separar somente trabalho pequeno, seguro e verificável para "
    "um modelo local. Você NÃO altera arquivos.\n\n"

    "Você não lê o repositório sozinho. Quando precisar de contexto, responda "
    "APENAS com até 3 pedidos por vez:\n"
    "LER caminho/relativo.py 10-60\n"
    "PROCURAR termo [pasta]\n\n"

    "REGRAS:\n"
    "- no máximo 4 tarefas;\n"
    "- cada tarefa deve ter uma ação só;\n"
    "- no máximo 2 arquivos por tarefa;\n"
    "- use somente linhas realmente recebidas por LER;\n"
    "- não estime linhas;\n"
    "- nada de decisão arquitetural, configuração, migração, banco ou tarefa "
    "dependente de outro passo;\n"
    "- prefira pedir CONTEÚDO para edição, não diff;\n"
    "- cada instrução deve conter contexto suficiente para funcionar sozinha;\n"
    "- termine cada instrucao com: "
    "\"Use só nomes que aparecem nos trechos. Se faltar algo, responda "
    "FALTA: <o que falta> em vez de inventar. Saída: <formato>.\"\n"
    "- max_tokens deve ser no máximo 400;\n"
    "- espera_diff normalmente deve ser false.\n\n"

    "Quando tiver contexto suficiente, responda SOMENTE com JSON válido neste formato:\n"
    '{"tarefas":[{"id":"...","instrucao":"...","trechos":[["caminho",10,30]],'
    '"max_tokens":400,"espera_diff":false}],'
    '"fora_do_alcance":"opcional"}\n\n'

    "Se nada couber na bancada local, responda:\n"
    '{"tarefas":[],"fora_do_alcance":"motivo"}\n'
)


def _extrair_plano(texto: str, lote: str) -> dict:
    bruto = texto.strip()

    if bruto.upper().startswith("PROPOSTA:"):
        bruto = bruto.split(":", 1)[1].strip()
    if bruto.upper().startswith("PLANO:"):
        bruto = bruto.split(":", 1)[1].strip()

    if bruto.startswith("```"):
        linhas = bruto.splitlines()
        if linhas:
            linhas = linhas[1:]
        if linhas and linhas[-1].strip().startswith("```"):
            linhas = linhas[:-1]
        bruto = "\n".join(linhas).strip()

    ini = bruto.find("{")
    fim = bruto.rfind("}")
    if ini < 0 or fim < ini:
        raise ValueError("resposta sem objeto JSON")

    plano = json.loads(bruto[ini:fim + 1])

    if not isinstance(plano, dict):
        raise ValueError("plano precisa ser objeto JSON")

    return validar_lote(plano, lote, LIMITES_LOCAL)


# Limites por origem do lote. O local (modelo pequeno fatiando) é estreito de
# propósito; o do AI Hub (LLM grande fatiando) segue o contrato do `rodar` da
# página: até 8 trechos, max_tokens 64-4000. Um lote tem até 10 tarefas, porque
# cada proposta passa por revisão humana; de 11 a 20 o plano vira 2 lotes
# (dividir_em_lotes) e acima disso a task é grande demais para a Bancada.
LIMITES_LOCAL = {"max_tarefas": 4, "max_arquivos": 2, "max_tokens": (64, 400)}
LIMITES_AI_HUB = {"max_tarefas": 10, "max_arquivos": 8, "max_tokens": (64, 4000)}
MAX_LOTES_POR_PLANO = 2
MAX_TRECHOS = 8
MAX_LINHAS_TRECHO = 400
MAX_INSTRUCAO = 8000
MAX_EXIGE = 5


def lote_seguinte(lote: str) -> str:
    dia, numero = LOTE.match(lote).groups()
    return f"{dia}-{int(numero) + 1:02d}"


def dividir_em_lotes(plano: dict, lote: str, limites: dict, raiz: Path | None = None) -> list[tuple[str, dict]]:
    """Valida o plano e, se passar de max_tarefas, divide em até MAX_LOTES_POR_PLANO lotes
    equilibrados (15 -> 8 + 7), cada um com seu id AAMMDD-NN. As tarefas já são
    independentes entre si (o modelo local não vê as respostas anteriores)."""
    if not isinstance(plano, dict):
        raise ValueError("plano precisa ser objeto JSON")
    tarefas = plano.get("tarefas")
    if not isinstance(tarefas, list):
        raise ValueError("campo tarefas precisa ser lista")
    teto = limites["max_tarefas"] * MAX_LOTES_POR_PLANO
    if len(tarefas) > teto:
        raise ValueError(f"máximo de {teto} tarefas ({MAX_LOTES_POR_PLANO} lotes de "
                         f"{limites['max_tarefas']}); divida a task no backlog")
    explicitos = [t.get("id") for t in tarefas if isinstance(t, dict) and isinstance(t.get("id"), str)
                  and t["id"].strip() and not ID_GENERICO.match(t["id"].strip())]
    repetido = next((i for i in explicitos if explicitos.count(i) > 1), None)
    if repetido:
        raise ValueError(f"id duplicado: {repetido}")
    partes = -(-len(tarefas) // limites["max_tarefas"]) or 1
    tamanho = -(-len(tarefas) // partes)
    lotes = []
    for n in range(partes):
        parte = {**plano, "tarefas": tarefas[n * tamanho:(n + 1) * tamanho]}
        lotes.append((lote, validar_lote(parte, lote, limites, raiz)))
        lote = lote_seguinte(lote)
    return lotes


def validar_lote(plano: dict, lote: str, limites: dict, raiz: Path | None = None) -> dict:
    """Valida um lote {"tarefas": [...]} contra os arquivos reais e dá ids.

    Ids genéricos (vazio, "1", "t2") viram <lote>-NN. Levanta ValueError com a
    primeira regra violada; devolve o próprio plano normalizado.
    """
    if not isinstance(plano, dict):
        raise ValueError("plano precisa ser objeto JSON")
    tarefas = plano.get("tarefas")
    if not isinstance(tarefas, list):
        raise ValueError("campo tarefas precisa ser lista")
    if len(tarefas) > limites["max_tarefas"]:
        raise ValueError(f"máximo de {limites['max_tarefas']} tarefas")
    min_tokens, max_tokens_lim = limites["max_tokens"]

    def generico(tid) -> bool:
        if tid is None or isinstance(tid, int) and not isinstance(tid, bool):
            return True
        return isinstance(tid, str) and (not tid.strip() or bool(ID_GENERICO.match(tid.strip())))

    # Ids automáticos <lote>-NN (lote = AAMMDD-NN): não repetem entre planos do mesmo dia.
    # Pulam os que o modelo já usou de forma descritiva.
    explicitos = {t.get("id") for t in tarefas
                  if isinstance(t, dict) and not generico(t.get("id"))}
    contador = 0

    ids = set()

    for i, tarefa in enumerate(tarefas, 1):
        if not isinstance(tarefa, dict):
            raise ValueError(f"tarefa {i}: precisa ser objeto")

        if generico(tarefa.get("id")):
            while True:
                contador += 1
                novo = f"{lote}-{contador:02d}"
                if novo not in explicitos:
                    break
            tarefa["id"] = novo

        tid = tarefa.get("id")
        instrucao = tarefa.get("instrucao")
        trechos = tarefa.get("trechos", [])

        if not isinstance(tid, str) or not ID_VALIDO.match(tid):
            raise ValueError(f"tarefa {i}: id inválido")
        if tid in ids:
            raise ValueError(f"id duplicado: {tid}")
        ids.add(tid)

        if not isinstance(instrucao, str) or len(instrucao.strip()) < 20:
            raise ValueError(f"{tid}: instrucao ausente ou curta demais")
        if len(instrucao) > MAX_INSTRUCAO:
            raise ValueError(f"{tid}: instrucao acima de {MAX_INSTRUCAO} caracteres")

        if not isinstance(trechos, list) or not trechos:
            raise ValueError(f"{tid}: precisa informar trechos reais")
        if len(trechos) > MAX_TRECHOS:
            raise ValueError(f"{tid}: no máximo {MAX_TRECHOS} trechos")

        arquivos = set()

        for trecho in trechos:
            if not isinstance(trecho, list) or len(trecho) != 3:
                raise ValueError(f"{tid}: trecho inválido: {trecho!r}")

            caminho, inicio, fim_linha = trecho

            if not isinstance(caminho, str):
                raise ValueError(f"{tid}: caminho inválido")
            if not isinstance(inicio, int) or not isinstance(fim_linha, int):
                raise ValueError(f"{tid}: linhas precisam ser inteiros")
            if inicio < 1 or fim_linha < inicio:
                raise ValueError(f"{tid}: intervalo inválido {inicio}-{fim_linha}")
            if fim_linha - inicio + 1 > MAX_LINHAS_TRECHO:
                raise ValueError(f"{tid}: trecho acima de {MAX_LINHAS_TRECHO} linhas em {caminho}")

            try:
                alvo = caminho_seguro(caminho, raiz)
            except Recusado as erro:
                raise ValueError(f"{tid}: {erro}")

            if not alvo.is_file():
                raise ValueError(f"{tid}: arquivo não existe: {caminho}")

            total_linhas = sum(1 for _ in alvo.open(
                "r", encoding="utf-8", errors="replace"
            ))

            if fim_linha > total_linhas:
                raise ValueError(
                    f"{tid}: linha {fim_linha} não existe em {caminho} "
                    f"(arquivo tem {total_linhas})"
                )

            arquivos.add(caminho)

        if len(arquivos) > limites["max_arquivos"]:
            raise ValueError(f"{tid}: usa mais de {limites['max_arquivos']} arquivos")

        max_tokens = tarefa.get("max_tokens", min(400, max_tokens_lim))
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) \
                or not min_tokens <= max_tokens <= max_tokens_lim:
            raise ValueError(f"{tid}: max_tokens deve estar entre {min_tokens} e {max_tokens_lim}")

        exige = tarefa.get("exige") or {}
        if not isinstance(exige, dict) or len(exige) > MAX_EXIGE:
            raise ValueError(f"{tid}: exige precisa ser objeto com até {MAX_EXIGE} itens")
        for padrao, explicacao in exige.items():
            if len(padrao) > 200 or len(str(explicacao)) > 200:
                raise ValueError(f"{tid}: cada item de exige tem até 200 caracteres")
            try:
                re.compile(padrao)
            except re.error:
                raise ValueError(f"{tid}: expressão inválida em exige: {padrao!r}")

        tarefa["max_tokens"] = max_tokens
        tarefa["espera_diff"] = bool(tarefa.get("espera_diff", False))
        if exige:
            tarefa["exige"] = {str(k): str(v) for k, v in exige.items()}

    return plano


def cmd_planejar(args) -> int:
    if not health(args.url):
        print(f"llama-server não respondeu em {args.url}/health — nada foi executado.")
        return 2

    if len(args.tarefa.strip()) < 20:
        print("tarefa curta demais; descreva objetivo e resultado esperado.")
        return 1

    lote = proximo_lote(SAIDA / "planos")
    if args.saida:
        bruto = Path(args.saida)
        destino = Path(os.path.realpath(bruto if bruto.is_absolute() else REPO / bruto))
        raiz = Path(os.path.realpath(SAIDA))
        if raiz not in destino.parents:
            print(f"--saida recusado: precisa ficar dentro de {rel(SAIDA)}/ (recebido: {args.saida})")
            return 1
    else:
        destino = SAIDA / "planos" / f"{lote}.json"

    mensagens = [
        {"role": "system", "content": PROTOCOLO_PLANEJADOR},
        {"role": "user", "content": "TAREFA:\n" + args.tarefa.strip()},
    ]

    pedidos_feitos = 0

    for volta in range(1, BROKER_MAX_VOLTAS + 1):
        resposta = chat(
            args.url,
            corpo_base(mensagens, args.max_tokens, args.thinking),
            args.timeout,
        )
        texto = (
            resposta["choices"][0]["message"].get("content") or ""
        ).strip()

        pedidos = PEDIDO.findall(texto)

        if pedidos:
            resultados = []

            for tipo, argumento in pedidos[:3]:
                pedidos_feitos += 1
                try:
                    conteudo = cortar(_executar_pedido(tipo, argumento))
                    print(
                        f"[planejador volta {volta}] {tipo} {argumento} "
                        f"-> {len(conteudo)} caracteres"
                    )
                except Recusado as erro:
                    conteudo = f"RECUSADO: {erro}"
                    print(
                        f"[planejador volta {volta}] "
                        f"{tipo} {argumento} -> {conteudo}"
                    )

                resultados.append(
                    f"RESULTADO de {tipo} {argumento}:\n{conteudo}"
                )

            mensagens += [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": "\n\n".join(resultados)},
            ]
            continue

        try:
            plano = _extrair_plano(texto, lote)
        except (ValueError, json.JSONDecodeError) as erro:
            print(f"[planejador volta {volta}] JSON recusado: {erro}")
            mensagens += [
                {"role": "assistant", "content": texto},
                {
                    "role": "user",
                    "content": (
                        f"FORMATO INVÁLIDO: {erro}. "
                        "Corrija sem inventar contexto. "
                        "Se faltar informação, peça LER/PROCURAR. "
                        "Caso contrário devolva somente o JSON válido."
                    ),
                },
            ]
            continue

        plano = {"lote": lote, **plano}
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(plano, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print()
        print("=== PLANO VALIDADO ===")
        print(json.dumps(plano, ensure_ascii=False, indent=2))
        print()
        print(f"leituras feitas: {pedidos_feitos}")
        print(f"lote: {lote}")
        print(f"gravado em: {rel(destino)}")

        if plano.get("tarefas"):
            print()
            print(
                "para executar:"
                f"\npython3 scripts/bancada_local.py rodar {rel(destino)}"
            )
        else:
            print()
            print(
                "nenhuma tarefa enviada ao local: "
                + str(plano.get("fora_do_alcance", "sem motivo informado"))
            )

        return 0

    print(
        f"Limite de {BROKER_MAX_VOLTAS} voltas "
        "sem produzir plano JSON válido."
    )
    return 4


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=URL_PADRAO)
    p.add_argument("--timeout", type=float, default=900)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rodar")
    r.add_argument("tarefas")
    r.add_argument("--so", nargs="+", help="roda só estes ids")
    r.add_argument("--stream", action="store_true", help="mostra token a token e vigia símbolos")
    r.add_argument("--sobrescrever", action="store_true",
                   help="refaz tarefas que já têm proposta deste modelo (padrão: pula)")
    r.set_defaults(func=cmd_rodar)

    f = sub.add_parser("ferramentas")
    f.add_argument("pergunta")
    f.add_argument("--max-tokens", type=int, default=1500)
    f.add_argument("--thinking", action="store_true")
    f.set_defaults(func=cmd_ferramentas)

    a = sub.add_parser("avaliar")
    a.add_argument("id")
    a.add_argument("veredito", choices=VEREDITOS)
    a.add_argument("nota", nargs="*")
    a.add_argument("--modelo", help="padrão: pasta com a saída mais recente desse id")
    a.set_defaults(func=cmd_avaliar)

    x = sub.add_parser("extrair", help="grava o diff da proposta em tmp/bancada/patches/ e testa (não aplica)")
    x.add_argument("id")
    x.add_argument("--modelo", help="padrão: pasta com a proposta mais recente desse id")
    x.set_defaults(func=cmd_extrair)

    s = sub.add_parser("resumo")
    s.set_defaults(func=cmd_resumo)

    v = sub.add_parser("verificar", help="checagens mecânicas (sem LLM) de uma proposta")
    v.add_argument("--caso", help="id de um caso do corpus")
    v.add_argument("--proposta", help="arquivo da proposta em tmp/")
    v.add_argument("--tarefa", help="nome da tarefa no corpus")
    v.add_argument("--corpus")
    v.set_defaults(func=cmd_verificar)

    o = sub.add_parser("observar", help="checagens + parecer de um observer (não reenvia)")
    o.add_argument("caso")
    o.add_argument("--observer", default="openai/gpt-5.6-luna",
                   help="modelo do observer (padrão: openai/gpt-5.6-luna)")
    o.add_argument("--segunda-opiniao", action="store_true", dest="segunda_opiniao",
                   help="escalona para um árbitro (openai/gpt-5.6-luna) quando o primário "
                        "(mistralai/codestral-2508) não disser 'aproveitada'; ignora --observer")
    o.add_argument("--corpus")
    o.set_defaults(func=cmd_observar)

    c = sub.add_parser("comparar", help="mesmas entradas em vários observers")
    c.add_argument("--observers", nargs="+")
    c.add_argument("--so", nargs="+", help="só estes casos")
    c.add_argument("--corpus")
    c.set_defaults(func=cmd_comparar)

    b = sub.add_parser("broker", help="modelo local pede LER/PROCURAR; o broker só lê")
    b.add_argument("pergunta")
    b.add_argument("--max-tokens", type=int, default=1500)
    b.add_argument("--thinking", action="store_true")
    b.set_defaults(func=cmd_broker)

    pl = sub.add_parser(
        "planejar",
        help="planejador local simplificado; lê via broker e gera tarefas.json",
    )
    pl.add_argument("tarefa", help="descrição da task a decompor")
    pl.add_argument(
        "--saida",
        help="arquivo JSON de destino, só dentro de tmp/bancada/; padrão: tmp/bancada/planos/<lote>.json",
    )
    pl.add_argument("--max-tokens", type=int, default=1400)
    pl.add_argument("--thinking", action="store_true")
    pl.set_defaults(func=cmd_planejar)

    args = p.parse_args()
    try:
        return args.func(args)
    finally:
        _devolver_para_workdev()


def _devolver_para_workdev() -> None:
    """Como root (para ler a chave da OpenRouter), a CLI cria arquivos de root em
    tmp/bancada; a página roda como workdev e precisa gravar lá também."""
    if os.geteuid() != 0 or not SAIDA.exists():
        return
    import pwd
    try:
        dono = pwd.getpwnam("workdev")
    except KeyError:
        return
    for raiz, pastas, arquivos in os.walk(SAIDA):
        for nome in [raiz, *(os.path.join(raiz, n) for n in pastas + arquivos)]:
            try:
                os.lchown(nome, dono.pw_uid, dono.pw_gid)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
