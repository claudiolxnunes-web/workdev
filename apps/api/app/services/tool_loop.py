"""Guardas do loop de tools do AI Hub (Fase 0).

O loop de `chat_anthropic`/`chat_openai` (routers/ai.py) é o mesmo para o AI
Hub, o chat livre e o supervisor do Workspace. Com modelo local ele fica frágil
em quatro pontos, e cada guarda aqui ataca um:

1. **Argumentos.** Modelo local manda JSON quebrado ou com tipo errado com
   frequência. Antes o `json.loads` ficava fora do `try` e derrubava a
   requisição inteira. Agora parse + validação pelo `input_schema` da tool,
   com coerção do óbvio ("12" → 12); o erro volta ao modelo como resultado
   da tool, para ele corrigir.
2. **Repetição.** A mesma chamada (nome + argumentos) só executa
   `MAX_REPETICOES` vezes; depois o modelo recebe o aviso, e se insistir o
   loop termina com mensagem clara.
3. **Tempo total.** Cada chamada local pode levar 900 s; 12 passos somavam
   até 3 h. O loop tem um prazo total e cada chamada recebe só o que resta.
4. **Tamanho do retorno.** Resultado de tool cortado num teto comum.

Mais: `slot_local` serializa o llama-server (um slot só, `-np 1`) com a
Bancada e a execução do Workspace, e `registrar` grava telemetria por chamada.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_REPETICOES = 2
MAX_RECUSAS_SEGUIDAS = 3
TEMPO_TOTAL_PADRAO = 900
TEMPO_TOTAL_LOCAL_PADRAO = 1800
MAX_CHARS_RESULTADO_PADRAO = 24_000
ESPERA_SLOT_PADRAO = 120
FOLGA_S = 5


class Interromper(Exception):
    """O loop deve parar e devolver `mensagem` ao usuário."""

    def __init__(self, motivo: str, mensagem: str):
        super().__init__(mensagem)
        self.motivo = motivo
        self.mensagem = mensagem


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


# ---------------------------------------------------------------- argumentos


def _coagir(valor, tipo: str):
    """Converte o óbvio; devolve (valor, ok)."""
    if tipo == "string":
        return (valor, True) if isinstance(valor, str) else (str(valor), isinstance(valor, (int, float)))
    if tipo == "integer":
        if isinstance(valor, bool):
            return valor, False
        if isinstance(valor, int):
            return valor, True
        if isinstance(valor, float) and valor.is_integer():
            return int(valor), True
        if isinstance(valor, str) and valor.strip().lstrip("-").isdigit():
            return int(valor.strip()), True
        return valor, False
    if tipo == "number":
        if isinstance(valor, bool):
            return valor, False
        if isinstance(valor, (int, float)):
            return valor, True
        try:
            return float(valor), isinstance(valor, str)
        except (TypeError, ValueError):
            return valor, False
    if tipo == "boolean":
        if isinstance(valor, bool):
            return valor, True
        if isinstance(valor, str) and valor.strip().lower() in ("true", "false"):
            return valor.strip().lower() == "true", True
        return valor, False
    if tipo == "array":
        return valor, isinstance(valor, list)
    if tipo == "object":
        return valor, isinstance(valor, dict)
    return valor, True


def validar(schema: dict | None, args) -> tuple[dict, list[str]]:
    """Valida contra o input_schema (tipos, required, enum). Devolve (args coagidos, erros)."""
    if not isinstance(args, dict):
        return {}, ["os argumentos precisam ser um objeto JSON"]
    schema = schema or {}
    propriedades = schema.get("properties") or {}
    erros, saida = [], dict(args)
    for nome in schema.get("required") or []:
        if nome not in args or args[nome] is None:
            erros.append(f"falta o argumento obrigatório '{nome}'")
    for nome, valor in args.items():
        regra = propriedades.get(nome)
        if not regra or valor is None:
            continue
        tipo = regra.get("type")
        if isinstance(tipo, str):
            convertido, ok = _coagir(valor, tipo)
            if not ok:
                erros.append(f"'{nome}' precisa ser {tipo}, veio {type(valor).__name__}")
                continue
            saida[nome] = convertido
        if "enum" in regra and saida[nome] not in regra["enum"]:
            erros.append(f"'{nome}' precisa ser um de {regra['enum']}")
    return saida, erros


def erro_para_o_modelo(nome: str, erros: list[str], schema: dict | None) -> str:
    return json.dumps({"erro": "argumentos inválidos: " + "; ".join(erros), "code": "argumentos_invalidos",
                       "tool": nome, "esperado": {"required": (schema or {}).get("required") or [],
                                                  "properties": {k: v.get("type") for k, v in
                                                                 ((schema or {}).get("properties") or {}).items()}},
                       "proximo_passo": "Corrija os argumentos e chame de novo."}, ensure_ascii=False)


# ---------------------------------------------------------------- guarda

class Guarda:
    """Uma por conversa (uma ida ao provider com seu loop de tools)."""

    def __init__(self, tools: list[dict], local: bool):
        self.schemas = {t["name"]: t.get("input_schema") for t in tools}
        limite = _env_int("AI_LOCAL_MAX_TOTAL_SECONDS", TEMPO_TOTAL_LOCAL_PADRAO) if local \
            else _env_int("AI_MAX_TOTAL_SECONDS", TEMPO_TOTAL_PADRAO)
        self.limite_s = max(30, limite)
        self.inicio = time.monotonic()
        self.max_chars = _env_int("AI_TOOL_RESULT_MAX_CHARS", MAX_CHARS_RESULTADO_PADRAO)
        self.chamadas: dict[str, int] = {}
        self.recusas_seguidas = 0

    def restante(self) -> float:
        return self.limite_s - (time.monotonic() - self.inicio)

    def prazo(self, por_chamada: float) -> float:
        """Timeout da próxima chamada ao provider; interrompe se o prazo total acabou."""
        resta = self.restante()
        if resta <= FOLGA_S:
            raise Interromper("tempo", f"Parei: o tempo total da conversa ({int(self.limite_s)} s) acabou "
                                       "antes de uma resposta final. Divida o pedido ou use um modelo mais rápido.")
        return max(1.0, min(por_chamada, resta))

    def argumentos(self, nome: str, bruto) -> tuple[dict | None, str | None]:
        """(args validados, None) ou (None, erro para devolver ao modelo como resultado da tool)."""
        if isinstance(bruto, str):
            try:
                bruto = json.loads(bruto or "{}")
            except ValueError as erro:
                return None, json.dumps({"erro": f"argumentos não são JSON válido: {erro}", "code": "json_invalido",
                                         "tool": nome, "proximo_passo": "Mande os argumentos como objeto JSON."},
                                        ensure_ascii=False)
        if nome not in self.schemas:
            # Tool fora do catálogo: quem recusa é o gate de autoridade (camada 2),
            # com a mensagem dele. Aqui só o parse.
            if not isinstance(bruto, dict):
                return None, erro_para_o_modelo(nome, ["os argumentos precisam ser um objeto JSON"], None)
            return bruto, None
        args, erros = validar(self.schemas[nome], bruto)
        if erros:
            return None, erro_para_o_modelo(nome, erros, self.schemas[nome])
        return args, None

    def repetida(self, nome: str, args: dict) -> str | None:
        """Erro para o modelo se a chamada já foi feita demais; Interromper se ele insiste."""
        chave = nome + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        self.chamadas[chave] = self.chamadas.get(chave, 0) + 1
        if self.chamadas[chave] <= MAX_REPETICOES:
            self.recusas_seguidas = 0
            return None
        self.recusas_seguidas += 1
        if self.recusas_seguidas >= MAX_RECUSAS_SEGUIDAS:
            raise Interromper("repeticao", "Parei: o modelo entrou em repetição, chamando a mesma ferramenta com "
                                           "os mesmos argumentos. Reformule o pedido ou troque de modelo.")
        return json.dumps({"erro": f"chamada repetida: '{nome}' com estes argumentos já rodou "
                                   f"{MAX_REPETICOES} vezes", "code": "chamada_repetida",
                           "proximo_passo": "Use o resultado que você já tem ou mude os argumentos."},
                          ensure_ascii=False)

    def truncar(self, saida: str) -> str:
        if len(saida) <= self.max_chars:
            return saida
        return saida[:self.max_chars] + f"\n[... resultado cortado: {len(saida) - self.max_chars} caracteres omitidos]"


# ---------------------------------------------------------------- slot do llama-server

@contextmanager
def slot_local(ativo: bool, espera_s: float | None = None):
    """Uma chamada por vez no llama-server, junto com a Bancada e o Workspace.

    Usa a mesma trava da Bancada (`<pasta da bancada>/.execucao.lock`). Espera
    até `espera_s` em vez de recusar na hora: o chat entra na fila.
    """
    if not ativo:
        yield
        return
    import fcntl

    from app.services import bancada_runner
    espera = ESPERA_SLOT_PADRAO if espera_s is None else espera_s
    pasta = bancada_runner.pasta()
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / ".execucao.lock", "w") as arquivo:
        limite = time.monotonic() + espera
        while True:
            try:
                fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= limite:
                    raise Interromper("ocupado", "O modelo local está ocupado (Bancada ou Workspace executando). "
                                                 "Tente de novo em instantes.") from None
                time.sleep(0.5)
        yield


# ---------------------------------------------------------------- telemetria

def _pasta_telemetria() -> Path:
    destino = os.getenv("AI_TELEMETRIA_DIR")
    if destino:
        return Path(destino)
    # Dentro da pasta da Bancada: tmp/ do checkout é do root e a API roda como workdev.
    from app.services import bancada_runner
    return bancada_runner.pasta() / "ai-telemetria"


def registrar(**campos) -> None:
    """Uma linha JSONL por chamada ao provider. Falha de disco nunca derruba o chat."""
    agora = datetime.now(timezone.utc)
    try:
        pasta = _pasta_telemetria()
        pasta.mkdir(parents=True, exist_ok=True)
        with (pasta / f"{agora:%Y-%m}.jsonl").open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps({"ts": agora.isoformat(timespec="seconds"), **campos},
                                     ensure_ascii=False, default=str) + "\n")
    except OSError:
        return
