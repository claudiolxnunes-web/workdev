"""Priorização e explicação por LLM — uma chamada, sem tools, sem descoberta.

O que o modelo recebe: fatos já produzidos deterministicamente, redigidos,
serializados em JSON.

O que o modelo devolve: ordem de prioridade e quatro campos de prosa por
achado, referenciando cada um por `id`.

O que o modelo **não** tem: tools, banco, shell, git, filesystem, rede. A
chamada é um `messages.create` com `output_config.format` — nenhuma
ferramenta é declarada, então não existe caminho pelo qual ele possa agir.

O que o modelo **não pode alterar**: `severity`, `entity_id`, `bucket`,
`evidencia`, `fingerprint`, `status`. Esses campos são copiados dos Fatos
depois da resposta, não lidos dela. Um `id` que não existe na entrada é
descartado e contado.

Se a chamada falhar — timeout, 429, 5xx, refusal, schema inválido, chave
ausente — a execução continua com a ordem determinística e prosa vazia. O
Supervisor nunca deixa de entregar por causa do modelo.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Sequence

from dotenv import load_dotenv

from . import config
from .modelo import Achado, ordenar_achados
from .redacao import redigir


SYSTEM = """Você é a camada de priorização de um supervisor de engenharia somente-leitura.

Recebe fatos já apurados deterministicamente sobre uma plataforma de software
(backlog, planos de execução, estado de deploy, base de conhecimento, agentes).
Sua função é decidir o que merece atenção primeiro e explicar por quê.

Regras:
- Trabalhe apenas com os fatos recebidos. Não invente números, datas, nomes de
  arquivo, tabelas ou causas que não estejam nos dados.
- Não repita o título do achado no campo `impacto`; acrescente o que o título
  não diz.
- `acao_sugerida` é uma frase para um humano executar, nunca um comando
  destrutivo, nunca algo que você mesmo faria.
- Se dois achados forem manifestações do mesmo problema, diga isso em `risco`.
- Prioridade 1 é o mais urgente. Use cada valor uma única vez.
- Português do Brasil, direto, sem preâmbulo. Cada campo em uma ou duas frases.
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resumo", "achados"],
    "properties": {
        "resumo": {
            "type": "string",
            "description": "Uma ou duas frases sobre o conjunto, não sobre um achado.",
        },
        "achados": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "prioridade",
                    "impacto",
                    "risco",
                    "recomendacao",
                    "acao_sugerida",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "prioridade": {"type": "integer"},
                    "impacto": {"type": "string"},
                    "risco": {"type": "string"},
                    "recomendacao": {"type": "string"},
                    "acao_sugerida": {"type": "string"},
                },
            },
        },
    },
}


@dataclass
class ResultadoLLM:
    """Tudo que a etapa do LLM produz, inclusive quando ela não acontece."""

    achados: list[Achado] = field(default_factory=list)
    resumo: str | None = None
    chamadas: int = 0
    falhas: int = 0
    modelo: str | None = None
    tokens_entrada: int = 0
    tokens_saida: int = 0
    ids_invalidos: int = 0
    ids_ausentes: int = 0
    erro: str | None = None

    @property
    def custo_usd(self) -> float:
        entrada, saida = config.LLM_PRECOS_USD_POR_MTOK.get(self.modelo or "", (0.0, 0.0))
        return (
            self.tokens_entrada * entrada + self.tokens_saida * saida
        ) / 1_000_000


def payload(achados: Sequence[Achado]) -> dict[str, Any]:
    """Só o necessário para julgar. Sem evidência de credencial, sem conteúdo."""
    return {
        "instrucao": (
            "Ordene por urgência real e explique cada achado. Responda usando "
            "exatamente os ids recebidos."
        ),
        "achados": [
            {
                "id": achado.fingerprint,
                "check": achado.check,
                "subcheck": achado.subcheck,
                "severidade": achado.severity,
                "estado": achado.status,
                "projeto": achado.project_name,
                "titulo": achado.titulo,
                "medidas": achado.medidas,
                "ocorrencias": achado.ocorrencias,
                "visto_desde": achado.first_seen_at,
                "faixa": achado.bucket,
                "faixa_anterior": achado.bucket_anterior,
                "como_verificar": list(achado.evidencia),
            }
            for achado in achados
        ],
    }


