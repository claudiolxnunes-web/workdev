from sqlalchemy import Column, String, Text, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    github_url = Column(Text)
    supabase_project = Column(Text)
    netlify_project = Column(Text)
    vercel_project = Column(Text)
    vps = Column(String(20))
    dev_branch = Column(String(50))
    prod_branch = Column(String(50))
    stack = Column(Text)

    # Sensibilidade do contexto que pode sair daqui para um runtime de
    # inferência. `internal` (default) sai para GPU remota depois de redaction
    # e consentimento; `restricted` nunca deixa a VPS, sem flag que contorne.
    #
    # A coluna existe no banco desde a migração d4a1c7e39b52. Declará-la aqui
    # não é detalhe: enquanto o ORM não a conhecia, ler
    # `project.context_classification` levantava AttributeError — foi o mesmo
    # descompasso que o commit af2d334 corrigiu em AgentRun.
    context_classification = Column(
        String(16),
        nullable=False,
        server_default="internal",
    )

    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))
