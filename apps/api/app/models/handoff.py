from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, text,
)

from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ExecutionPlan(Base):
    __tablename__ = "execution_plans"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    backlog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("backlog.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, server_default="draft")
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    scope = Column(Text)
    constraints = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    acceptance_criteria = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    validation_steps = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    implementation_notes = Column(Text)
    created_by = Column(
        String(50),
        nullable=False,
        server_default="ai_hub",
    )
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "backlog_id",
            "version",
            name="uq_execution_plan_version",
        ),
        Index("ix_execution_plans_backlog_id", "backlog_id"),
        Index("ix_execution_plans_status", "status"),
    )


class AgentRun(Base):
    terminal_session = relationship('TerminalSession', back_populates='run', uselist=False, passive_deletes='all')
    __tablename__ = "agent_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("execution_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    backlog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("backlog.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Executor da run. Identidade lógica do agente (codex, claude, local-code,
    # gpu-hostinger…), nunca o modelo carregado — modelo é `model`.
    agent = Column(String(32), nullable=False)

    # Revisor independente escolhido na aprovação do PLAN. Nunca pode ser igual
    # ao executor na revisão final (validado em app/services/handoff.py).
    reviewer_agent = Column(String(32))

    # Quantas rodadas de revisão já foram registradas para esta run. O histórico
    # detalhado vive em agent_run_reviews e é cumulativo (nunca sobrescrito).
    review_attempts = Column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # Estado do despacho para runtime Ollama. A migração b2e8f4a17c30 criou as
    # colunas no banco e o model não foi atualizado junto: entre a aplicação da
    # migração e este commit, quem lesse run.dispatch_state pelo ORM levava
    # AttributeError, não None — e derrubou toda rota que serializa uma run.
    # O detalhe de cada tentativa vive em agent_build_jobs; isto é o resumo.
    dispatch_state = Column(
        String(16),
        nullable=False,
        server_default="idle",
    )
    dispatch_attempts = Column(
        Integer,
        nullable=False,
        server_default="0",
    )
    last_dispatch_at = Column(DateTime(timezone=True))
    dispatch_token = Column(UUID(as_uuid=True))

    model = Column(String(120))

    # Provedor escolhido no roteamento (anthropic, openrouter, ollama…).
    # Nulo nas runs históricas: a escolha já era auditável pelo evento
    # `build.queued`, mas não por coluna. O consumo por run vive em
    # `agent_run_telemetry`.
    provider = Column(String(60))

    # Chave do modelo físico servido pelo llama.cpp no despacho do local-code
    # (moe/q27/dev/fast, via local_model.current()). `model` continua gravando o
    # alias estável workdev-qwen; esta coluna só é preenchida para
    # agent = 'local-code' e fica NULL nos demais.
    local_model_key = Column(String(32))

    reasoning_effort = Column(String(16))
    complexity = Column(String(16))
    complexity_score = Column(Integer)
    routing_mode = Column(
        String(16),
        nullable=False,
        server_default="manual",
    )
    routing_reason = Column(Text)

    status = Column(
        String(24),
        nullable=False,
        server_default="queued",
    )
    summary = Column(Text)
    result = Column(Text)
    error = Column(Text)
    branch = Column(String(255))
    commit_sha = Column(String(64))
    deployment_url = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_agent_runs_plan_id", "plan_id"),
        Index("ix_agent_runs_backlog_id", "backlog_id"),
        Index("ix_agent_runs_agent_status", "agent", "status"),
        Index("ix_agent_runs_reviewer_agent", "reviewer_agent"),
    )


