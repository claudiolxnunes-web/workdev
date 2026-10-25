"""Bancada Local, segunda etapa: rodar, verificar, pedir parecer e reenviar.

Tudo o que a página executa passa por aqui, sempre por pedido explícito do
operador. Nada é aplicado ao repositório: o modelo local só produz proposta,
gravada em tmp/bancada. Uma execução por vez (o llama-server tem um slot).

As regras de vigia, checagens e observer são os módulos da própria release
(scripts/bancada_*.py), não do checkout que outros agentes editam. Os trechos
de código e a base das checagens vêm do checkout de trabalho (WORKDEV_BANCADA_REPO).
"""
from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
REPO_TRABALHO = Path(os.environ.get("WORKDEV_BANCADA_REPO", "/opt/workdev"))
LLAMA_URL = os.environ.get("WORKDEV_LLAMA_URL", "http://127.0.0.1:8080")
LLAMA_KEY_FILE = Path("/var/lib/workdev-llama/model")
ALIAS = "workdev-qwen"

BLOQUEADOS = (".env", ".git", "secret", ".key", ".pem", "node_modules",
              "credential", "id_rsa", "id_ed25519", ".p12", ".pfx")
ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_TRECHOS = 8
MAX_LINHAS_TRECHO = 400
MAX_INSTRUCAO = 8000
MAX_PROMPT_REENVIO = 8000
MAX_TOKENS = 4000
TIMEOUT = 900


