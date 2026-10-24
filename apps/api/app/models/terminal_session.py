"""Persisted identity of a Linux PTY supervised independently of API objects."""
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class TerminalSession(Base):
    __tablename__ = 'terminal_sessions'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey('agent_runs.id', ondelete='RESTRICT'), nullable=False, unique=True)
    state = Column(String(16), nullable=False, default='STARTING')
    supervisor_pid = Column(Integer)
    pid = Column(Integer)
    process_identity = Column(String(100))
    pty_path = Column(String(100))
    socket_path = Column(Text, nullable=False)
    cwd = Column(Text, nullable=False)
    exit_code = Column(Integer)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    closed_at = Column(DateTime(timezone=True))
    run = relationship('AgentRun', back_populates='terminal_session')
    __table_args__ = (CheckConstraint("state IN ('STARTING','RUNNING','STOPPING','CLOSED','ERROR')", name='ck_terminal_session_state'),)
