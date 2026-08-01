import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.routers.ai import build_project_system


def _project(**kwargs):
    defaults = dict(id="p1", name="WorkDev Core", slug="workdev-core",
                     status="active", type="produto")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _item(status, priority, title):
    return SimpleNamespace(status=status, priority=priority, title=title)


class BuildProjectSystemTest(unittest.TestCase):
    def test_returns_none_for_unknown_slug(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        self.assertIsNone(build_project_system("inexistente", db))

    def test_includes_slug_and_backlog_summary(self):
        db = Mock()
        project_query = Mock()
        project_query.filter.return_value.first.return_value = _project()
        backlog_query = Mock()
        chained = backlog_query.filter.return_value.order_by.return_value.limit.return_value
        chained.all.return_value = [
            _item("todo", "high", "Implementar X"),
            _item("done", "medium", "Ajustar Y"),
        ]
        db.query.side_effect = [project_query, backlog_query]

        system = build_project_system("workdev-core", db)

        self.assertIn("workdev-core", system)
        self.assertIn("Implementar X", system)
        self.assertIn("todo", system)

    def test_empty_backlog_still_returns_system(self):
        db = Mock()
        project_query = Mock()
        project_query.filter.return_value.first.return_value = _project(slug="nutricontrole")
        backlog_query = Mock()
        chained = backlog_query.filter.return_value.order_by.return_value.limit.return_value
        chained.all.return_value = []
        db.query.side_effect = [project_query, backlog_query]

        system = build_project_system("nutricontrole", db)

        self.assertIn("Backlog vazio", system)


if __name__ == "__main__":
    unittest.main()
