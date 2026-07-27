import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.schemas.handoff import PlanUpdate
from app.services.handoff import (
    HandoffError, RUN_TRANSITIONS, SUPPORTED_AGENTS, render_agent_prompt,
    update_plan,
)


class HandoffContractTest(unittest.TestCase):
    def test_supported_agents_include_all_build_agents(self):
        self.assertEqual(SUPPORTED_AGENTS, {"codex", "claude", "kimi", "qwen"})

    def test_terminal_states_cannot_transition(self):
        self.assertEqual(RUN_TRANSITIONS["completed"], set())
        self.assertEqual(RUN_TRANSITIONS["failed"], set())
        self.assertEqual(RUN_TRANSITIONS["cancelled"], set())

    def test_blocked_run_can_resume_but_not_complete_directly(self):
        self.assertIn("running", RUN_TRANSITIONS["blocked"])
        self.assertNotIn("completed", RUN_TRANSITIONS["blocked"])

    def test_agent_prompt_contains_approved_contract_and_cli(self):
        context = {
            "run": {"id": "run-123", "agent": "codex", "status": "queued"},
            "project": {
                "name": "WorkDev", "slug": "workdev-core", "stack": "FastAPI + React",
                "github_url": "https://example.invalid/repo", "dev_branch": "dev",
            },
            "task": {
                "id": "task-123", "title": "Handoff", "description": "Integrar PLAN e BUILD",
            },
            "plan": {
                "version": 2, "objective": "Automatizar handoff", "scope": "MVP",
                "constraints": ["Sem secrets no prompt"],
                "acceptance_criteria": ["Agent recebe contexto"],
                "validation_steps": ["Executar testes"],
                "implementation_notes": "Preservar compatibilidade",
            },
            "subtasks": [{"status": "todo", "order": 1, "title": "Implementar"}],
        }
        prompt = render_agent_prompt(context)
        self.assertIn("WorkDev Build — execução run-123", prompt)
        self.assertIn("Agent recebe contexto", prompt)
        self.assertIn("workdev_agent.py start run-123", prompt)
        self.assertNotIn("SUPABASE_SECRET_KEY", prompt)

    def test_plan_update_accepts_portuguese_edit_fields(self):
        payload = PlanUpdate.model_validate({
            "titulo": "Título revisado",
            "objetivo": "Objetivo revisado",
        })
        self.assertEqual(payload.title, "Título revisado")
        self.assertEqual(payload.objective, "Objetivo revisado")

    def test_draft_can_be_edited_and_discarded(self):
        db = Mock()
        plan = SimpleNamespace(
            status="draft", title="Original", objective="Objetivo original",
            updated_at=None,
        )
        db.refresh.side_effect = lambda _plan: None

        updated = update_plan(db, plan, {
            "title": "Título novo", "objective": "Objetivo novo",
            "status": "discarded",
        })

        self.assertEqual(updated.title, "Título novo")
        self.assertEqual(updated.objective, "Objetivo novo")
        self.assertEqual(updated.status, "discarded")
        self.assertIsNotNone(updated.updated_at)
        db.commit.assert_called_once()

    def test_approved_plan_cannot_be_edited_or_discarded(self):
        db = Mock()
        plan = SimpleNamespace(status="approved")
        with self.assertRaisesRegex(HandoffError, "Somente planos"):
            update_plan(db, plan, {"status": "discarded"})

    def test_needs_revision_plan_cannot_change_title_or_objective(self):
        db = Mock()
        plan = SimpleNamespace(status="needs_revision")
        with self.assertRaisesRegex(HandoffError, "Título e objetivo"):
            update_plan(db, plan, {"title": "Título bloqueado"})


if __name__ == "__main__":
    unittest.main()