class AgentRunReview(Base):
    """Histórico cumulativo de revisões independentes de uma execução.

    Cada tentativa vira uma linha nova: rejeição não apaga nem sobrescreve a
    anterior, então a trilha de auditoria (quem revisou, quando, com qual
    veredito e feedback) sobrevive a quantas correções forem necessárias.
    """

    __tablename__ = "agent_run_reviews"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt = Column(Integer, nullable=False)
    executor_agent = Column(String(32), nullable=False)
    reviewer_agent = Column(String(32), nullable=False)
    verdict = Column(String(16), nullable=False)
    feedback = Column(Text)
    gate_passed = Column(Boolean)
    payload = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "attempt",
            name="uq_agent_run_review_attempt",
        ),
        Index("ix_agent_run_reviews_run_id", "run_id"),
        Index("ix_agent_run_reviews_created_at", "created_at"),
    )


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type = Column(String(40), nullable=False)
    message = Column(Text)
    payload = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_agent_run_events_run_id", "run_id"),
        Index("ix_agent_run_events_created_at", "created_at"),
    )


class AgentRunTelemetry(Base):
    """Consumo de tokens e custo de uma chamada de provedor dentro de uma run.

    Uma linha por chamada, não por run: uma execução pode acionar mais de um
    provedor, e somar tudo na linha da run esconderia a composição.

    Duas colunas sustentam a honestidade do dado:

    - `source` diz de onde veio o número — `official` (veio da API do
      provedor ou do runtime) ou `estimated` (derivado do transcript e do
      preço de catálogo). Sem ela, um estimado apareceria ao lado de um
      faturado como se fossem a mesma coisa.
    - `cost_class` diz o que o número significa em dinheiro — `local`
      (runtime próprio), `free_quota`, `included_plan` (já pago por
      assinatura) ou `paid_api` (cobrança por token).

    Nenhum campo guarda segredo: só contagens, dinheiro e nomes de modelo.
    """

    __tablename__ = "agent_run_telemetry"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Desnormalizados de propósito: o relatório de consumo é por task e por
    # projeto, e nenhuma dessas queries deveria depender de join com a run.
    backlog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("backlog.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent = Column(String(40), nullable=False)
    provider = Column(String(60), nullable=False)
    model = Column(String(120), nullable=False)

    input_tokens = Column(Integer)
    cached_input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    total_tokens = Column(Integer)

    estimated_cost = Column(Numeric(12, 6))
    actual_cost = Column(Numeric(12, 6))
    currency = Column(String(3), nullable=False, server_default="USD")

    # 'official'  = o número veio da API do provedor ou do runtime
    # 'estimated' = número derivado do transcript e do preço de catálogo
    source = Column(String(16), nullable=False)
    # local | free_quota | included_plan | paid_api
    cost_class = Column(String(20), nullable=False)

    recorded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('official', 'estimated')",
            name="ck_agent_run_telemetry_source",
        ),
        CheckConstraint(
            "cost_class IN ('local', 'free_quota', 'included_plan', 'paid_api')",
            name="ck_agent_run_telemetry_cost_class",
        ),
        Index("ix_agent_run_telemetry_run_id", "run_id"),
        Index("ix_agent_run_telemetry_agent", "agent", "recorded_at"),
        Index("ix_agent_run_telemetry_project", "project_id", "recorded_at"),
    )


class AgentBuildJob(Base):
    """Uma tentativa de despacho de uma run para um runtime Ollama.

    A run diz *quem* executa; o job diz *que* uma execução concreta foi pedida,
    quando, com qual prompt e em que estado ela está. Sem esta linha o despacho
    só existia como efeito colateral de uma requisição HTTP: dois cliques
    viravam duas inferências sem que nada no banco registrasse a primeira.

    A garantia de despacho único não é da aplicação, é do banco — o índice
    parcial `uq_agent_build_jobs_active_run` recusa uma segunda linha ativa para
    a mesma run. Corrida entre dois processos perde no INSERT, não num `if`.
    """

    __tablename__ = "agent_build_jobs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    runtime_id = Column(String(32), nullable=False)
    model = Column(String(120))
    state = Column(String(16), nullable=False, server_default="queued")
    attempt = Column(Integer, nullable=False, server_default=text("1"))
    prompt_sha256 = Column(String(64))
    branch = Column(String(120))
    error = Column(Text)
    payload = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_agent_build_jobs_run_id", "run_id"),
        Index("ix_agent_build_jobs_state", "state"),
    )
