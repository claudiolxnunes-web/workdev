import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers.repository import repository_status


def _fake_project(github_url):
    return SimpleNamespace(github_url=github_url)


class RepositoryStatusTest(unittest.TestCase):
    def test_no_project_returns_not_configured(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = repository_status("nutricontrole", db)

        self.assertFalse(result["configured"])

    def test_unrecognized_url_reports_error(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _fake_project(
            "https://not-github.example.com/foo"
        )

        result = repository_status("feed-bpf", db)

        self.assertTrue(result["configured"])
        self.assertIn("error", result)

    @patch("app.routers.repository.httpx.Client")
    def test_public_repo_returns_branch_and_commit(self, mock_client_cls):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _fake_project(
            "https://github.com/claudiolxnunes-web/workdev"
        )

        client = mock_client_cls.return_value.__enter__.return_value
        repo_resp = Mock(status_code=200)
        repo_resp.json.return_value = {"default_branch": "develop"}
        repo_resp.raise_for_status = Mock()
        commit_resp = Mock()
        commit_resp.json.return_value = {
            "sha": "abcdef1234567890",
            "commit": {
                "message": "feat: algo\n\ndetalhes",
                "author": {"name": "Cláudio", "date": "2026-08-01T00:00:00Z"},
            },
            "html_url": "https://github.com/claudiolxnunes-web/workdev/commit/abcdef1",
        }
        commit_resp.raise_for_status = Mock()
        runs_resp = Mock(status_code=200)
        runs_resp.json.return_value = {"workflow_runs": []}
        client.get.side_effect = [repo_resp, commit_resp, runs_resp]

        result = repository_status("workdev-core", db)

        self.assertTrue(result["configured"])
        self.assertEqual(result["default_branch"], "develop")
        self.assertEqual(result["last_commit"]["sha"], "abcdef1")
        self.assertEqual(result["last_commit"]["message"], "feat: algo")
        self.assertIsNone(result["ci"])

    @patch("app.routers.repository.httpx.Client")
    def test_private_repo_without_token_reports_clear_error(self, mock_client_cls):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _fake_project(
            "https://github.com/claudiolxnunes-web/private-repo"
        )
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.return_value = Mock(status_code=404)

        result = repository_status("nutrigestor-crm", db)

        self.assertTrue(result["configured"])
        self.assertIn("privado", result["error"].lower())


if __name__ == "__main__":
    unittest.main()
