"""Revisão cruzada obrigatória: papéis, persistência e histórico cumulativo.

Fatia 1 — modelagem dos papéis executor/revisor e da trilha de revisões.
Fatia 2 — validação executor != revisor no envio ao Build.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pydantic

from app.models.handoff import AgentRun, AgentRunReview
from app.schemas.handoff import BuildRequest
from app.services.handoff import (
    HandoffError,
    queue_build,
    transfer_run,
    validate_review_pair,
)


def _approved_plan():
    return SimpleNamespace(
        id=uuid4(),
        backlog_id=uuid4(),
        status="approved",
    )


def _db_without_active_run():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


class ReviewRoleModelTest(unittest.TestCase):
    def test_run_persists_executor_and_reviewer_separately(self):
        columns = AgentRun.__table__.columns

        self.assertIn("agent", columns)
        self.assertIn("reviewer_agent", columns)
        self.assertEqual(columns["agent"].type.length, 32)
        self.assertEqual(columns["reviewer_agent"].type.length, 32)

    def test_run_tracks_review_attempts_with_zero_default(self):
        column = AgentRun.__table__.columns["review_attempts"]

        self.assertFalse(column.nullable)
        self.assertEqual(column.server_default.arg, "0")

    def test_review_history_is_append_only_per_attempt(self):
        columns = AgentRunReview.__table__.columns

        for field in (
            "run_id",
            "attempt",
            "executor_agent",
            "reviewer_agent",
            "verdict",
            "feedback",
            "gate_passed",
            "created_at",
        ):
            self.assertIn(field, columns)

        # A unicidade é (run_id, attempt): cada rodada de revisão vira linha
        # nova, então rejeição não sobrescreve o histórico anterior.
        constraint = next(
            item
            for item in AgentRunReview.__table__.constraints
            if getattr(item, "name", None) == "uq_agent_run_review_attempt"
        )
        self.assertEqual(
            {column.name for column in constraint.columns},
            {"run_id", "attempt"},
        )

    def test_review_row_cascades_with_the_run(self):
        foreign_key = next(
            iter(AgentRunReview.__table__.columns["run_id"].foreign_keys)
        )
        self.assertEqual(foreign_key.column.table.name, "agent_runs")
        self.assertEqual(foreign_key.ondelete, "CASCADE")


class ReviewPairValidationTest(unittest.TestCase):
    def test_reviewer_is_mandatory(self):
        with self.assertRaises(HandoffError) as ctx:
            validate_review_pair("claude", None)
        self.assertIn("Revisor é obrigatório", str(ctx.exception))

    def test_executor_cannot_review_itself(self):
        with self.assertRaises(HandoffError) as ctx:
            validate_review_pair("claude", "claude")
        self.assertIn("diferentes", str(ctx.exception))

    def test_unknown_reviewer_is_rejected(self):
        with self.assertRaises(HandoffError):
            validate_review_pair("claude", "chatgpt-do-zap")

    def test_distinct_pair_is_accepted(self):
        self.assertEqual(validate_review_pair("claude", "codex"), "codex")


class BuildRequestReviewerTest(unittest.TestCase):
    def test_manual_build_without_reviewer_is_rejected(self):
        with self.assertRaises(pydantic.ValidationError) as ctx:
            BuildRequest(routing_mode="manual", agent="claude")
        self.assertIn("reviewer é obrigatório", str(ctx.exception))

    def test_auto_build_also_requires_a_reviewer(self):
        with self.assertRaises(pydantic.ValidationError):
            BuildRequest(routing_mode="auto")

    def test_same_executor_and_reviewer_is_rejected(self):
        with self.assertRaises(pydantic.ValidationError) as ctx:
            BuildRequest(
                routing_mode="manual",
                agent="qwen",
                reviewer="qwen",
            )
        self.assertIn("diferentes", str(ctx.exception))

    def test_valid_pair_is_accepted(self):
        payload = BuildRequest(
            routing_mode="manual",
            agent="claude",
            reviewer="codex",
        )
        self.assertEqual(payload.agent, "claude")
        self.assertEqual(payload.reviewer, "codex")


class QueueBuildReviewerTest(unittest.TestCase):
    def test_queue_build_persists_both_roles(self):
        db = _db_without_active_run()
        plan = _approved_plan()

        run, _event = queue_build(db, plan, "claude", reviewer="codex")

        self.assertEqual(run.agent, "claude")
        self.assertEqual(run.reviewer_agent, "codex")
        self.assertEqual(run.review_attempts, 0)

    def test_queue_build_rejects_missing_reviewer(self):
        with self.assertRaises(HandoffError):
            queue_build(_db_without_active_run(), _approved_plan(), "claude")

    def test_queue_build_rejects_executor_as_reviewer(self):
        with self.assertRaises(HandoffError):
            queue_build(
                _db_without_active_run(),
                _approved_plan(),
                "claude",
                reviewer="claude",
            )

    def test_queued_event_records_the_reviewer(self):
        db = _db_without_active_run()

        _run, event = queue_build(
            db,
            _approved_plan(),
            "claude",
            reviewer="codex",
        )

        self.assertEqual(event.payload["reviewer_agent"], "codex")


class TransferPreservesReviewerTest(unittest.TestCase):
    def test_transfer_keeps_the_reviewer_of_the_original_run(self):
        db = _db_without_active_run()
        plan = _approved_plan()
        run = SimpleNamespace(
            id=uuid4(),
            plan_id=plan.id,
            backlog_id=plan.backlog_id,
            agent="claude",
            reviewer_agent="codex",
            status="running",
        )
        # Ordem das consultas: plano da run, execução ativa (nenhuma), task.
        db.query.return_value.filter.return_value.first.side_effect = [
            plan,
            None,
            None,
        ]

        with patch(
            "app.services.handoff.update_run",
            side_effect=lambda _db, current, _data: (current, None),
        ):
            _cancelled, new_run = transfer_run(db, run, "kimi", "sem cota")

        self.assertEqual(new_run.agent, "kimi")
        self.assertEqual(new_run.reviewer_agent, "codex")

    def test_transfer_to_the_reviewer_is_rejected(self):
        run = SimpleNamespace(
            id=uuid4(),
            plan_id=uuid4(),
            backlog_id=uuid4(),
            agent="claude",
            reviewer_agent="codex",
            status="running",
        )

        with self.assertRaises(HandoffError) as ctx:
            transfer_run(Mock(), run, "codex", "sem cota")

        self.assertIn("revisor", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
