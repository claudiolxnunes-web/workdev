#!/usr/bin/env python3
"""Bancada Local: usa o llama-server (127.0.0.1:8080) fora do harness do CLI qwen.

Toda saída é PROPOSTA. Este script nunca aplica patch, nunca roda shell, nunca
toca em git e nunca escreve no repositório — só grava em tmp/bancada/.
Não lê .env nem precisa da WORKDEV_API_KEY.

Subcomandos:
  rodar tarefas.json                 executa as tarefas em ordem
  ferramentas "<pergunta>"           exploração somente leitura com function calling
  avaliar <id> <veredito> [nota]     registra o aproveitamento em registro.jsonl
  resumo                             taxa de aproveitamento e tempo médio por modelo
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

BLOQUEADOS = (".env", ".git", "secret", ".key", ".pem", "node_modules")
# Pastas enormes ou sem interesse que a busca nem percorre.
PULAR_NA_BUSCA = {"venv", ".venv", "__pycache__", "dist", "build"}
LIMITE_FERRAMENTA = 6000
MAX_VOLTAS = 10
VEREDITOS = ("aproveitada", "correcao_pequena", "descartada")
ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class Recusado(Exception):
    pass


# ---------------------------------------------------------------- caminhos

def caminho_seguro(relativo: str) -> Path:
    """Resolve com realpath e recusa o que sai da raiz ou bate na lista negra."""
    if not isinstance(relativo, str) or not relativo.strip():
        raise Recusado("caminho vazio")
    bruto = relativo.strip()
    alvo = Path(os.path.realpath(REPO / bruto))
    if alvo != REPO and REPO not in alvo.parents:
        raise Recusado(f"fora do repositório: {bruto}")
    rel = alvo.relative_to(REPO).as_posix().lower()
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
        inicio = time.monotonic()
        tokens = None
        try:
            prompt = montar_prompt(tarefa)
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
        resumo[tid] = {"segundos": segundos, "tokens": tokens, "ok": ok,
                       "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        resumo_path.write_text(json.dumps(resumo, ensure_ascii=False, indent=2))
        print(f"  {tid:<28} {'ok  ' if ok else 'ERRO'} {segundos:>7}s  tokens={tokens}")
    return 0


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
    linha = {"id": args.id, "modelo": modelo, "veredito": args.veredito,
             "nota": " ".join(args.nota), "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    SAIDA.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    print(f"registrado: {args.id} [{modelo}] = {args.veredito}")
    return 0


def cmd_resumo(args) -> int:
    try:
        registros = [json.loads(l) for l in REGISTRO.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        print("sem registro.jsonl ainda — use `avaliar` primeiro")
        return 1
    # A última avaliação de cada (modelo, id) vale.
    ultimo = {(r["modelo"], r["id"]): r for r in registros}
    por_modelo: dict[str, list] = {}
    for (modelo, _), r in ultimo.items():
        por_modelo.setdefault(modelo, []).append(r)
    print(f"{'modelo':<14}{'tarefas':>8}" + "".join(f"{v:>18}" for v in VEREDITOS) + f"{'tempo médio':>14}")
    for modelo, itens in sorted(por_modelo.items()):
        try:
            tempos = json.loads((SAIDA / modelo / "_resumo.json").read_text())
        except (OSError, ValueError):
            tempos = {}
        segs = [tempos[r["id"]]["segundos"] for r in itens if r["id"] in tempos]
        total = len(itens)
        colunas = "".join(
            f"{100 * sum(r['veredito'] == v for r in itens) / total:>17.0f}%" for v in VEREDITOS)
        media = f"{sum(segs) / len(segs):.1f}s" if segs else "-"
        print(f"{modelo:<14}{total:>8}{colunas}{media:>14}")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=URL_PADRAO)
    p.add_argument("--timeout", type=float, default=900)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rodar")
    r.add_argument("tarefas")
    r.add_argument("--so", nargs="+", help="roda só estes ids")
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

    s = sub.add_parser("resumo")
    s.set_defaults(func=cmd_resumo)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
