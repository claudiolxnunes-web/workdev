"""Revisão cruzada obrigatória: papéis, persistência e histórico cumulativo.

Fatia 1 — modelagem dos papéis executor/revisor e da trilha de revisões.
Fatia 2 — validação executor != revisor no envio ao Build.
Fatia 3 — histórico cumulativo e ciclo BUILD → REVIEW → correção → DONE.
Fatia 4 — troca auditada de executor/revisor com justificativa escrita.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pydantic

from app.models.handoff import AgentRun, AgentRunReview
from app.schemas.handoff import BuildRequest
from app.services.handoff import (
    RUN_TRANSITIONS,
    HandoffError,
    queue_build,
    record_review,
    swap_reviewer,
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


class ReviewIsMandatoryBeforeDoneTest(unittest.TestCase):
    def test_running_cannot_jump_straight_to_completed(self):
        self.assertNotIn("completed", RUN_TRANSITIONS["running"])
        self.assertIn("review", RUN_TRANSITIONS["running"])

    def test_completed_is_only_reachable_from_review(self):
        origens = {
            origem
            for origem, destinos in RUN_TRANSITIONS.items()
            if "completed" in destinos
        }
        self.assertEqual(origens, {"review"})

    def test_review_can_send_the_run_back_to_the_executor(self):
        self.assertIn("running", RUN_TRANSITIONS["review"])


class _ReviewRun(SimpleNamespace):
    """Run em revisão, com os campos que record_review toca."""

    def __init__(self, **overrides):
        base = {
            "id": uuid4(),
            "backlog_id": uuid4(),
            "agent": "claude",
            "reviewer_agent": "codex",
            "status": "review",
            "review_attempts": 0,
            "result": None,
        }
        base.update(overrides)
        super().__init__(**base)


class RecordReviewTest(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.added = []
        self.db.add.side_effect = self.added.append

    def _transition(self, _db, run, data):
        run.status = data["status"]
        return run, SimpleNamespace(id=f"event-{data['status']}")

    def test_rejection_returns_the_run_to_the_executor_with_feedback(self):
        run = _ReviewRun()

        with patch(
            "app.services.handoff.update_run",
            side_effect=self._transition,
        ):
            updated, review = record_review(
                self.db,
                run,
                "codex",
                "rejected",
                "Faltou teste do caso de timeout",
            )

        self.assertEqual(updated.status, "running")
        self.assertEqual(review.verdict, "rejected")
        self.assertEqual(review.attempt, 1)
        self.assertEqual(review.executor_agent, "claude")
        self.assertEqual(review.reviewer_agent, "codex")
        self.assertEqual(review.feedback, "Faltou teste do caso de timeout")
        self.assertEqual(run.review_attempts, 1)

    def test_rejection_without_feedback_is_refused(self):
        with self.assertRaises(HandoffError) as ctx:
            record_review(self.db, _ReviewRun(), "codex", "rejected", "   ")
        self.assertIn("feedback", str(ctx.exception))

    def test_two_rejections_accumulate_instead_of_overwriting(self):
        run = _ReviewRun()

        with patch(
            "app.services.handoff.update_run",
            side_effect=self._transition,
        ):
            record_review(self.db, run, "codex", "rejected", "primeira volta")
            run.status = "review"
            record_review(self.db, run, "codex", "rejected", "segunda volta")

        registros = [
            item for item in self.added if isinstance(item, AgentRunReview)
        ]
        self.assertEqual([item.attempt for item in registros], [1, 2])
        self.assertEqual(
            [item.feedback for item in registros],
            ["primeira volta", "segunda volta"],
        )
        self.assertEqual(run.review_attempts, 2)

    def test_approval_completes_the_run_when_the_gate_passes(self):
        run = _ReviewRun()

        with (
            patch(
                "app.services.test_gate.validate_run_for_status_change",
                return_value=(True, "Gate aprovado"),
            ),
            patch(
                "app.services.handoff.update_run",
                side_effect=self._transition,
            ),
        ):
            updated, review = record_review(self.db, run, "codex", "approved")

        self.assertEqual(updated.status, "completed")
        self.assertEqual(review.verdict, "approved")
        self.assertTrue(review.gate_passed)

    def test_reviewer_opinion_does_not_override_objective_gate(self):
        run = _ReviewRun()

        with (
            patch(
                "app.services.test_gate.validate_run_for_status_change",
                return_value=(False, "pytest falhou"),
            ),
            patch("app.services.handoff.update_run") as update_mock,
            self.assertRaises(HandoffError) as ctx,
        ):
            record_review(self.db, run, "codex", "approved")

        self.assertIn("Gate objetivo reprovado", str(ctx.exception))
        update_mock.assert_not_called()
        self.assertEqual(run.status, "review")
        self.assertEqual(run.review_attempts, 0)
        self.assertEqual(
            [item for item in self.added if isinstance(item, AgentRunReview)],
            [],
        )

    def test_executor_cannot_review_its_own_run(self):
        with self.assertRaises(HandoffError):
            record_review(self.db, _ReviewRun(), "claude", "approved")

    def test_other_agent_cannot_hijack_the_designated_review(self):
        with self.assertRaises(HandoffError) as ctx:
            record_review(self.db, _ReviewRun(), "kimi", "approved")
        self.assertIn("troque o revisor", str(ctx.exception))

    def test_run_outside_review_cannot_be_reviewed(self):
        with self.assertRaises(HandoffError):
            record_review(
                self.db,
                _ReviewRun(status="running"),
                "codex",
                "approved",
            )

    def test_unknown_verdict_is_refused(self):
        with self.assertRaises(HandoffError):
            record_review(self.db, _ReviewRun(), "codex", "aprovadinho")


class SwapReviewerTest(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.events = []
        self.db.add.side_effect = self.events.append

    def test_swap_records_reason_and_previous_reviewer(self):
        run = _ReviewRun(status="running")

        updated, event = swap_reviewer(
            self.db,
            run,
            "kimi",
            "Codex sem cota até amanhã",
        )

        self.assertEqual(updated.reviewer_agent, "kimi")
        self.assertEqual(event.event_type, "review.reviewer_changed")
        self.assertEqual(event.payload["from_reviewer"], "codex")
        self.assertEqual(event.payload["to_reviewer"], "kimi")
        self.assertEqual(
            event.payload["reason"],
            "Codex sem cota até amanhã",
        )

    def test_swap_requires_written_reason(self):
        with self.assertRaises(HandoffError) as ctx:
            swap_reviewer(self.db, _ReviewRun(status="running"), "kimi", "  ")
        self.assertIn("justificativa", str(ctx.exception))

    def test_swap_cannot_make_the_executor_its_own_reviewer(self):
        with self.assertRaises(HandoffError):
            swap_reviewer(
                self.db,
                _ReviewRun(status="running"),
                "claude",
                "quero aprovar sozinho",
            )

    def test_swap_rejects_the_current_reviewer(self):
        with self.assertRaises(HandoffError):
            swap_reviewer(
                self.db,
                _ReviewRun(status="running"),
                "codex",
                "sem mudança real",
            )

    def test_terminal_run_does_not_accept_reviewer_swap(self):
        with self.assertRaises(HandoffError):
            swap_reviewer(
                self.db,
                _ReviewRun(status="completed"),
                "kimi",
                "tarde demais",
            )


class TransferWithReviewerSwapTest(unittest.TestCase):
    def test_transfer_to_reviewer_is_allowed_when_reviewer_also_changes(self):
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
        db.query.return_value.filter.return_value.first.side_effect = [
            plan,
            None,
            None,
        ]

        with patch(
            "app.services.handoff.update_run",
            side_effect=lambda _db, current, _data: (current, None),
        ):
            _cancelled, new_run = transfer_run(
                db,
                run,
                "codex",
                "Claude travou",
                new_reviewer="kimi",
            )

        self.assertEqual(new_run.agent, "codex")
        self.assertEqual(new_run.reviewer_agent, "kimi")


if __name__ == "__main__":
    unittest.main()
