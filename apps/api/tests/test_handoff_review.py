"""Revisão cruzada obrigatória: papéis, persistência e histórico cumulativo.

Fatia 1 — modelagem dos papéis executor/revisor e da trilha de revisões.
"""

import unittest

from app.models.handoff import AgentRun, AgentRunReview


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


if __name__ == "__main__":
    unittest.main()
