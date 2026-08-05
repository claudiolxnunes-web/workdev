import unittest
from unittest.mock import Mock

from fastapi import BackgroundTasks, HTTPException

from app.routers.knowledge import criar_conhecimento
from app.schemas.knowledge import KnowledgeCreate


class KnowledgeCreateEndpointTest(unittest.TestCase):
    def test_persiste_entrada_valida_sem_projeto_ou_task(self):
        db = Mock()
        db.refresh.side_effect = lambda entry: setattr(entry, "id", "entry-1")
        payload = KnowledgeCreate(
            title="Stack padrão", content="Decisão registrada em texto",
            category="decisao",
        )

        result = criar_conhecimento(payload, BackgroundTasks(), db)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        self.assertEqual(result.title, "Stack padrão")
        self.assertEqual(result.category, "decisao")

    def test_rejeita_categoria_invalida(self):
        db = Mock()
        payload = KnowledgeCreate(
            title="X", content="Y", category="categoria-inexistente",
        )

        with self.assertRaises(HTTPException) as ctx:
            criar_conhecimento(payload, BackgroundTasks(), db)
        self.assertEqual(ctx.exception.status_code, 400)
        db.add.assert_not_called()

    def test_rejeita_project_id_inexistente(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        payload = KnowledgeCreate(
            title="X", content="Y", category="licao",
            project_id="11111111-1111-1111-1111-111111111111",
        )

        with self.assertRaises(HTTPException) as ctx:
            criar_conhecimento(payload, BackgroundTasks(), db)
        self.assertEqual(ctx.exception.status_code, 404)
        db.add.assert_not_called()

    def test_rejeita_backlog_id_inexistente(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        payload = KnowledgeCreate(
            title="X", content="Y", category="licao",
            backlog_id="22222222-2222-2222-2222-222222222222",
        )

        with self.assertRaises(HTTPException) as ctx:
            criar_conhecimento(payload, BackgroundTasks(), db)
        self.assertEqual(ctx.exception.status_code, 404)
        db.add.assert_not_called()

    def test_agenda_sync_automatico_quando_ha_projeto(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = Mock()
        db.refresh.side_effect = lambda entry: setattr(
            entry, "id", "33333333-3333-4333-8333-333333333333"
        )
        tasks = BackgroundTasks()
        payload = KnowledgeCreate(
            title="Runbook", content="Procedimento validado", category="solucao",
            project_id="11111111-1111-4111-8111-111111111111",
        )

        criar_conhecimento(payload, tasks, db)

        self.assertEqual(len(tasks.tasks), 1)
        task = tasks.tasks[0]
        self.assertEqual(task.args[:5], (
            "sync_related", "Knowledge",
            "33333333-3333-4333-8333-333333333333",
            "11111111-1111-4111-8111-111111111111",
            "LINKED_TO_KNOWLEDGE",
        ))


if __name__ == "__main__":
    unittest.main()
