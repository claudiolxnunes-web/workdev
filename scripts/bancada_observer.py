"""Observer LLM da Bancada Local: árbitro depois das checagens mecânicas.

Recebe a proposta, os trechos reais e o resultado do `verificar` e devolve um
parecer em JSON. Nunca reenvia nada ao modelo local: quem decide é o operador.
A chave da OpenRouter é lida direto do arquivo de ambiente, só essa variável,
e nunca é impressa nem gravada.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from bancada_checks import CATEGORIAS

URL = "https://openrouter.ai/api/v1/chat/completions"
ARQUIVOS_DE_CHAVE = (Path("/etc/workdev/workdev-api.env"),)
VEREDITOS = ("aproveitada", "correcao_pequena", "descartada")

# Observer padrão: GPT-5.6 Luna (melhor veredito e prompt no comparativo, 0 falhas).
PADRAO = "openai/gpt-5.6-luna"
# Saída generosa: modelos que raciocinam gastavam os 1500 tokens antes do JSON.
MAX_TOKENS = 4000

# Observers do comparativo (slugs e preços conferidos no catálogo em 2026-10-01).
OBSERVERS = {
    "openai/gpt-5.6-luna": {"reasoning": {"effort": "medium"}},
    "deepseek/deepseek-v4-flash": {},
    "qwen/qwen3-coder-next": {},
    "mistralai/codestral-2508": {},
}


# Segunda opinião: o primário (rápido e barato, rígido) decide quando diz
# "aproveitada"; nos demais casos o árbitro (mais calibrado na severidade) decide.
SEGUNDA_OPINIAO_PRIMARIO = "mistralai/codestral-2508"
SEGUNDA_OPINIAO_ARBITRO = "openai/gpt-5.6-luna"


class ObserverFalhou(RuntimeError):
    pass


def _chave() -> str:
    valor = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if valor:
        return valor
    for arquivo in ARQUIVOS_DE_CHAVE:
        try:
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if linha.startswith("OPENROUTER_API_KEY="):
                    return linha.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            continue
    raise ObserverFalhou("OPENROUTER_API_KEY não encontrada (ambiente ou /etc/workdev/workdev-api.env)")


SISTEMA = (
    "Você é o árbitro de uma proposta de código feita por um modelo local. Não reescreva a "
    "solução. Use os trechos reais e o resultado das checagens mecânicas, que são a verdade "
    "sobre o código (aplica ou não, compila ou não, nomes existem ou não). Aponte só erros "
    "que você consegue sustentar com os trechos; não invente problemas. Responda SÓ com um "
    "objeto JSON, sem texto em volta."
)


def montar_mensagens(instrucao: str, trechos: str, proposta: str, checagens: dict) -> list[dict]:
    categorias = "\n".join(f"- {nome}: {descricao}" for nome, descricao in CATEGORIAS.items())
    achados = [a for a in checagens["achados"] if a["severidade"] != "info"]
    pedido = (
        f"## Enunciado dado ao modelo local\n{instrucao}\n\n"
        f"## Trechos reais do código\n{trechos}\n\n"
        f"## Proposta do modelo local\n{proposta}\n\n"
        f"## Checagens mecânicas\n{json.dumps(achados, ensure_ascii=False, indent=1) or '[]'}\n\n"
        "## Responda com este JSON\n"
        '{"veredito": "aproveitada|correcao_pequena|descartada",\n'
        ' "erros": [{"categoria": "<uma das categorias>", "descricao": "<curta, citando o nome real>"}],\n'
        ' "prompt_correcao": "<prompt curto para o modelo local corrigir, ou vazio se aproveitada>"}\n\n'
        f"Categorias permitidas:\n{categorias}\n\n"
        "aproveitada = aplica e cumpre o enunciado; correcao_pequena = ideia certa, ajuste "
        "localizado; descartada = não cumpre o enunciado ou exige refazer."
    )
    return [{"role": "system", "content": SISTEMA}, {"role": "user", "content": pedido}]


def _post(corpo: dict, timeout: float) -> dict:
    req = urllib.request.Request(URL, data=json.dumps(corpo).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {_chave()}",
        "X-Title": "WorkDev Bancada Local"})
    with urllib.request.urlopen(req, timeout=timeout) as resposta:
        return json.loads(resposta.read())


def _json_da_resposta(texto: str) -> dict:
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim < inicio:
        raise ValueError("resposta sem objeto JSON")
    dados = json.loads(texto[inicio:fim + 1])
    if dados.get("veredito") not in VEREDITOS:
        raise ValueError(f"veredito inválido: {dados.get('veredito')!r}")
    dados["erros"] = [e for e in dados.get("erros") or [] if isinstance(e, dict)]
    dados["prompt_correcao"] = str(dados.get("prompt_correcao") or "")
    return dados


def observar(modelo: str, mensagens: list[dict], timeout: float = 180) -> dict:
    """Uma chamada ao observer; no máximo 1 retentativa em falha de rede ou de JSON."""
    extra = OBSERVERS.get(modelo, {})
    corpo = {"model": modelo, "messages": mensagens, "temperature": 0, "max_tokens": MAX_TOKENS,
             "usage": {"include": True}, "response_format": {"type": "json_object"}, **extra}
    falhas: list[str] = []
    custo = 0.0  # inclui tentativas pagas que vieram com JSON inválido
    for tentativa in (1, 2):
        inicio = time.monotonic()
        try:
            resposta = _post(corpo, timeout)
            segundos = round(time.monotonic() - inicio, 1)
            if "error" in resposta:
                raise ObserverFalhou(str(resposta["error"].get("message", resposta["error"]))[:300])
            uso = resposta.get("usage") or {}
            custo += float(uso.get("cost") or 0)
            texto = resposta["choices"][0]["message"].get("content") or ""
            parecer = _json_da_resposta(texto)
            return {"ok": True, "parecer": parecer, "segundos": segundos, "tentativas": tentativa,
                    "tokens_entrada": uso.get("prompt_tokens"), "tokens_saida": uso.get("completion_tokens"),
                    "custo_usd": round(custo, 6), "falhas": falhas}
        except urllib.error.HTTPError as erro:
            corpo_erro = erro.read().decode("utf-8", "replace")[:300]
            falhas.append(f"HTTP {erro.code}: {corpo_erro}")
            if erro.code == 400 and "response_format" in corpo:
                # Provedor sem modo JSON: a retentativa vai sem ele.
                corpo = {k: v for k, v in corpo.items() if k != "response_format"}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, ObserverFalhou) as erro:
            falhas.append(f"{type(erro).__name__}: {str(erro)[:300]}")
    return {"ok": False, "parecer": None, "segundos": None, "tentativas": 2,
            "tokens_entrada": None, "tokens_saida": None, "custo_usd": round(custo, 6), "falhas": falhas}
