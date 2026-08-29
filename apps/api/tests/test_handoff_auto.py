import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers.handoffs import _run_auto_agent, send_to_build, update_agent_run
from app.schemas.handoff import BuildRequest, RunUpdate
from app.services.agent_router import RoutingDecision


class HandoffAutoRouteTest(unittest.TestCase):
    def test_auto_routes_before_queueing_build(self):
        db = Mock()
        background = Mock()

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
            [],
        )

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

    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch("app.routers.handoffs.start_agent_runtime")
    @patch("app.routers.handoffs.SessionLocal")
    def test_auto_runtime_completes_successful_headless_run(
        self, session_local, start_runtime, _sync,
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
            _run_auto_agent("run-1", "gemini", "prompt")

        self.assertEqual(
            [call.args[2]["status"] for call in update_mock.call_args_list],
            ["running", "completed"],
        )
        start_runtime.assert_called_once_with("gemini", "prompt")
        db.close.assert_called_once()

    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch(
        "app.routers.handoffs.start_agent_runtime",
        side_effect=RuntimeError("runtime indisponível"),
    )
    @patch("app.routers.handoffs.SessionLocal")
    def test_auto_runtime_records_launch_failure(
        self, session_local, _start_runtime, _sync,
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
            _run_auto_agent("run-1", "gemini", "prompt")

        self.assertEqual(
            [call.args[2]["status"] for call in update_mock.call_args_list],
            ["running", "failed"],
        )
        self.assertEqual(
            update_mock.call_args_list[-1].args[2]["error"],
            "runtime indisponível",
        )
        db.close.assert_called_once()

    @patch("app.routers.handoffs.graph_sync.sync_safely")
    @patch("app.routers.handoffs.start_agent_runtime")
    @patch("app.routers.handoffs.SessionLocal")
    def test_interactive_auto_runtime_remains_running_after_prompt_delivery(
        self, session_local, start_runtime, _sync,
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
            _run_auto_agent("run-1", "codex", "prompt")

        self.assertEqual(len(update_mock.call_args_list), 1)
        self.assertEqual(update_mock.call_args.args[2]["status"], "running")
        start_runtime.assert_called_once_with("codex", "prompt")
        db.close.assert_called_once()

    def test_auto_stops_agent_when_run_completes(self):
        db = Mock()
        background = Mock()

        run = SimpleNamespace(
            id="run-1",
            agent="gemini",
            routing_mode="auto",
            status="completed",
        )

        event = SimpleNamespace(
            id="event-1",
        )

        payload = RunUpdate(
            status="completed",
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
                "app.routers.handoffs.stop_agent_runtime",
            ) as stop_agent_mock,
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

        background.add_task.assert_called_once_with(
            stop_agent_mock,
            "gemini",
        )

        self.assertEqual(
            result["status"],
            "completed",
        )


if __name__ == "__main__":
    unittest.main()
