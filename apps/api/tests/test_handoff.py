import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.schemas.handoff import PlanUpdate
from app.services.handoff import (
    AutoRuntimeConfig, HandoffError, RUN_TRANSITIONS, SUPPORTED_AGENTS,
    load_subtasks, render_agent_prompt,
    update_plan,
)


class HandoffContractTest(unittest.TestCase):
    def test_supported_agents_include_all_build_agents(self):
        self.assertEqual(SUPPORTED_AGENTS, {"codex", "claude", "kimi", "qwen", "gemini"},
)

    def test_terminal_states_cannot_transition(self):
        self.assertEqual(RUN_TRANSITIONS["completed"], set())
        self.assertEqual(RUN_TRANSITIONS["failed"], set())
        self.assertEqual(RUN_TRANSITIONS["cancelled"], set())

    def test_blocked_run_can_resume_but_not_complete_directly(self):
        self.assertIn("running", RUN_TRANSITIONS["blocked"])
        self.assertNotIn("completed", RUN_TRANSITIONS["blocked"])

    def test_agent_prompt_contains_approved_contract_and_cli(self):
        context = {
            "runtime": {
                "schema_version": "auto-runtime.v2",
                "run_id": "run-123",
                "session": "auto-codex-run-123",
                "timeout_seconds": 14400,
            },
            "run": {
    "id": "run-123",
    "agent": "codex",
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "routing_mode": "manual",
    "complexity": "high",
    "complexity_score": 70,
    "routing_reason": "Seleção manual pelo usuário",
    "status": "queued",
},
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

    def test_auto_runtime_config_has_strict_json_schema(self):
        schema = AutoRuntimeConfig.model_json_schema()
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(
            set(schema["required"]),
            {"run_id", "session", "timeout_seconds"},
        )
        config = AutoRuntimeConfig.model_validate({
            "run_id": "run-1",
            "session": "auto-codex-run-1",
            "timeout_seconds": 600,
        })
        self.assertEqual(config.schema_version, "auto-runtime.v2")

    def test_load_subtasks_uses_backlog_id_and_preserves_query_order(self):
        db = Mock()
        rows = [SimpleNamespace(execution_order=1), SimpleNamespace(execution_order=2)]
        query = db.query.return_value
        query.filter.return_value.order_by.return_value.all.return_value = rows

        self.assertEqual(load_subtasks(db, "task-123"), rows)
        query.filter.assert_called_once()
        query.filter.return_value.order_by.assert_called_once()

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


class ManualModelChoiceTest(unittest.TestCase):
    """O usuário escolhe o modelo, mas só entre os permitidos do agente."""

    def _plan(self):
        return SimpleNamespace(
            id="plan-1",
            backlog_id="task-1",
            status="approved",
        )

    def _allowed(self):
        return [
            SimpleNamespace(
                provider_model_id="claude-opus-5",
                display_name="Claude Opus 5",
            ),
            SimpleNamespace(
                provider_model_id="claude-sonnet-5",
                display_name="Claude Sonnet 5",
            ),
        ]

    def _send(self, model, allowed):
        from fastapi import HTTPException
        from unittest.mock import patch

        from app.routers.handoffs import send_to_build
        from app.schemas.handoff import BuildRequest

        run = SimpleNamespace(
            id="run-1",
            plan_id="plan-1",
            backlog_id="task-1",
            agent="claude",
            model=model,
            routing_mode="manual",
            status="queued",
        )

        with (
            patch(
                "app.routers.handoffs._get_plan",
                return_value=self._plan(),
            ),
            patch(
                "app.routers.handoffs.allowed_models_for_agent",
                return_value=allowed,
            ),
            patch(
                "app.routers.handoffs.queue_build",
                return_value=(run, SimpleNamespace(id="event-1")),
            ) as queue_mock,
            patch("app.routers.handoffs._sync_run"),
            patch(
                "app.routers.handoffs._run_out",
                return_value={"id": "run-1", "model": model},
            ),
        ):
            try:
                result = send_to_build(
                    plan_id="plan-1",
                    payload=BuildRequest(
                        routing_mode="manual",
                        agent="claude",
                        model=model,
                    ),
                    background=Mock(),
                    db=Mock(),
                )
            except HTTPException as error:
                return None, error, queue_mock

        return result, None, queue_mock

    def test_modelo_permitido_e_aceito_e_persistido_no_run(self):
        result, error, queue_mock = self._send(
            "claude-sonnet-5",
            self._allowed(),
        )

        self.assertIsNone(error)
        self.assertEqual(result["model"], "claude-sonnet-5")
        self.assertEqual(
            queue_mock.call_args.kwargs["model"],
            "claude-sonnet-5",
        )

    def test_modelo_fora_da_lista_do_agente_e_recusado(self):
        _result, error, queue_mock = self._send(
            "gpt-5.6-sol",
            self._allowed(),
        )

        self.assertIsNotNone(error)
        self.assertEqual(error.status_code, 409)
        self.assertEqual(
            error.detail["code"],
            "model_not_allowed_for_agent",
        )
        self.assertEqual(
            [
                item["model"]
                for item in error.detail["details"]["allowed_models"]
            ],
            ["claude-opus-5", "claude-sonnet-5"],
        )
        queue_mock.assert_not_called()

    def test_agente_sem_modelos_configurados_segue_como_hoje(self):
        """Qwen não foi vinculado: o envio manual continua funcionando."""
        result, error, _queue = self._send("qwen/qwen3-coder", [])

        self.assertIsNone(error)
        self.assertEqual(result["model"], "qwen/qwen3-coder")
