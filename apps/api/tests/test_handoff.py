import unittest

from app.services.handoff import RUN_TRANSITIONS, SUPPORTED_AGENTS, render_agent_prompt


class HandoffContractTest(unittest.TestCase):
    def test_supported_agents_include_kimi(self):
        self.assertEqual(SUPPORTED_AGENTS, {"codex", "claude", "kimi"})

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


if __name__ == "__main__":
    unittest.main()
