import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.routers import ai
from app.services import autoridade as aut


class SubtaskApprovalTest(unittest.TestCase):

    def test_decompor_sem_aprovacao_nao_toca_no_banco(self):
        db = Mock()

        saida = json.loads(ai.executar_tool(
            "decompor_task",
            {"titulo_task": "Teste", "subtasks": ["A"]},
            db,
            aut.PLAN,
        ))

        self.assertFalse(saida["executado"])
        self.assertFalse(saida["persistido"])
        self.assertIn("aprovação explícita", saida["erro"])
        db.query.assert_not_called()
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_desenhar_subtasks_nao_persiste(self):
        db = Mock()
        q = db.query.return_value
        q.filter.return_value.all.return_value = [
            SimpleNamespace(
                id="11111111-1111-1111-1111-111111111111",
                title="Teste",
            )
        ]

        saida = json.loads(ai.executar_tool(
            "desenhar_subtasks",
            {"titulo_task": "Teste", "subtasks": ["A", "B"]},
            db,
            aut.PLAN,
        ))

        self.assertTrue(saida["ok"])
        self.assertFalse(saida["executado"])
        self.assertFalse(saida["persistido"])
        self.assertTrue(saida["aguarda_aprovacao"])
        self.assertEqual(saida["subtasks_propostas"], ["A", "B"])
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_decompor_bloqueia_se_ja_existirem_subtasks(self):
        db = Mock()
        q_task = Mock()
        q_subtasks = Mock()
        db.query.side_effect = [q_task, q_subtasks]

        q_task.filter.return_value.first.return_value = SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            title="Teste",
            project_id="22222222-2222-2222-2222-222222222222",
        )
        q_subtasks.filter.return_value.count.return_value = 2

        saida = json.loads(ai.executar_tool(
            "decompor_task",
            {
                "titulo_task": "Teste",
                "subtasks": ["A", "B"],
                "aprovado_pelo_usuario": True,
            },
            db,
            aut.PLAN,
        ))

        self.assertFalse(saida["executado"])
        self.assertEqual(saida["quantidade_existente"], 2)
        self.assertIn("nova criação bloqueada", saida["erro"])
        db.add.assert_not_called()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
