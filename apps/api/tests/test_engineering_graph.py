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
    def test_sync_backlog_capitalized_feature_is_a_feature(self):
        """Regressão de 2026-11-09: o tipo do backlog não é normalizado.

        No Postgres existem 120 itens com type 'feature' e 2 com 'Feature'
        (capitalizado). A comparação exata mandava os 2 capitalizados para o
        ramo de Task: o node existia, mas com o tipo errado — e a
        reconciliação via HAS_FEATURE não os encontrava.
        """
        self.sync.sync_project = Mock(return_value={"id": "project-node"})
        self.sync.ensure_node = Mock(return_value={"id": "feature-node"})
        self.sync.ensure_edge = Mock()

        self.sync.sync_backlog("task-2", "project-1", "Feature")

        self.sync.ensure_node.assert_called_once_with(
            "Feature", "task-2", "project-1"
        )
        self.sync.ensure_edge.assert_called_once_with(
            "project-node", "feature-node", "HAS_FEATURE"
        )

    def test_sync_backlog_other_types_stay_task(self):
        self.sync.sync_project = Mock(return_value={"id": "project-node"})
        self.sync.ensure_node = Mock(return_value={"id": "task-node"})
        self.sync.ensure_edge = Mock()

        self.sync.sync_backlog("task-3", "project-1", "bug")

        self.sync.ensure_node.assert_called_once_with(
            "Task", "task-3", "project-1"
        )

    def test_sync_backlog_empty_type_is_task(self):
        self.sync.sync_project = Mock(return_value={"id": "project-node"})
        self.sync.ensure_node = Mock(return_value={"id": "task-node"})
        self.sync.ensure_edge = Mock()

        self.sync.sync_backlog("task-4", "project-1", "")

        self.sync.ensure_node.assert_called_once_with(
            "Task", "task-4", "project-1"
        )

    def test_delete_node_removes_edges_before_the_node(self):
        """Cascade: as edges saem junto, senão o node fica acorrentado ao nada."""
        self.sync._request = Mock(return_value=[{"id": "node-1"}])

        self.assertTrue(self.sync.delete_node("ADR", "adr-1", "project-1"))

        chamadas = [c.args for c in self.sync._request.call_args_list]
        metodos = [c[0][0] for c in self.sync._request.call_args_list]
        # Primeiro as edges, depois o node.
        self.assertEqual(metodos, ["GET", "DELETE", "DELETE"])
        self.assertEqual(chamadas[1][1], "graph_edges")
        self.assertEqual(chamadas[2][1], "graph_nodes")

    def test_delete_node_filters_by_type_and_project(self):
        self.sync._request = Mock(return_value=[])
        self.sync.delete_node("Feature", "f-1", "p-1")

        params = self.sync._request.call_args_list[0].kwargs["params"]
        self.assertEqual(params["entity_id"], "eq.f-1")
        self.assertEqual(params["type"], "eq.Feature")
        self.assertEqual(params["project_id"], "eq.p-1")

    def test_delete_node_without_project_does_not_filter_by_it(self):
        """Sem project_id, o node e procurado so por entity_id e tipo."""
        self.sync._request = Mock(return_value=[])
        self.sync.delete_node("ADR", "adr-1")

        params = self.sync._request.call_args_list[0].kwargs["params"]
        self.assertNotIn("project_id", params)

    def test_delete_node_absent_is_not_an_error(self):
        """Já removido: nada a fazer, e nao é erro."""
        self.sync._request = Mock(return_value=[])
        self.assertFalse(self.sync.delete_node("ADR", "adr-1", "p-1"))
        self.assertEqual(self.sync._request.call_count, 1)

    def test_delete_safely_swallows_failure(self):
        """Falha no grafo nao desfaz o DELETE no Postgres."""
        self.sync._request = Mock(side_effect=RuntimeError("supabase fora"))
        self.assertFalse(self.sync.delete_safely("ADR", "adr-1", "p-1"))

    def test_delete_safely_without_configuration(self):
        sync = EngineeringGraphSync(None, None)
        self.assertFalse(sync.delete_safely("ADR", "adr-1", "p-1"))

if __name__ == "__main__":
    unittest.main()
