"""Contratos das sessões de chat do AI Hub (E1.3).

O projeto ativo é propriedade da sessão, não da tela: quem manda é
`chat_sessions.project_id`. A interface reflete o que o banco diz, e por isso
uma conversa reaberta volta com o contexto certo.

`authority` existe na tabela desde a E1.1, mas não entra nestes contratos —
sem o gate da E1.4 seria um campo que aceita valor e não muda nada.
"""

from uuid import UUID

from pydantic import BaseModel, Field


class SessionUpdate(BaseModel):
    """Troca o projeto ativo da conversa.

    `project_id=None` é explícito e significativo: devolve a conversa ao
    escopo global. Por isso o campo usa `exclude_unset` no router — omitir é
    diferente de mandar null.
    """

    project_id: UUID | None = Field(
        default=None,
        description="UUID do projeto; null devolve a conversa ao escopo global",
    )


class SessionOut(BaseModel):
    id: str
    title: str
    project_id: str | None = None
    project_slug: str | None = None
    project_name: str | None = None
    created_at: str
    updated_at: str