class BancadaErro(Exception):
    def __init__(self, status: int, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.status, self.codigo, self.mensagem = status, codigo, mensagem


def pasta() -> Path:
    return Path(os.path.realpath(os.environ.get("WORKDEV_BANCADA_DIR", "/opt/workdev/tmp/bancada")))


def _modulo(nome: str):
    """bancada_checks / bancada_observer / bancada_local da release."""
    os.environ.setdefault("WORKDEV_BANCADA_REPO", str(REPO_TRABALHO))
    os.environ.setdefault("WORKDEV_BANCADA_DIR", str(pasta()))
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(nome)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gravar(caminho: Path, dados: dict | str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, indent=1)
    caminho.write_text(texto, encoding="utf-8")


def registrar(linha: dict) -> None:
    pasta().mkdir(parents=True, exist_ok=True)
    with (pasta() / "registro.jsonl").open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({**linha, "data": _agora()}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- tarefa

def ler_trecho(caminho: str, inicio: int, fim: int, raiz: Path | None = None) -> tuple[str, int, int]:
    """`raiz`: a cópia da sessão do Workspace; sem ela, o checkout de trabalho."""
    if not isinstance(caminho, str) or not caminho.strip():
        raise BancadaErro(422, "trecho_invalido", "caminho vazio")
    base = (raiz or REPO_TRABALHO).resolve()
    alvo = Path(os.path.realpath(base / caminho.strip()))
    if base not in alvo.parents:
        raise BancadaErro(422, "trecho_invalido", f"fora do repositório: {caminho}")
    relativo = alvo.relative_to(base).as_posix().lower()
    for proibido in BLOQUEADOS:
        if proibido in caminho.lower() or proibido in relativo:
            raise BancadaErro(422, "trecho_bloqueado", f"caminho bloqueado ({proibido}): {caminho}")
    if not alvo.is_file():
        raise BancadaErro(422, "trecho_invalido", f"não é arquivo: {caminho}")
    linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    inicio = max(1, int(inicio))
    fim = min(len(linhas), int(fim), inicio + MAX_LINHAS_TRECHO - 1)
    if fim < inicio:
        raise BancadaErro(422, "trecho_invalido", f"intervalo vazio em {caminho}")
    return "\n".join(linhas[inicio - 1:fim]), inicio, fim


def montar_prompt(instrucao: str, trechos: list, raiz: Path | None = None) -> tuple[str, list]:
    if not instrucao or not instrucao.strip():
        raise BancadaErro(422, "instrucao_vazia", "escreva a instrução")
    if len(instrucao) > MAX_INSTRUCAO:
        raise BancadaErro(422, "instrucao_longa", f"instrução acima de {MAX_INSTRUCAO} caracteres")
    if len(trechos) > MAX_TRECHOS:
        raise BancadaErro(422, "trechos_demais", f"no máximo {MAX_TRECHOS} trechos")
    partes, normalizados = [instrucao.strip()], []
    for caminho, ini, fim in trechos:
        texto, ini, fim = ler_trecho(caminho, ini, fim, raiz)
        normalizados.append([caminho.strip(), ini, fim])
        partes.append(f"### {caminho.strip()} (linhas {ini}-{fim})\n```\n{texto}\n```")
    return "\n\n".join(partes), normalizados


def chave_modelo() -> str:
    try:
        bruto = LLAMA_KEY_FILE.read_bytes()[:32].decode("ascii", "ignore")
    except OSError:
        return "desconhecido"
    return "".join(c for c in bruto if c.islower() or c.isdigit()) or "desconhecido"


def commit_base(raiz: Path | None = None) -> str:
    resultado = subprocess.run(["git", "-C", str(raiz or REPO_TRABALHO), "rev-parse", "--short=12", "HEAD"],
                               capture_output=True, text=True, timeout=10)
    if resultado.returncode != 0:
        raise BancadaErro(500, "sem_base", "não foi possível ler o HEAD do checkout de trabalho")
    return resultado.stdout.strip()


# ---------------------------------------------------------------- uma execução por vez

@contextmanager
def _lock_execucao():
    pasta().mkdir(parents=True, exist_ok=True)
    arquivo = open(pasta() / ".execucao.lock", "w")
    try:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as erro:
            raise BancadaErro(409, "ocupado", "já há uma execução da Bancada em andamento") from erro
        yield
    finally:
        arquivo.close()


def ocupado() -> bool:
    try:
        with _lock_execucao():
            return False
    except BancadaErro:
        return True


def llama_no_ar() -> bool:
    try:
        with urllib.request.urlopen(LLAMA_URL + "/health", timeout=5) as resposta:
            return json.loads(resposta.read() or b"{}").get("status") == "ok"
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------- streaming

def _sse(evento: dict) -> str:
    return "data: " + json.dumps(evento, ensure_ascii=False) + "\n\n"


def _stream_llama(mensagens: list, max_tokens: int, conhecido: str, vigiar: bool,
                  tools: list | None = None) -> Iterator[dict]:
    """Eventos 'token' e, se o vigia agir, um 'interrompido' final.

    Com `tools`, o evento final 'tokens' traz também as `chamadas` que o modelo
    pediu (o llama-server manda os argumentos em pedaços, por índice).
    """
    local = _modulo("bancada_local")
    suspeitos = local.suspeitos
    corpo = {"model": ALIAS, "messages": mensagens, "max_tokens": max_tokens, "temperature": 0.2,
             "stream": True, "stream_options": {"include_usage": True},
             "chat_template_kwargs": {"enable_thinking": False}}
    if tools:
        corpo["tools"] = tools
    req = urllib.request.Request(LLAMA_URL + "/v1/chat/completions", data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    linha_atual, em_codigo, definidos, tokens = "", False, set(), None
    medicao: dict = {}
    chamadas: dict[int, dict] = {}
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resposta:
        for bruto in resposta:
            bruto = bruto.decode("utf-8", "replace").strip()
            if not bruto.startswith("data:"):
                continue
            dado = bruto[5:].strip()
            if dado == "[DONE]":
                break
            pedaco = json.loads(dado)
            tokens = (pedaco.get("usage") or {}).get("completion_tokens", tokens)
            if pedaco.get("timings"):
                medicao = local.medir_timings(pedaco)
            bloco = (pedaco.get("choices") or [{}])[0].get("delta") or {}
            for parcial in bloco.get("tool_calls") or []:
                atual = chamadas.setdefault(int(parcial.get("index") or 0),
                                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                atual["id"] = parcial.get("id") or atual["id"]
                funcao = parcial.get("function") or {}
                atual["function"]["name"] += funcao.get("name") or ""
                atual["function"]["arguments"] += funcao.get("arguments") or ""
            delta = bloco.get("content") or ""
            if not delta:
                continue
            yield {"tipo": "token", "texto": delta}
            linha_atual += delta
            while "\n" in linha_atual:
                linha, linha_atual = linha_atual.split("\n", 1)
                if linha.lstrip().startswith("```"):
                    em_codigo = not em_codigo
                    continue
                if not em_codigo or linha.startswith(("-", "@@", " ")):
                    continue
                codigo = linha[1:] if linha.startswith("+") else linha
                for par in re.findall(r"\b(?:def|class)\s+(\w+)|^\s*(\w+)\s*=", codigo):
                    definidos.update(n for n in par if n)
                ruins = suspeitos(codigo, conhecido, definidos)
                if vigiar and ruins:
                    yield {"tipo": "interrompido", "nomes": ruins, "tokens": tokens, "medicao": medicao}
                    return
    final = {"tipo": "tokens", "tokens": tokens, "medicao": medicao}
    if chamadas:
        final["chamadas"] = [chamadas[i] for i in sorted(chamadas)]
    yield final


# ---------------------------------------------------------------- ferramentas (Workspace)

# Só o chat Local do Workspace liga as ferramentas; a página da Bancada roda sem.
# A leitura é do leitura_repo, a mesma do supervisor.
MAX_VOLTAS_FERRAMENTA = 6
# Teto do que as leituras somam no contexto. ~24 mil caracteres são ~6 mil
# tokens: perto de 2 minutos de prefill na CPU. Sem teto, o problema dos 22 mil
# tokens do harness volta pelas leituras.
MAX_CONTEXTO_FERRAMENTA = 24_000
MAX_SAIDA_FERRAMENTA = 6000
MAX_TRECHOS_REGISTRADOS = 16

FERRAMENTAS_WORKSPACE = [
    {"type": "function", "function": {
        "name": "buscar_texto",
        "description": "Procura texto literal no repositório (como git grep). Devolve caminho:linha: conteúdo. "
                       "Use antes de ler, para achar onde algo está.",
        "parameters": {"type": "object", "properties": {
            "texto": {"type": "string", "description": "texto literal, ex.: def current"},
            "caminho": {"type": "string", "description": "pasta ou arquivo; '.' é a raiz"}},
            "required": ["texto"]}}},
    {"type": "function", "function": {
        "name": "listar_pasta",
        "description": "Lista arquivos e subpastas de uma pasta do repositório.",
        "parameters": {"type": "object", "properties": {
            "caminho": {"type": "string", "description": "pasta relativa; '.' é a raiz"}},
            "required": ["caminho"]}}},
    {"type": "function", "function": {
        "name": "ler_arquivo",
        "description": "Lê linhas numeradas de um arquivo do repositório (no máximo 200 por chamada). "
                       "Leia só o intervalo que precisa.",
        "parameters": {"type": "object", "properties": {
            "caminho": {"type": "string", "description": "caminho relativo à raiz"},
            "inicio": {"type": "integer"}, "fim": {"type": "integer"}},
            "required": ["caminho", "inicio", "fim"]}}},
]

SISTEMA_FERRAMENTAS = (
    "Você pode ler o repositório com buscar_texto, listar_pasta e ler_arquivo (somente leitura). "
    "Cada leitura custa tempo: use buscar_texto antes de ler e leia só as linhas necessárias. "
    "Não invente nomes de arquivos, funções ou variáveis: confira no código. "
    "Quando tiver o suficiente, responda no formato pedido e nada mais."
)

AVISO_LIMITE_FERRAMENTA = ("Limite de leituras atingido. Responda agora, no formato pedido, só com o que já "
                           "leu. Se faltar informação, responda exatamente: FALTA: <o que falta e onde estaria>.")


def _ferramenta(chamada: dict, raiz: Path | None = None) -> tuple[str, dict, list | None]:
    """Executa uma chamada do modelo: (saída em texto, argumentos, trecho lido ou None)."""
    from app.services import leitura_repo
    nome = (chamada.get("function") or {}).get("name") or ""
    try:
        args = json.loads((chamada.get("function") or {}).get("arguments") or "{}")
        if not isinstance(args, dict):
            raise ValueError("argumentos precisam ser objeto")
    except ValueError as erro:
        return f"ERRO: argumentos inválidos ({erro})", {}, None
    try:
        if nome == "buscar_texto":
            r = leitura_repo.buscar_texto(args.get("texto"), args.get("caminho") or ".", raiz)
            linhas = [f"{o['caminho']}:{o['linha']}: {o['texto']}" for o in r["ocorrencias"]]
            saida = "\n".join(linhas) or "(nenhuma ocorrência)"
            if r.get("truncado"):
                saida += "\n[... mais ocorrências; restrinja a pasta]"
            return saida, args, None
        if nome == "listar_pasta":
            r = leitura_repo.listar_pasta(args.get("caminho") or ".", raiz)
            return "\n".join(r["itens"]) or "(vazia)", args, None
        if nome == "ler_arquivo":
            r = leitura_repo.ler_arquivo(args.get("caminho"), int(args.get("inicio") or 1),
                                         int(args.get("fim") or leitura_repo.MAX_LINHAS_ARQUIVO), raiz)
            corpo = "\n".join(f"{r['inicio'] + i:>5}| {l}" for i, l in enumerate(r["texto"].split("\n")))
            saida = f"### {r['caminho']} (linhas {r['inicio']}-{r['fim']} de {r['total_linhas']})\n{corpo}"
            return saida, args, [r["caminho"], r["inicio"], r["fim"]]
        return f"RECUSADO: ferramenta desconhecida: {nome}", args, None
    except leitura_repo.Recusado as erro:
        return f"RECUSADO: {erro}", args, None
    except (TypeError, ValueError) as erro:
        return f"ERRO: {type(erro).__name__}: {erro}", args, None


def _somar_medicao(total: dict, parcial: dict | None) -> dict:
    """Soma prefill e geração de várias voltas; as taxas são recalculadas."""
    if not parcial:
        return total
    if not total:
        return dict(parcial)
    soma = {k: round(total.get(k, 0) + parcial.get(k, 0), 1) if k.endswith("_ms") else total.get(k, 0) + parcial.get(k, 0)
            for k in ("prefill_ms", "prefill_tok", "cache_tok", "prompt_tok", "geracao_ms", "geracao_tok")}
    soma["tok_s_prefill"] = round(soma["prefill_tok"] / (soma["prefill_ms"] / 1000), 2) if soma["prefill_ms"] else None
    soma["tok_s_geracao"] = round(soma["geracao_tok"] / (soma["geracao_ms"] / 1000), 2) if soma["geracao_ms"] else None
    return soma


def _proximo_id(base: str) -> str:
    n = 1
    while (pasta() / chave_modelo() / f"{base}-r{n}.txt").exists():
        n += 1
    return f"{base}-r{n}"


MAX_EXIGE = 5


def validar_exige(exige: dict | None) -> dict:
    """O que a resposta precisa conter: {expressão regular: explicação}."""
    exige = exige or {}
    if len(exige) > MAX_EXIGE:
        raise BancadaErro(422, "exige_demais", f"no máximo {MAX_EXIGE} itens em exige")
    for padrao, explicacao in exige.items():
        if len(padrao) > 200 or len(str(explicacao)) > 200:
            raise BancadaErro(422, "exige_longo", "cada item de exige tem até 200 caracteres")
        try:
            re.compile(padrao)
        except re.error as erro:
            raise BancadaErro(422, "exige_invalido", f"expressão inválida em exige: {padrao!r}") from erro
    return {str(k): str(v) for k, v in exige.items()}


def _com_sistema(mensagens: list, ferramentas: bool) -> list:
    return ([{"role": "system", "content": SISTEMA_FERRAMENTAS}] + mensagens) if ferramentas else mensagens


def preparar_execucao(ident: str, instrucao: str, trechos: list, max_tokens: int,
                      exige: dict | None = None, espera_diff: bool = False,
                      ferramentas: bool = False, raiz: Path | None = None) -> dict:
    if not ID_VALIDO.match(ident or ""):
        raise BancadaErro(422, "id_invalido", "use letras, números, _ ou - (até 80)")
    if (pasta() / chave_modelo() / f"{ident}.txt").exists():
        raise BancadaErro(409, "id_existente", f"já existe a proposta {ident} para {chave_modelo()}")
    prompt, normalizados = montar_prompt(instrucao, trechos, raiz)
    return {"raiz": str(raiz) if raiz else None, "id": ident, "instrucao": instrucao.strip(), "trechos": normalizados, "prompt": prompt,
            "mensagens": _com_sistema([{"role": "user", "content": prompt}], ferramentas),
            "max_tokens": max(64, min(int(max_tokens or 1024), MAX_TOKENS)), "origem_de": None,
            "exige": validar_exige(exige), "espera_diff": bool(espera_diff), "ferramentas": bool(ferramentas)}


def preparar_reenvio(modelo: str, ident: str, prompt_correcao: str) -> dict:
    meta = ler_meta(ident)
    if meta is None or meta.get("modelo") != modelo:
        raise BancadaErro(409, "sem_tarefa", "só dá para reenviar proposta criada pela página")
    if not prompt_correcao or not prompt_correcao.strip():
        raise BancadaErro(422, "prompt_vazio", "o prompt de reenvio está vazio")
    if len(prompt_correcao) > MAX_PROMPT_REENVIO:
        raise BancadaErro(422, "prompt_longo", f"prompt acima de {MAX_PROMPT_REENVIO} caracteres")
    anterior = (pasta() / modelo / f"{ident}.txt").read_text(encoding="utf-8")
    raiz = meta.get("origem_raiz") or ident
    ferramentas = bool(meta.get("ferramentas"))
    return {"raiz": meta.get("raiz"), "id": _proximo_id(raiz), "instrucao": meta["instrucao"], "trechos": meta["trechos"],
            "prompt": meta["prompt"],
            "mensagens": _com_sistema([{"role": "user", "content": meta["prompt"]},
                                       {"role": "assistant", "content": anterior},
                                       {"role": "user", "content": prompt_correcao.strip() + "\n\n" + meta["prompt"]}],
                                      ferramentas),
            "max_tokens": meta.get("max_tokens", 1024), "origem_de": ident, "origem_raiz": raiz,
            "prompt_correcao": prompt_correcao.strip(),
            "exige": meta.get("exige") or {}, "espera_diff": bool(meta.get("espera_diff")),
            "ferramentas": ferramentas}


def executar(plano: dict) -> Iterator[str]:
    """Gera eventos SSE. O lock é tomado aqui e solto no fim do fluxo."""
    try:
        yield from _executar(plano)
    except BancadaErro as erro:
        yield _sse({"tipo": "erro", "codigo": erro.codigo, "mensagem": erro.mensagem})


def _executar(plano: dict) -> Iterator[str]:
    with _lock_execucao():
        if not llama_no_ar():
            yield _sse({"tipo": "erro", "codigo": "modelo_desligado", "mensagem": "O modelo local está desligado. Use Ligar."})
            return
        raiz = Path(plano["raiz"]) if plano.get("raiz") else None
        chave, base = chave_modelo(), commit_base(raiz)
        yield _sse({"tipo": "inicio", "id": plano["id"], "modelo": chave, "base": base})
        inicio, texto, tokens, retentativa, suspeitos = time.monotonic(), "", None, False, []
        medicao: dict = {}
        # Com ferramentas, a conversa cresce a cada volta e o que o modelo leu
        # entra no que o vigia aceita como conhecido.
        mensagens, conhecido = list(plano["mensagens"]), plano["prompt"]
        leituras: list[dict] = []
        trechos = [list(t) for t in plano["trechos"]]
        voltas = contexto = 0
        try:
            while True:
                usar = plano.get("ferramentas") and voltas < MAX_VOLTAS_FERRAMENTA and contexto < MAX_CONTEXTO_FERRAMENTA
                texto, chamadas = "", []
                extra = {"tools": FERRAMENTAS_WORKSPACE} if usar else {}
                for evento in _stream_llama(mensagens, plano["max_tokens"], conhecido, vigiar=True, **extra):
                    if evento["tipo"] == "token":
                        texto += evento["texto"]
                        yield _sse(evento)
                    elif evento["tipo"] == "interrompido":
                        retentativa, suspeitos = True, evento["nomes"]
                        yield _sse({"tipo": "vigia", "nomes": suspeitos,
                                    "mensagem": "nome que não está nos trechos; reenviando 1 vez"})
                    else:
                        tokens = evento["tokens"]
                        medicao = _somar_medicao(medicao, evento.get("medicao")) if voltas else (evento.get("medicao") or medicao)
                        chamadas = evento.get("chamadas") or []
                if retentativa or not chamadas:
                    break
                voltas += 1
                mensagens.append({"role": "assistant", "content": texto, "tool_calls": chamadas})
                for chamada in chamadas:
                    saida, args, lido = _ferramenta(chamada, raiz)
                    saida = saida if len(saida) <= MAX_SAIDA_FERRAMENTA else (
                        saida[:MAX_SAIDA_FERRAMENTA] + f"\n[... cortado: {len(saida) - MAX_SAIDA_FERRAMENTA} caracteres]")
                    contexto += len(saida)
                    conhecido += "\n" + saida
                    if lido and lido not in trechos and len(trechos) < MAX_TRECHOS_REGISTRADOS:
                        trechos.append(lido)
                    nome = (chamada.get("function") or {}).get("name") or "?"
                    leituras.append({"nome": nome, "argumentos": args, "caracteres": len(saida)})
                    mensagens.append({"role": "tool", "tool_call_id": chamada.get("id") or nome, "content": saida})
                    yield _sse({"tipo": "ferramenta", "nome": nome, "argumentos": args, "caracteres": len(saida),
                                "recusada": saida.startswith(("RECUSADO", "ERRO"))})
                if voltas >= MAX_VOLTAS_FERRAMENTA or contexto >= MAX_CONTEXTO_FERRAMENTA:
                    mensagens.append({"role": "user", "content": AVISO_LIMITE_FERRAMENTA})
                    yield _sse({"tipo": "limite", "voltas": voltas, "caracteres": contexto})
                yield _sse({"tipo": "reinicio"})
            if retentativa:
                nomes = ", ".join(f"`{n}`" for n in suspeitos)
                mensagens = mensagens + [
                    {"role": "assistant", "content": texto},
                    {"role": "user", "content": f"Pare. {nomes} não existe nos trechos fornecidos. Refaça a "
                                                "resposta inteira usando só nomes que aparecem nos trechos abaixo. "
                                                "Se faltar informação, diga exatamente o que falta.\n\n" + plano["prompt"]}]
                texto = ""
                yield _sse({"tipo": "reinicio"})
                for evento in _stream_llama(mensagens, plano["max_tokens"], plano["prompt"], vigiar=False):
                    if evento["tipo"] == "token":
                        texto += evento["texto"]
                        yield _sse(evento)
                    elif evento["tipo"] == "tokens":
                        tokens = evento["tokens"]
                        medicao = _somar_medicao(medicao, evento.get("medicao")) if voltas else (evento.get("medicao") or medicao)
        except (urllib.error.URLError, OSError, ValueError) as erro:
            yield _sse({"tipo": "erro", "codigo": "falha_modelo", "mensagem": f"{type(erro).__name__}: {erro}"})
            return
        segundos = round(time.monotonic() - inicio, 1)
        destino = pasta() / chave
        _gravar(destino / f"{plano['id']}.txt", texto.strip() + "\n")
        resumo_path = destino / "_resumo.json"
        try:
            resumo = json.loads(resumo_path.read_text())
        except (OSError, ValueError):
            resumo = {}
        resumo[plano["id"]] = {"segundos": segundos, "tokens": tokens, "ok": True, "retentativa": retentativa,
                               "suspeitos": suspeitos, "origem": "pagina", "medicao": medicao,
                               "leituras": len(leituras), "data": _agora()}
        _gravar(resumo_path, resumo)
        _gravar(pasta() / "tarefas" / f"{plano['id']}.json", {
            "id": plano["id"], "modelo": chave, "base": base, "instrucao": plano["instrucao"],
            # Os trechos que o modelo leu entram aqui: verificar e parecer olham o mesmo que ele viu.
            "trechos": trechos, "prompt": plano["prompt"], "max_tokens": plano["max_tokens"],
            "origem_de": plano.get("origem_de"), "origem_raiz": plano.get("origem_raiz"),
            "prompt_correcao": plano.get("prompt_correcao"), "exige": plano.get("exige") or {},
            "espera_diff": bool(plano.get("espera_diff")), "ferramentas": bool(plano.get("ferramentas")),
            "raiz": plano.get("raiz"),
            "leituras": leituras, "data": _agora()})
        registrar({"id": plano["id"], "modelo": chave, "origem": "pagina", "tipo": "execucao",
                   "segundos": segundos, "tokens": tokens, "retentativa": retentativa,
                   "medicao": medicao, "origem_de": plano.get("origem_de"), "leituras": len(leituras)})
        yield _sse({"tipo": "fim", "id": plano["id"], "modelo": chave, "segundos": segundos,
                    "tokens": tokens, "retentativa": retentativa, "medicao": medicao, "leituras": len(leituras)})


# ---------------------------------------------------------------- verificar / parecer

def ler_meta(ident: str) -> dict | None:
    if not ID_VALIDO.match(ident or ""):
        return None
    try:
        return json.loads((pasta() / "tarefas" / f"{ident}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _proposta(modelo: str, ident: str) -> tuple[dict, str]:
    meta = ler_meta(ident)
    if meta is None or meta.get("modelo") != modelo:
        raise BancadaErro(409, "sem_tarefa", "proposta sem tarefa registrada pela página; use a CLI")
    arquivo = pasta() / modelo / f"{ident}.txt"
    if not arquivo.is_file():
        raise BancadaErro(404, "nao_encontrada", "proposta não encontrada")
    return meta, arquivo.read_text(encoding="utf-8")


def verificar(modelo: str, ident: str) -> dict:
    meta, texto = _proposta(modelo, ident)
    checks = _modulo("bancada_checks")
    tarefa = {"base": meta["base"], "trechos": meta["trechos"],
              "escopo": sorted({c for c, *_ in meta["trechos"]}), "exige": meta.get("exige") or {},
              "espera_diff": bool(meta.get("espera_diff"))}
    resultado = checks.verificar(texto, tarefa)
    _gravar(pasta() / "verificacoes" / f"{ident}.json", {
        "id": ident, "modelo": modelo, "tarefa": "pagina", "base": meta["base"], "proposta": texto[:20000],
        **resultado, "data": _agora()})
    return resultado


SEGUNDA_OPINIAO = "segunda-opiniao"


def observers() -> dict:
    obs = _modulo("bancada_observer")
    return {"padrao": obs.PADRAO, "observers": list(obs.OBSERVERS),
            "segunda_opiniao": {"id": SEGUNDA_OPINIAO, "primario": obs.SEGUNDA_OPINIAO_PRIMARIO,
                                "arbitro": obs.SEGUNDA_OPINIAO_ARBITRO}}


def parecer(modelo: str, ident: str, observer: str | None = None) -> dict:
    if observer == SEGUNDA_OPINIAO:
        return segunda_opiniao(modelo, ident)
    meta, texto = _proposta(modelo, ident)
    obs = _modulo("bancada_observer")
    observer = observer or obs.PADRAO
    if observer not in obs.OBSERVERS:
        raise BancadaErro(422, "observer_invalido", "observer fora da lista do comparativo")
    try:
        verificacao = json.loads((pasta() / "verificacoes" / f"{ident}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        verificacao = {**verificar(modelo, ident)}
    # Proposta feita na cópia de uma sessão: o observer lê os mesmos trechos, se a cópia ainda existe.
    raiz = Path(meta["raiz"]) if meta.get("raiz") and Path(meta["raiz"]).is_dir() else None
    trechos = "\n\n".join(f"### {c} (linhas {i}-{f})\n```\n{ler_trecho(c, i, f, raiz)[0]}\n```" for c, i, f in meta["trechos"])
    resultado = obs.observar(observer, obs.montar_mensagens(meta["instrucao"], trechos, texto, verificacao))
    _gravar(pasta() / "pareceres" / f"{ident}__{observer.replace('/', '--')}.json", {
        "id": ident, "modelo": modelo, "observer": observer, **resultado, "data": _agora()})
    registrar({"id": ident, "modelo": modelo, "origem": "observer", "observer": observer, "ok": resultado["ok"],
               "veredito": (resultado["parecer"] or {}).get("veredito", "falhou"),
               "erros": [e.get("categoria") for e in (resultado["parecer"] or {}).get("erros", [])],
               "custo_usd": resultado["custo_usd"], "segundos": resultado["segundos"], "falhas": resultado["falhas"]})
    return resultado


def segunda_opiniao(modelo: str, ident: str) -> dict:
    """Primário decide sozinho quando diz "aproveitada"; senão o árbitro dá a palavra final.

    Se o árbitro falhar, fica o veredito do primário. Cada parecer é gravado e
    registrado normalmente; aqui só se soma custo/tempo e se diz quem decidiu.
    """
    obs = _modulo("bancada_observer")
    primario, arbitro = obs.SEGUNDA_OPINIAO_PRIMARIO, obs.SEGUNDA_OPINIAO_ARBITRO
    etapas = [parecer(modelo, ident, primario)]
    veredito = (etapas[0]["parecer"] or {}).get("veredito")
    decidido_por = primario
    if etapas[0]["ok"] and veredito != "aproveitada":
        etapas.append(parecer(modelo, ident, arbitro))
        if etapas[1]["ok"]:
            decidido_por = arbitro
    elif not etapas[0]["ok"]:
        etapas.append(parecer(modelo, ident, arbitro))
        decidido_por = arbitro if etapas[1]["ok"] else None
    final = next((e for e, nome in zip(etapas, (primario, arbitro)) if nome == decidido_por), etapas[-1])
    return {**final, "custo_usd": round(sum(e["custo_usd"] or 0 for e in etapas), 6),
            "segundos": round(sum(e["segundos"] or 0 for e in etapas), 1),
            "decidido_por": decidido_por,
            "etapas": [{"observer": nome, "ok": e["ok"], "veredito": (e["parecer"] or {}).get("veredito")}
                       for e, nome in zip(etapas, (primario, arbitro))]}


# ---------------------------------------------------------------- ligar / desligar

def ligar_desligar(acao: str) -> dict:
    from app.services import agent_lifecycle
    if acao == "desligar" and ocupado():
        raise BancadaErro(409, "ocupado", "há uma execução em andamento; espere terminar para desligar")
    ok = agent_lifecycle._llama_service("start" if acao == "ligar" else "stop")
    if not ok:
        raise BancadaErro(502, "falha_servico", f"não foi possível {acao} o modelo local")
    return {"acao": acao, "ok": True}


# ---------------------------------------------------------------- planejador

def preparar_planejamento(tarefa_id: str | None, prompt: str | None, modelo: str) -> dict:
    """Prepara um plano de tarefas via OpenRouter.

    Retorna um dict com o plano para `planejar_stream()` consumir.
    """
    if not tarefa_id and not prompt:
        raise BancadaErro(422, "entrada_vazia", "forneça task_id ou prompt")
    return {"tipo": "planejar", "tarefa_id": tarefa_id, "prompt": prompt, "modelo": modelo}


def planejar_stream(plano: dict) -> Iterator[str]:
    """Gera eventos SSE para o planejamento.

    Chama bancada_planner.planejar_stream() e traduz para SSE.
    """
    try:
        yield from _planejar(plano)
    except Exception as erro:
        yield _sse({"tipo": "erro", "codigo": "erro_interno", "mensagem": str(erro)})


def _planejar(plano: dict) -> Iterator[str]:
    """Orquestra o planejamento com lock."""
    planner = _modulo("bancada_planner")
    with _lock_execucao():
        for evento in planner.planejar_stream(plano["tarefa_id"], plano["prompt"], plano["modelo"]):
            if evento["tipo"] == "erro":
                yield _sse(evento)
                return
            elif evento["tipo"] == "ok":
                tarefas = evento["tarefas"]
                tokens = evento.get("tokens")
                # Mesma pasta e mesmo id de lote (AAMMDD-NN) do `planejar` da CLI.
                ident_plano = _modulo("bancada_local").proximo_lote(pasta() / "planos")
                _gravar(pasta() / "planos" / f"{ident_plano}.json", {
                    "id": ident_plano, "lote": ident_plano, "tarefas": tarefas, "tokens": tokens,
                    "modelo": plano["modelo"], "origem_tarefa": plano.get("tarefa_id"),
                    "origem_prompt": (plano.get("prompt") or "")[:500], "data": _agora()
                })
                yield _sse({"tipo": "ok", "id": ident_plano, "tarefas": tarefas, "tokens": tokens})
            else:
                yield _sse(evento)
