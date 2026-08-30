import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import os

from app.routers.handoffs import (
    _auto_runtime_enabled, _monitor_auto_agent, _run_auto_agent,
    send_to_build, update_agent_run,
)
from app.schemas.handoff import BuildRequest, RunUpdate
from app.services.agent_router import RoutingDecision


class HandoffAutoRouteTest(unittest.TestCase):
    def test_auto_routes_before_queueing_build(self):
        db = Mock()
        background = Mock()
        subtasks = [SimpleNamespace(id="sub-1", execution_order=1)]

        plan = SimpleNamespace(
            id="plan-1",
            backlog_id="task-1",
            status="approved",
        )

        task = SimpleNamespace(
            id="task-1",
            project_id="project-1",
            title="Criar endpoint CRUD",
            description="Adicionar endpoint FastAPI",
            priority="medium",
        )

        project = SimpleNamespace(
            id="project-1",
            name="WorkDev",
        )

        assessment = SimpleNamespace(
            level="medium",
            score=48,
            required_capabilities=(
                "code",
                "reasoning",
            ),
            reason="teste",
            signals=(),
        )

        decision = RoutingDecision(
            agent="gemini",
            provider="gemini",
            model="gemini-2.5-flash",
            catalog_id="gemini-2-5-flash",
            reasoning_effort=None,
            complexity="medium",
            complexity_score=48,
            capability_score=100,
            matched_capabilities=(
                "code",
                "reasoning",
            ),
            missing_capabilities=(),
            category="economic",
            estimated_price_index=None,
            requires_confirmation=False,
            reason="AUTO selecionou Gemini 2.5 Flash",
        )

        run = SimpleNamespace(
            id="run-1",
            plan_id="plan-1",
            backlog_id="task-1",
            agent="gemini",
            model="gemini-2.5-flash",
            reasoning_effort=None,
            complexity="medium",
            complexity_score=48,
            routing_mode="auto",
            routing_reason=decision.reason,
            status="queued",
            summary=None,
            result=None,
            error=None,
            branch=None,
            commit_sha=None,
            deployment_url=None,
            started_at=None,
            finished_at=None,
            created_at=None,
            updated_at=None,
        )

        event = SimpleNamespace(
            id="event-1",
        )

        payload = BuildRequest(
            routing_mode="auto",
        )

        with (
            patch(
                "app.routers.handoffs._get_plan",
                return_value=plan,
            ),
            patch(
                "app.routers.handoffs._task_project",
                return_value=(
                    task,
                    project,
                ),
            ),
            patch(
                "app.routers.handoffs.classify_task",
                return_value=assessment,
            ) as classify_mock,
            patch(
                "app.routers.handoffs.load_subtasks",
                return_value=subtasks,
            ) as load_subtasks_mock,
            patch(
                "app.routers.handoffs.route_agent",
                return_value=decision,
            ) as route_mock,
            patch(
                "app.routers.handoffs.queue_build",
                return_value=(
                    run,
                    event,
                ),
            ) as queue_mock,
            patch(
                "app.routers.handoffs._sync_run",
            ) as sync_mock,
            patch(
                "app.routers.handoffs._run_out",
                return_value={
                    "id": "run-1",
                    "agent": "gemini",
                    "model": "gemini-2.5-flash",
                    "routing_mode": "auto",
                },
            ),
            patch(
                "app.routers.handoffs.build_context",
                return_value={"prompt": "mock prompt"},
            ) as build_context_mock,
            patch(
                "app.routers.handoffs._run_auto_agent",
            ) as run_auto_mock,
            # O runtime tmux dinâmico do AUTO é opt-in: aqui ligamos de
            # propósito para provar que o roteamento e o start continuam
            # funcionando quando o operador o habilita.
            patch(
                "app.routers.handoffs._auto_runtime_enabled",
                return_value=True,
            ),
        ):
            result = send_to_build(
                plan_id="plan-1",
                payload=payload,
                background=background,
                db=db,
            )

        classify_mock.assert_called_once_with(
            task,
            plan,
            subtasks,
        )
        load_subtasks_mock.assert_called_once_with(db, "task-1")

        route_mock.assert_called_once_with(
            db,
            assessment,
            allow_premium=False,
        )

        queue_mock.assert_called_once_with(
            db,
            plan,
            "gemini",
            model="gemini-2.5-flash",
            reasoning_effort=None,
            routing_mode="auto",
            complexity="medium",
            complexity_score=48,
            routing_reason=decision.reason,
        )

        sync_mock.assert_called_once_with(
            background,
            db,
            run,
            event,
        )

        build_context_mock.assert_called_once_with(
            db,
            run,
        )

        background.add_task.assert_called_once_with(
            run_auto_mock,
            "run-1",
            "gemini",
            "gemini-2.5-flash",
            "mock prompt",
        )

        self.assertEqual(
            result["agent"],
            "gemini",
        )

        self.assertEqual(
            result["model"],
            "gemini-2.5-flash",
        )

        self.assertEqual(
            result["routing_mode"],
            "auto",
        )

    def test_auto_nao_cria_runtime_tmux_dinamico_por_padrao(self):
        """tmux é terminal persistente manual, não orquestrador do AUTO.

        Sem o opt-in explícito, um build AUTO ainda classifica, roteia e
        enfileira — mas nenhuma sessão dinâmica `auto-<agent>-<run_id>` é
        criada. O agente recolhe a execução na sua sessão de sempre.
        """
        db = Mock()
        background = Mock()

        plan = SimpleNamespace(
            id="plan-1", backlog_id="task-1", status="approved",
        )
        task = SimpleNamespace(
            id="task-1", project_id="project-1", title="Criar endpoint CRUD",
            description="Adicionar endpoint FastAPI", priority="medium",
        )
        project = SimpleNamespace(id="project-1", name="WorkDev")
        assessment = SimpleNamespace(
            level="medium", score=48,
            required_capabilities=("code", "reasoning"),
            reason="teste", signals=(),
        )
        decision = RoutingDecision(
            agent="gemini", provider="gemini", model="gemini-2.5-flash",
            catalog_id="gemini-2-5-flash", reasoning_effort=None,
            complexity="medium", complexity_score=48, capability_score=100,
            matched_capabilities=("code", "reasoning"),
            missing_capabilities=(), category="economic",
            estimated_price_index=None, requires_confirmation=False,
            reason="AUTO selecionou Gemini 2.5 Flash",
        )
        run = SimpleNamespace(
            id="run-1", plan_id="plan-1", backlog_id="task-1", agent="gemini",
            model="gemini-2.5-flash", routing_mode="auto", status="queued",
        )
        event = SimpleNamespace(id="event-1")

        with (
            patch("app.routers.handoffs._get_plan", return_value=plan),
            patch(
                "app.routers.handoffs._task_project",
                return_value=(task, project),
            ),
            patch(
                "app.routers.handoffs.classify_task",
                return_value=assessment,
            ),
            patch("app.routers.handoffs.load_subtasks", return_value=[]),
            patch("app.routers.handoffs.route_agent", return_value=decision),
            patch(
                "app.routers.handoffs.queue_build",
                return_value=(run, event),
            ),
            patch("app.routers.handoffs._sync_run"),
            patch(
                "app.routers.handoffs._run_out",
                return_value={"id": "run-1", "routing_mode": "auto"},
            ),
            patch(
                "app.routers.handoffs.build_context",
            ) as build_context_mock,
            patch("app.routers.handoffs.start_agent_runtime") as start_mock,
        ):
            result = send_to_build(
                plan_id="plan-1",
                payload=BuildRequest(routing_mode="auto"),
                background=background,
                db=db,
            )

        build_context_mock.assert_not_called()
        start_mock.assert_not_called()
        background.add_task.assert_not_called()
        self.assertEqual(result["routing_mode"], "auto")

    def test_flag_do_runtime_auto_e_desligada_por_padrao(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_auto_runtime_enabled())

        with patch.dict(
            os.environ,
            {"WORKDEV_AUTO_RUNTIME_ENABLED": "true"},
            clear=True,
        ):
            self.assertTrue(_auto_runtime_enabled())

    @patch("app.routers.handoffs.finalize_auto_runtime", return_value={})
    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch("app.routers.handoffs.start_agent_runtime")
    @patch("app.routers.handoffs.SessionLocal")
    def test_auto_runtime_completes_successful_headless_run(
        self, session_local, start_runtime, _sync, _finalize,
    ):
        db = Mock()
        session_local.return_value = db
        run = SimpleNamespace(
            id="run-1", plan_id="plan-1", backlog_id="task-1",
            agent="gemini", routing_mode="auto", status="queued",
        )

        def apply_status(_db, current, data):
            current.status = data["status"]
            return current, SimpleNamespace(id=f"event-{data['status']}")

        with (
            patch("app.routers.handoffs._get_run", return_value=run),
            patch(
                "app.routers.handoffs._task_project",
                return_value=(
                    SimpleNamespace(id="task-1"),
                    SimpleNamespace(id="project-1"),
                ),
            ),
            patch(
                "app.routers.handoffs.update_run",
                side_effect=apply_status,
            ) as update_mock,
        ):
            _run_auto_agent(
                "run-1", "gemini", "gemini-2.5-flash", "prompt",
            )

        self.assertEqual(
            [call.args[2]["status"] for call in update_mock.call_args_list],
            ["running", "completed"],
        )
        start_runtime.assert_called_once_with(
            "gemini", "prompt", model="gemini-2.5-flash", run_id="run-1",
        )
        db.close.assert_called_once()

    @patch("app.routers.handoffs.finalize_auto_runtime", return_value={})
    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch(
        "app.routers.handoffs.start_agent_runtime",
        side_effect=RuntimeError("runtime indisponível"),
    )
    @patch("app.routers.handoffs.SessionLocal")
    def test_auto_runtime_records_launch_failure(
        self, session_local, _start_runtime, _sync, _finalize,
    ):
        db = Mock()
        session_local.return_value = db
        run = SimpleNamespace(
            id="run-1", plan_id="plan-1", backlog_id="task-1",
            agent="gemini", routing_mode="auto", status="queued",
        )

        def apply_status(_db, current, data):
            current.status = data["status"]
            return current, SimpleNamespace(id=f"event-{data['status']}")

        with (
            patch("app.routers.handoffs._get_run", return_value=run),
            patch(
                "app.routers.handoffs._task_project",
                return_value=(
                    SimpleNamespace(id="task-1"),
                    SimpleNamespace(id="project-1"),
                ),
            ),
            patch(
                "app.routers.handoffs.update_run",
                side_effect=apply_status,
            ) as update_mock,
        ):
            _run_auto_agent(
                "run-1", "gemini", "gemini-2.5-flash", "prompt",
            )

        self.assertEqual(
            [call.args[2]["status"] for call in update_mock.call_args_list],
            ["running", "failed"],
        )
        self.assertEqual(
            update_mock.call_args_list[-1].args[2]["error"],
            "runtime indisponível",
        )
        db.close.assert_called_once()

    @patch("app.routers.handoffs._start_auto_monitor")
    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch("app.routers.handoffs.start_agent_runtime")
    @patch("app.routers.handoffs.SessionLocal")
    def test_interactive_auto_runtime_remains_running_after_prompt_delivery(
        self, session_local, start_runtime, _sync, start_monitor,
    ):
        db = Mock()
        session_local.return_value = db
        run = SimpleNamespace(
            id="run-1", plan_id="plan-1", backlog_id="task-1",
            agent="codex", routing_mode="auto", status="queued",
        )

        def apply_status(_db, current, data):
            current.status = data["status"]
            return current, SimpleNamespace(id=f"event-{data['status']}")

        with (
            patch("app.routers.handoffs._get_run", return_value=run),
            patch(
                "app.routers.handoffs._task_project",
                return_value=(
                    SimpleNamespace(id="task-1"),
                    SimpleNamespace(id="project-1"),
                ),
            ),
            patch(
                "app.routers.handoffs.update_run",
                side_effect=apply_status,
            ) as update_mock,
        ):
            _run_auto_agent("run-1", "codex", "gpt-5", "prompt")

        self.assertEqual(len(update_mock.call_args_list), 1)
        self.assertEqual(update_mock.call_args.args[2]["status"], "running")
        start_runtime.assert_called_once_with("codex", "prompt", model="gpt-5", run_id="run-1")
        start_monitor.assert_called_once_with("run-1", "codex")
        db.close.assert_called_once()

    def test_auto_finalizes_runtime_before_persisting_completion(self):
        db = Mock()
        background = Mock()

        run = SimpleNamespace(
            id="run-1",
            agent="gemini",
            routing_mode="auto",
            status="running",
        )

        event = SimpleNamespace(
            id="event-1",
        )

        payload = RunUpdate(
            status="completed",
            result="validações concluídas",
        )

        with (
            patch(
                "app.routers.handoffs._get_run",
                return_value=run,
            ),
            patch(
                "app.routers.handoffs.update_run",
                return_value=(run, event),
            ) as update_mock,
            patch(
                "app.routers.handoffs._sync_run",
            ) as sync_mock,
            patch(
                "app.routers.handoffs.finalize_auto_runtime",
                return_value={"stopped": True, "standby_process": "gemini"},
            ) as finalize_mock,
            patch(
                "app.routers.handoffs._run_out",
                return_value={
                    "id": "run-1",
                    "agent": "gemini",
                    "status": "completed",
                    "routing_mode": "auto",
                },
            ),
        ):
            result = update_agent_run(
                run_id="run-1",
                payload=payload,
                background=background,
                db=db,
            )

        update_mock.assert_called_once()
        sync_mock.assert_called_once_with(
            background,
            db,
            run,
            event,
        )

        finalize_mock.assert_called_once_with("gemini", "run-1")
        background.add_task.assert_not_called()

        self.assertEqual(
            result["status"],
            "completed",
        )

    def test_auto_completion_requires_persisted_result(self):
        run = SimpleNamespace(
            id="run-1", agent="codex", routing_mode="auto", status="running",
        )
        with (
            patch("app.routers.handoffs._get_run", return_value=run),
            self.assertRaises(Exception) as raised,
        ):
            update_agent_run(
                "run-1", RunUpdate(status="completed"), Mock(), Mock(),
            )
        self.assertIn("exige resultado", str(raised.exception.detail))

    def test_premium_confirmation_continues_auto_without_manual_choice(self):
        payload = BuildRequest(routing_mode="auto", premium_confirmed=True)
        self.assertTrue(payload.premium_confirmed)
        self.assertIsNone(payload.agent)
        self.assertIsNone(payload.model)

    def test_monitor_persists_failure_after_runtime_disappears_and_cleanup(self):
        db = Mock()
        run = SimpleNamespace(
            id="run-1", plan_id="plan-1", backlog_id="task-1",
            agent="codex", routing_mode="auto", status="running",
        )

        def apply_status(_db, current, data):
            current.status = data["status"]
            current.error = data["error"]
            return current, SimpleNamespace(id="event-failed")

        with (
            patch("app.routers.handoffs.SessionLocal", return_value=db),
            patch("app.routers.handoffs._get_run", return_value=run),
            patch("app.routers.handoffs.time.sleep"),
            patch("app.routers.handoffs.auto_runtime_running", return_value=False),
            patch("app.routers.handoffs.finalize_auto_runtime", return_value={}) as finalize,
            patch("app.routers.handoffs.update_run", side_effect=apply_status),
            patch("app.routers.handoffs._sync_auto_transition"),
        ):
            _monitor_auto_agent("run-1", "codex", 60)

        finalize.assert_called_once_with("codex", "run-1")
        self.assertEqual(run.status, "failed")
        self.assertIn("antes de registrar resultado", run.error)


if __name__ == "__main__":
    unittest.main()
