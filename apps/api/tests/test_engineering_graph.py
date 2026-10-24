import unittest
from unittest.mock import Mock

from app.services.engineering_graph import EngineeringGraphSync


class EngineeringGraphSyncTest(unittest.TestCase):
    def setUp(self):
        self.sync = EngineeringGraphSync("https://example.supabase.co", "secret")
        self.sync._request = Mock()

    def test_ensure_node_is_idempotent(self):
        existing = {"id": "node-1", "type": "Task"}
        self.sync._request.return_value = [existing]

        result = self.sync.ensure_node("Task", "task-1", "project-1")

        self.assertEqual(result, existing)
        self.assertEqual(self.sync._request.call_count, 1)

    def test_new_secret_key_is_not_sent_as_bearer_token(self):
        sync = EngineeringGraphSync(
            "https://example.supabase.co", "sb_secret_backend"
        )
        self.assertNotIn("Authorization", sync._headers())
        self.assertEqual(sync._headers()["apikey"], "sb_secret_backend")

    def test_legacy_service_role_is_sent_as_bearer_token(self):
        sync = EngineeringGraphSync(
            "https://example.supabase.co", "legacy.jwt.value"
        )
        self.assertEqual(
            sync._headers()["Authorization"], "Bearer legacy.jwt.value"
        )

    def test_sync_backlog_links_project_to_feature(self):
        self.sync.sync_project = Mock(return_value={"id": "project-node"})
        self.sync.ensure_node = Mock(return_value={"id": "feature-node"})
        self.sync.ensure_edge = Mock()

        self.sync.sync_backlog("task-1", "project-1", "feature")

        self.sync.ensure_node.assert_called_once_with(
            "Feature", "task-1", "project-1"
        )
        self.sync.ensure_edge.assert_called_once_with(
            "project-node", "feature-node", "HAS_FEATURE"
        )

    def test_sync_subtask_links_to_existing_parent(self):
        self.sync._find_node = Mock(return_value={"id": "task-node"})
        self.sync.ensure_node = Mock(return_value={"id": "subtask-node"})
        self.sync.ensure_edge = Mock()

        self.sync.sync_subtask("sub-1", "task-1", "project-1")

        self.sync.ensure_edge.assert_called_once_with(
            "task-node", "subtask-node", "HAS_SUBTASK"
        )

    def test_handoff_uses_phase_3_projection(self):
        self.sync.sync_related = Mock(return_value={"id": "node"})
        self.sync._find_node = Mock(return_value={"id": "plan-node"})

        self.sync.sync_plan("plan-1", "project-1", "task-1")
        self.sync.sync_agent_run("run-1", "project-1", "plan-1", "task-1")
        self.sync.sync_agent_event("event-1", "project-1", "run-1")

        self.assertEqual(
            self.sync.sync_related.call_args_list[0].args,
            ("Plan", "plan-1", "project-1", "HAS_PLAN", "task-1"),
        )
        self.assertEqual(
            self.sync.sync_related.call_args_list[1].args,
            ("AgentRun", "run-1", "project-1", "HAS_RUN", "plan-1"),
        )
        self.assertEqual(
            self.sync.sync_related.call_args_list[2].args,
            ("AgentEvent", "event-1", "project-1", "HAS_EVENT", "run-1"),
        )


if __name__ == "__main__":
    unittest.main()
