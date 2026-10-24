"""Domínio de status do backlog e transição para/de archived (ADR 009).

Usado pelo router /backlog e pela tool atualizar_task do AI Hub, para que as
duas portas de escrita apliquem a mesma regra. O gate de subtasks de `done`
continua no router, intocado.
"""
from datetime import datetime
from typing import Any

STATUSES = ("todo", "doing", "blocked", "done", "archived")
ARCHIVE_REASONS = ("concluida_fora", "obsoleta", "sem_destravamento")


class BacklogStatusError(Exception):
    """Erro de domínio no formato {code, message, details} já usado pela API."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def validate_status(status: Any) -> None:
    if status not in STATUSES:
        raise BacklogStatusError(
            422, "invalid_status",
            f"Status inválido: {status!r}. Aceitos: {', '.join(STATUSES)}.",
            {"allowed": list(STATUSES), "received": status},
        )


def apply_status(obj, status: Any, now: datetime,
                 reason: str | None = None, note: str | None = None) -> None:
    """Valida e aplica `status` em `obj`, mantendo archived_at/archived_reason
    preenchidos se e somente se o status for archived."""
    validate_status(status)
    note = (note or "").strip()

    if status == "archived":
        if reason is None:
            if obj.status == "archived" and not note:
                return
            raise BacklogStatusError(
                422, "archived_reason_required",
                "Informe o motivo do arquivamento.",
                {"allowed_reasons": list(ARCHIVE_REASONS)},
            )
        if reason not in ARCHIVE_REASONS:
            raise BacklogStatusError(
                422, "invalid_archived_reason",
                f"Motivo de arquivamento inválido: {reason!r}.",
                {"allowed_reasons": list(ARCHIVE_REASONS), "received": reason},
            )
        obj.archived_reason = f"{reason}: {note}" if note else reason
        if obj.status != "archived":
            obj.archived_at = now
        obj.status = "archived"
        return

    if reason is not None or note:
        raise BacklogStatusError(
            422, "archived_reason_without_archive",
            "Motivo de arquivamento só é aceito com status archived.",
            {"status": status},
        )
    if obj.status == "archived":
        if status != "todo":
            raise BacklogStatusError(
                409, "archived_must_return_to_todo",
                "Task arquivada só pode ser desarquivada para todo.",
                {"current": "archived", "requested": status},
            )
        obj.archived_at = None
        obj.archived_reason = None
    obj.status = status
