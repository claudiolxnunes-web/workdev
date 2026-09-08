import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services.handoff import (
    HandoffError,
    approve_plan,
    update_run,
    task_requires_deploy,
    promote_pending_subtasks,
)


class StatusTransitionAutomationTest(unittest.TestCase):
    def test_approve_plan_only_marks_plan_approved(self):
        db = Mock()
        plan = SimpleNamespace(
            id=uuid4(),
            backlog_id=uuid4(),
            status="draft",
            acceptance_criteria=["crit"],
            validation_steps=["step"],
            created_by="ai_hub",
        )

        result = approve_plan(db, plan)

        self.assertEqual(result.status, "approved")
        self.assertIsNotNone(result.approved_at)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(plan)

    def test_approve_plan_never_routes_or_queues_build(self):
        db = Mock()
        plan = SimpleNamespace(
            id=uuid4(),
            backlog_id=uuid4(),
            status="draft",
            acceptance_criteria=["crit"],
            validation_steps=["step"],
            created_by="ai_hub",
        )

        with (
            patch("app.services.agent_router.route_agent") as route_mock,
            patch("app.services.handoff.queue_build") as queue_mock,
        ):
            result = approve_plan(db, plan)

        self.assertEqual(result.status, "approved")
        route_mock.assert_not_called()
        queue_mock.assert_not_called()

    def test_create_plan_raises_handoff_error_if_plan_already_exists(self):
        from app.services.handoff import create_plan
        db = Mock()
        backlog_id = uuid4()
        task = SimpleNamespace(id=backlog_id, title="Test Task")
        active_plan = SimpleNamespace(id=uuid4(), status="draft", version=1)

        # Mock query return values:
        # First query: finds task
        # Second query: finds active_plan
        db.query.return_value.filter.return_value.first.side_effect = [task, active_plan]

        with self.assertRaisesRegex(HandoffError, "Já existe um plano ativo ou aprovado"):
            create_plan(db, {"backlog_id": backlog_id})

    def test_task_requires_deploy_detection(self):
        db = Mock()
        backlog_id = uuid4()
        project_id = uuid4()

        # Case 1: Project has VPS deployment target
        task = SimpleNamespace(id=backlog_id, project_id=project_id)
        project = SimpleNamespace(id=project_id, vps="VPS1", supabase_project=None, netlify_project=None, vercel_project=None)
        db.query.return_value.filter.return_value.first.side_effect = [task, project]

        self.assertTrue(task_requires_deploy(db, backlog_id))

        # Case 2: Project has Netlify deployment target
        project = SimpleNamespace(id=project_id, vps=None, supabase_project=None, netlify_project="my-site", vercel_project=None)
        db.query.return_value.filter.return_value.first.side_effect = [task, project]

        self.assertTrue(task_requires_deploy(db, backlog_id))

        # Case 3: No deployment target
        project = SimpleNamespace(id=project_id, vps=None, supabase_project=None, netlify_project=None, vercel_project=None)
        db.query.return_value.filter.return_value.first.side_effect = [task, project]

        self.assertFalse(task_requires_deploy(db, backlog_id))

    def test_promote_pending_subtasks_creates_new_tasks_and_respects_idempotency(self):
        db = Mock()
        task = SimpleNamespace(id=uuid4(), project_id=uuid4(), title="Task Mãe", sprint="Sprint 1")
        
        # 1 active subtask, 1 completed subtask
        active_subtask = SimpleNamespace(id=uuid4(), title="Subtask Ativa", status="todo")
        completed_subtask = SimpleNamespace(id=uuid4(), title="Subtask Feita", status="done")
        db.query.return_value.filter.return_value.all.return_value = [active_subtask, completed_subtask]

        # First run: not promoted yet (mock find to return None)
        db.query.return_value.filter.return_value.first.return_value = None

        promote_pending_subtasks(db, task)

        # Should add the new task to session
        db.add.assert_called_once()
        promoted_task = db.add.call_args[0][0]
        self.assertEqual(promoted_task.title, "Subtask Ativa")
        self.assertIn(f"[subtask_ref: {active_subtask.id}]", promoted_task.description)

        # Second run: already promoted (mock find to return the existing task)
        db.add.reset_mock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=uuid4())
        promote_pending_subtasks(db, task)
        db.add.assert_not_called()  # No duplicate created

    def test_update_run_completed_sets_task_done_and_promotes_if_no_deploy_required(self):
        db = Mock()
        run = SimpleNamespace(id=uuid4(), backlog_id=uuid4(), status="running", agent="gemini")
        task = SimpleNamespace(id=run.backlog_id, status="doing")
        db.query.return_value.filter.return_value.first.return_value = task

        # Mock task_requires_deploy to return False
        with (
            patch("app.services.test_gate.validate_run_for_status_change", return_value=(True, "Gate aprovado")),
            patch("app.services.handoff.task_requires_deploy", return_value=False),
            patch("app.services.handoff.promote_pending_subtasks") as promote_mock,
        ):
            update_run(db, run, {"status": "completed"})

            self.assertEqual(task.status, "done")
            promote_mock.assert_called_once()

    def test_update_run_completed_keeps_task_doing_if_deploy_required(self):
        db = Mock()
        run = SimpleNamespace(id=uuid4(), backlog_id=uuid4(), status="running", agent="gemini")
        task = SimpleNamespace(id=run.backlog_id, status="doing")
        db.query.return_value.filter.return_value.first.return_value = task

        # Mock task_requires_deploy to return True
        with (
            patch("app.services.test_gate.validate_run_for_status_change", return_value=(True, "Gate aprovado")),
            patch("app.services.handoff.task_requires_deploy", return_value=True),
            patch("app.services.handoff.promote_pending_subtasks") as promote_mock,
        ):
            update_run(db, run, {"status": "completed"})

            self.assertEqual(task.status, "doing")  # Kept as doing
            promote_mock.assert_not_called()


class BacklogValidationRouterTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.env_patcher = patch.dict("os.environ", {"WORKDEV_API_KEY": "segredo-de-teste"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("app.routers.backlog.SessionLocal")
    def test_backlog_update_status_blocks_done_when_subtasks_pending(self, mock_session_local):
        db_mock = Mock()
        mock_session_local.return_value = db_mock

        # Mock BacklogItem existence
        task_id = uuid4()
        task = SimpleNamespace(id=task_id, status="doing")
        db_mock.query.return_value.filter.return_value.first.return_value = task

        # Mock a pending subtask
        pending_subtask = SimpleNamespace(id=uuid4(), title="Subtask Pendente", status="todo")
        db_mock.query.return_value.filter.return_value.all.return_value = [pending_subtask]

        # Request status change to done with X-API-Key header
        response = self.client.patch(
            f"/api/backlog/{task_id}/status?status=done",
            headers={"X-API-Key": "segredo-de-teste"}
        )

        self.assertEqual(response.status_code, 400)
        json_data = response.json()
        self.assertEqual(json_data["detail"]["code"], "active_subtasks_remaining")
        self.assertIn("Subtask Pendente", json_data["detail"]["message"])

    def test_create_deployment_outcome_validation_and_closure(self):
        from app.database import get_db
        from datetime import datetime
        db_mock = Mock()
        app.dependency_overrides[get_db] = lambda: db_mock

        def mock_add(obj):
            obj.id = uuid4()
            obj.created_at = datetime.utcnow()
        db_mock.add.side_effect = mock_add

        try:
            run_id = uuid4()
            task_id = uuid4()

            # Case 1: Postcheck success closes the task
            run = SimpleNamespace(id=run_id, backlog_id=task_id)
            task = SimpleNamespace(id=task_id, status="doing")
            # Mock database lookup for deployment outcomes, runs and task
            db_mock.query.return_value.filter.return_value.first.side_effect = [
                None,  # No existing outcome (to proceed)
                run,   # AgentRun check passes
                task,  # BacklogItem existence validation
                task,  # BacklogItem closure lookup
            ]

            payload = {
                "proof_id": "test-proof-123",
                "project": "workdev-core",
                "artifact_fingerprint": "xyz123",
                "outcome": "success",
                "postcheck_result": {"status": "DEPLOY_SUCCEEDED"},
                "agent_run_id": str(run_id),
                "backlog_id": str(task_id),
            }

            with patch("app.services.handoff.promote_pending_subtasks") as promote_mock:
                response = self.client.post(
                    "/api/deployments/outcomes",
                    json=payload,
                    headers={"X-API-Key": "segredo-de-teste"}
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(task.status, "done")
                promote_mock.assert_called_once()

            # Case 2: Postcheck failed does NOT close the task
            task.status = "doing"
            db_mock.query.return_value.filter.return_value.first.side_effect = [
                None,  # No existing outcome
                run,   # AgentRun passes
                task,  # BacklogItem
            ]

            payload["postcheck_result"] = {"status": "DEPLOY_FAILED"}

            with patch("app.services.handoff.promote_pending_subtasks") as promote_mock:
                response = self.client.post(
                    "/api/deployments/outcomes",
                    json=payload,
                    headers={"X-API-Key": "segredo-de-teste"}
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(task.status, "doing")  # Kept as doing
                promote_mock.assert_not_called()

            # Case 3: Invalid/spoofed backlog_id returns HTTP 400
            different_task_id = uuid4()
            payload["backlog_id"] = str(different_task_id)
            db_mock.query.return_value.filter.return_value.first.side_effect = [
                None,  # No existing outcome
                run,   # AgentRun check
            ]

            response = self.client.post(
                "/api/deployments/outcomes",
                json=payload,
                headers={"X-API-Key": "segredo-de-teste"}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("backlog_id não corresponde", response.json()["detail"])
            # Case 4: Nonexistent standalone backlog_id returns HTTP 400
            payload["proof_id"] = "test-proof-invalid-backlog"
            payload["agent_run_id"] = None
            payload["backlog_id"] = str(uuid4())
            db_mock.query.return_value.filter.return_value.first.side_effect = [
                None,  # No existing outcome
                None,  # BacklogItem does not exist
            ]

            response = self.client.post(
                "/api/deployments/outcomes",
                json=payload,
                headers={"X-API-Key": "segredo-de-teste"}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("backlog_id especificado não existe", response.json()["detail"])

        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
