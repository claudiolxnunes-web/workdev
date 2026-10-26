"""Ponto único de montagem do contexto canônico entregue ao agente.

Por que este módulo existe (ADR 010): o contexto canônico — ADR, knowledge e
decisions do projeto — era recolhido pelo `build_context` e injetado no
prompt por `build_rag.augment_prompt`, que só era chamado em **dois** dos
quatro caminhos de despacho. O caminho AUTO (tmux) e o `local-code` entregavam
ao agente um prompt sem nenhuma referência canônica, e nada no log, no evento
ou no status dizia isso: era falha silenciosa.

A regra agora é uma só — **todo prompt de agente passa por aqui**.

O módulo não decide o que é canônico (isso é do `build_rag`), não consulta o
banco (isso é do `build_context`) e não decide o que pode sair da máquina (isso
é do `context_egress`). Ele monta, no lugar certo, e aplica a política de
segredo quando a entrega é local.

Duas portas, porque a política de egresso é diferente nos dois casos:

- `build_prompt` — entrega remota. Não redige: quem redige é o
  `context_egress.prepare`, que precisa contar o que retirou e registrar na
  trilha da run. Redigir aqui zeraria a contagem do evento.
- `build_local_prompt` — entrega local (AUTO por tmux, `local-code`). Aplica
  a mesma `context_redaction.redact`, porque o texto não sai da máquina mas
  chega a um modelo, e o contexto canônico é texto que o operador escreveu ao
  longo de meses (ADR 012).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services import build_rag
from app.services.context_redaction import RedactionResult, redact


@dataclass(frozen=True)
class PromptMontado:
    """Prompt montado e o que a política de segredo retirou dele."""

    text: str
    redaction: RedactionResult

    @property
    def redacted(self) -> bool:
        return self.redaction.redacted


def canonical_block(context: dict) -> str:
    """Bloco de trechos canônicos (ADR, knowledge, decision), em texto plano.

    Vazio quando nada casa com o vocabulário da task/plano — e nesse caso o
    prompt sai sem bloco, e não com um bloco vazio.
    """
    return build_rag.render_snippets(
        build_rag.select_snippets(context)
    )


def build_prompt(context: dict, *, suffix: str = "") -> str:
    """Prompt do agente: base + bloco canônico + sufixo.

    Sem redaction — nos caminhos remotos a política é do `context_egress`, que
    precisa contar o que retirou. Redigir aqui zeraria a contagem do evento
    `build.context_redacted`.
    """
    partes = [context.get("prompt") or ""]

    bloco = canonical_block(context)
    if bloco:
        partes.append(bloco)

    if suffix:
        partes.append(suffix)

    return "\n\n".join(partes)


def build_local_prompt(context: dict, *, suffix: str = "") -> PromptMontado:
    """Prompt do agente para entrega local, com a política de segredo aplicada.

    O loopback não sai da máquina, mas o texto chega a um modelo — e o contexto
    canônico é exatamente o texto que pode ter uma chave colada num
    troubleshooting. O custo é um trecho de contexto a menos; segredo não é
    insumo de implementação (ADR 012).
    """
    resultado = redact(build_prompt(context, suffix=suffix))

    return PromptMontado(text=resultado.text, redaction=resultado)