def _cliente(modelo: str, cliente: Any | None):
    if cliente is not None:
        return cliente
    import anthropic

    load_dotenv(config.ENV_FILE)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY ausente")
    return anthropic.Anthropic(timeout=config.LLM_TIMEOUT_SEGUNDOS)


def priorizar(
    achados: Sequence[Achado],
    modelo: str | None = None,
    cliente: Any | None = None,
) -> ResultadoLLM:
    """Uma chamada, no máximo. Nunca levanta exceção para o chamador."""
    escolhidos = ordenar_achados(achados)[: config.LLM_MAX_FATOS]
    modelo = modelo or config.LLM_MODELO
    resultado = ResultadoLLM(achados=list(escolhidos), modelo=modelo)

    if not escolhidos:
        return resultado

    try:
        api = _cliente(modelo, cliente)
        resposta = api.messages.create(
            model=modelo,
            max_tokens=config.LLM_MAX_TOKENS,
            system=SYSTEM,
            # Sem `tools`: não há ferramenta declarada, logo não há ação
            # possível. Sem `thinking: disabled`, que no Opus 5 induz vazamento
            # de tag e chamada de tool em texto.
            output_config={
                "effort": config.LLM_EFFORT,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(payload(escolhidos), ensure_ascii=False),
                }
            ],
        )
        resultado.chamadas = 1
        uso = getattr(resposta, "usage", None)
        resultado.tokens_entrada = int(getattr(uso, "input_tokens", 0) or 0)
        resultado.tokens_saida = int(getattr(uso, "output_tokens", 0) or 0)

        if getattr(resposta, "stop_reason", None) == "refusal":
            raise RuntimeError("resposta recusada pelo modelo")

        dados = _extrair_json(resposta)
        _aplicar(resultado, escolhidos, dados)
    except Exception as erro:  # noqa: BLE001 — o LLM nunca derruba a execução
        resultado.falhas = 1
        resultado.erro = f"{type(erro).__name__}"
        resultado.resumo = None
        _fallback(escolhidos)

    return resultado


def _extrair_json(resposta: Any) -> dict[str, Any]:
    texto = next(
        (bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"),
        None,
    )
    if not texto:
        raise ValueError("resposta sem bloco de texto")
    dados = json.loads(texto)
    if not isinstance(dados, dict) or not isinstance(dados.get("achados"), list):
        raise ValueError("formato inesperado")
    return dados


def _aplicar(
    resultado: ResultadoLLM, achados: Sequence[Achado], dados: dict[str, Any]
) -> None:
    """Copia prosa e prioridade para os Achados, validando cada id."""
    por_id = {achado.fingerprint: achado for achado in achados}
    atendidos: set[str] = set()

    for item in dados.get("achados") or []:
        if not isinstance(item, dict):
            resultado.ids_invalidos += 1
            continue
        alvo = por_id.get(item.get("id"))
        if alvo is None:
            # O modelo citou um achado que não existe. Descartado e contado —
            # nunca acrescentado à saída.
            resultado.ids_invalidos += 1
            continue
        alvo.prioridade = _inteiro(item.get("prioridade"))
        alvo.impacto = _texto(item.get("impacto"))
        alvo.risco = _texto(item.get("risco"))
        alvo.recomendacao = _texto(item.get("recomendacao"))
        alvo.acao_sugerida = _texto(item.get("acao_sugerida"))
        atendidos.add(alvo.fingerprint)

    faltantes = [a for a in achados if a.fingerprint not in atendidos]
    resultado.ids_ausentes = len(faltantes)
    if faltantes:
        # Achado que o modelo ignorou não some do relatório: recebe a posição
        # determinística e segue sem prosa.
        _fallback(faltantes, inicio=len(atendidos) + 1)

    resultado.resumo = _texto(dados.get("resumo"))


def _fallback(achados: Sequence[Achado], inicio: int = 1) -> None:
    """Ordem determinística por severidade — o caminho quando não há LLM."""
    for posicao, achado in enumerate(ordenar_achados(achados), start=inicio):
        achado.prioridade = posicao


def _texto(valor: Any) -> str | None:
    """Texto do modelo passa pela mesma redação que o resto da saída.

    Improvável que ele ecoe um segredo — não recebe nenhum — mas a varredura
    é fail-closed por princípio, e a saída do LLM não é exceção.
    """
    if not isinstance(valor, str):
        return None
    limpo = redigir(valor.strip())
    return limpo or None


def _inteiro(valor: Any) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None
