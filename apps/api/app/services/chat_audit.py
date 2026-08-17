"""Auditoria das mudanças de contexto de uma conversa (E1.4).

Trocar a autoridade de uma conversa é uma decisão que muda o que a IA pode
fazer dali em diante. Precisa deixar rastro — e o rastro precisa ficar junto
da conversa, não num log que ninguém correlaciona depois.

Sem tabela nova: o evento é uma linha em `chat_messages` com um `role`
próprio. Duas consequências desenhadas de propósito:

- `carregar_sessao` separa eventos de mensagens, então o evento **nunca entra
  no array que vai para o LLM** nem na bolha de conversa da interface;
- o evento herda de graça o `ON DELETE CASCADE` da sessão e o índice por
  `(session_id, created_at)`, que já existiam.

`tool_calls` guarda o par de/para em JSONB, consultável sem parsear texto.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession

ROLE_AUDITORIA = "audit"
EVENTO_AUTORIDADE = "authority.changed"
EVENTO_PROJETO = "project.changed"

# Roles que são conversa de verdade — o que sai daqui não vai para o modelo.
ROLES_CONVERSA = ("user", "assistant")


def registrar_evento(
    db: Session,
    sessao: ChatSession,
    evento: str,
    texto: str,
    detalhe: dict | None = None,
) -> ChatMessage:
    """Grava um evento na linha do tempo da conversa. Não faz commit."""
    linha = ChatMessage(
        session_id=sessao.id,
        role=ROLE_AUDITORIA,
        content=texto,
        tool_calls=[{"evento": evento, **(detalhe or {})}],
    )
    db.add(linha)
    return linha


def registrar_troca_autoridade(
    db: Session, sessao: ChatSession, de: str | None, para: str
) -> ChatMessage:
    return registrar_evento(
        db,
        sessao,
        EVENTO_AUTORIDADE,
        f"Autoridade alterada de '{de or '—'}' para '{para}'",
        {"de": de, "para": para},
    )


def registrar_troca_projeto(
    db: Session, sessao: ChatSession, de: str | None, para: str | None
) -> ChatMessage:
    return registrar_evento(
        db,
        sessao,
        EVENTO_PROJETO,
        f"Projeto ativo alterado de '{de or 'Global'}' para '{para or 'Global'}'",
        {"de": de, "para": para},
    )


def separar(mensagens: list[ChatMessage]) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """Divide a linha do tempo em (conversa, eventos).

    Qualquer role fora de ROLES_CONVERSA é tratado como evento. É o lado
    seguro: um role novo no futuro não vaza para o prompt por descuido.
    """
    conversa = [m for m in mensagens if m.role in ROLES_CONVERSA]
    eventos = [m for m in mensagens if m.role not in ROLES_CONVERSA]
    return conversa, eventos


def evento_out(linha: ChatMessage) -> dict:
    detalhe = linha.tool_calls[0] if linha.tool_calls else {}
    return {
        "evento": detalhe.get("evento"),
        "descricao": linha.content,
        "de": detalhe.get("de"),
        "para": detalhe.get("para"),
        "created_at": str(linha.created_at),
    }
