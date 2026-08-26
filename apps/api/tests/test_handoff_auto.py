import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers.handoffs import send_to_build
from app.schemas.handoff import BuildRequest
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


if __name__ == "__main__":
    unittest.main()
