import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers.database import database_status


def _project(supabase_project=None):
    return SimpleNamespace(supabase_project=supabase_project)


class DatabaseStatusTest(unittest.TestCase):
    def test_no_supabase_project_reports_not_configured(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = database_status("agente-pessoal", db)

        self.assertFalse(result["configured"])

    @patch("app.routers.database.SUPABASE_MANAGEMENT_TOKEN", None)
    def test_configured_without_management_token_reports_clear_blocker(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _project(
            "ilvfwbtfjtnihtsuuzcb"
        )

        result = database_status("nutrigestor-crm", db)

        self.assertTrue(result["configured"])
        self.assertIsNone(result["connected"])
        self.assertIn("SUPABASE_MANAGEMENT_TOKEN", result["error"])

    @patch("app.routers.database.SUPABASE_MANAGEMENT_TOKEN", "sbp_fake")
    @patch("app.routers.database.httpx.Client")
    def test_token_without_project_access_reports_403(self, mock_client_cls):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _project(
            "tebrkrbfsjquqpckslks"
        )
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.return_value = Mock(status_code=403)

        result = database_status("nutricontrole", db)

        self.assertFalse(result["connected"])
        self.assertIn("não tem acesso", result["error"])

    @patch("app.routers.database.SUPABASE_MANAGEMENT_TOKEN", "sbp_fake")
    @patch("app.routers.database.httpx.Client")
    def test_connected_project_returns_table_count_and_size(self, mock_client_cls):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _project(
            "xgvapaebustyotrwnzqa"
        )
        client = mock_client_cls.return_value.__enter__.return_value

        status_resp = Mock(status_code=200)
        status_resp.raise_for_status = Mock()
        status_resp.json.return_value = {
            "status": "ACTIVE_HEALTHY", "region": "sa-east-1",
            "database": {"version": "17.6.1.147"},
        }
        tables_resp = Mock(status_code=201)
        tables_resp.raise_for_status = Mock()
        tables_resp.json.return_value = [{"tables": 104}]
        size_resp = Mock(status_code=201)
        size_resp.raise_for_status = Mock()
        size_resp.json.return_value = [{"size_pretty": "34 MB", "size_bytes": 123}]
        migrations_resp = Mock(status_code=200)
        migrations_resp.json.return_value = [
            {"version": "20260701", "name": "init"},
            {"version": "20260715", "name": "add_index"},
        ]

        client.get.side_effect = [status_resp, migrations_resp]
        client.post.side_effect = [tables_resp, size_resp]

        result = database_status("feed-bpf", db)

        self.assertTrue(result["connected"])
        self.assertEqual(result["table_count"], 104)
        self.assertEqual(result["size_pretty"], "34 MB")
        self.assertEqual(result["recent_migrations"][0]["version"], "20260715")


if __name__ == "__main__":
    unittest.main()
