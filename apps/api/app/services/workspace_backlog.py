"""Workspace Local → backlog (decisão 6 do operador, 2026-10-25).

- "Aprovar plano": cada fatia vira subtask da task, na ordem de execução.
- Fatia começa: a task vai para `doing` (se estava `todo`/`blocked`) e a
  subtask também.
- Fatia passa no gate e é commitada: subtask `done`, com o commit no `result`.
- Fatia falha: subtask `blocked`, com o motivo no `result`.

Fechar a task é sempre do operador: nada aqui leva a task para `done`.
Registro interno do WorkDev (nível Planejar): não toca código nem deploy.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.backlog import BacklogItem
from app.models.subtask import BacklogSubtask
from app.services.backlog_status import BacklogStatusError, apply_status

AGENTE = "workspace-local"
MAX_RESULT = 2000


def _uuid(valor) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(valor))
    except (TypeError, ValueError):
        return None


def _agora() -> datetime:
    # Colunas sem fuso, como o now() do Postgres em UTC grava.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sincronizar_grafo(subtask: BacklogSubtask, project_id) -> None:
    """Mesmo sync do router de subtasks, fora da requisição: falha não derruba nada."""
    from app.services.engineering_graph import graph_sync
    threading.Thread(target=graph_sync.sync_safely,
                     args=("sync_subtask", str(subtask.id), str(subtask.backlog_id), str(project_id)),
                     daemon=True).start()


def criar_subtasks(db: Session, task_id: str, fatias: list[dict]) -> list[str | None]:
    task = db.query(BacklogItem).filter(BacklogItem.id == _uuid(task_id)).first()
    if task is None:
        return [None] * len(fatias)
    criadas = []
    for fatia in fatias:
        descricao = fatia["instrucao"] + "\n\nGate:\n" + "\n".join(f"- {g}" for g in fatia["gate"])
        sub = BacklogSubtask(id=uuid.uuid4(), backlog_id=task.id, title=f"Fatia {fatia['n']}: {fatia['objetivo']}"[:500],
                             description=descricao, status="todo", execution_order=fatia["n"],
                             assigned_agent=AGENTE)
        db.add(sub)
        criadas.append(sub)
    db.commit()
    for sub in criadas:
        db.refresh(sub)
        _sincronizar_grafo(sub, task.project_id)
    return [str(sub.id) for sub in criadas]


def remover_subtasks_nao_iniciadas(db: Session, ids: list[str | None]) -> int:
    """Plano substituído antes de começar: some só o que o Workspace criou e ninguém tocou."""
    alvos = [u for u in (_uuid(i) for i in ids) if u]
    if not alvos:
        return 0
    removidas = (db.query(BacklogSubtask)
                 .filter(BacklogSubtask.id.in_(alvos), BacklogSubtask.assigned_agent == AGENTE,
                         BacklogSubtask.status == "todo")
                 .delete(synchronize_session=False))
    db.commit()
    return removidas


def task_em_andamento(db: Session, task_id: str | None) -> None:
    task = db.query(BacklogItem).filter(BacklogItem.id == _uuid(task_id)).first() if task_id else None
    if task is None or task.status not in ("todo", "blocked"):
        return
    try:
        apply_status(task, "doing", _agora())
    except BacklogStatusError:
        return
    db.commit()


def marcar_subtask(db: Session, subtask_id: str | None, status: str, resultado: str | None = None) -> None:
    sub = db.query(BacklogSubtask).filter(BacklogSubtask.id == _uuid(subtask_id)).first() if subtask_id else None
    if sub is None:
        return
    sub.status = status
    if resultado is not None:
        sub.result = resultado[:MAX_RESULT]
    sub.updated_at = _agora()
    db.commit()
