"""Contratos das sessões de chat do AI Hub (E1.3).

O projeto ativo é propriedade da sessão, não da tela: quem manda é
`chat_sessions.project_id`. A interface reflete o que o banco diz, e por isso
uma conversa reaberta volta com o contexto certo.

`authority` existe na tabela desde a E1.1, mas não entra nestes contratos —
sem o gate da E1.4 seria um campo que aceita valor e não muda nada.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.autoridade import NIVEIS


class SessionUpdate(BaseModel):
    """Troca o projeto ativo e/ou a autoridade da conversa.

    `project_id=None` é explícito e significativo: devolve a conversa ao
    escopo global. Por isso o router usa `exclude_unset` — omitir é diferente
    de mandar null.

    `authority` aceita só os níveis conhecidos; qualquer outro valor é 422.
    Aqui não vale a tolerância de `normalizar()`: o usuário está declarando uma
    escolha, e uma escolha inválida precisa falhar em vez de virar o padrão.
    """

    project_id: UUID | None = Field(
        default=None,
        description="UUID do projeto; null devolve a conversa ao escopo global",
    )
    authority: Literal[NIVEIS] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="observe | plan | execute | admin",
    )


class SessionOut(BaseModel):
    id: str
    title: str
    project_id: str | None = None
    project_slug: str | None = None
    project_name: str | None = None
    authority: str
    created_at: str
    updated_at: str
