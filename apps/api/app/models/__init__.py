# Import all models to ensure they are registered with SQLAlchemy
from app.models.adr import ADR
from app.models.ai_routing import AIModelCatalog
from app.models.backlog import BacklogItem
from app.models.chat import ChatMessage, ChatSession
from app.models.decision import Decision
from app.models.deployment import DeploymentOutcome
from app.models.handoff import ExecutionPlan, AgentRun, AgentRunEvent
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.rfc import RFC
from app.models.subtask import BacklogSubtask

__all__ = [
    "ADR",
    "AIModelCatalog",
    "BacklogItem",
    "ChatMessage",
    "ChatSession",
    "Decision",
    "DeploymentOutcome",
    "ExecutionPlan",
    "AgentRun",
    "AgentRunEvent",
    "KnowledgeEntry",
    "Project",
    "RFC",
    "BacklogSubtask",
]
