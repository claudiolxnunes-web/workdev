import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import ai
from app.services import autoridade as aut


TASK_ID = "11111111-1111-1111-1111-111111111111"


class PlanPreviewApprovalTest(unittest.TestCase):

    def test_preview_nao_persiste_nem_cria_plan_id(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            id=TASK_ID,
            title="Task de teste",
            project_id="22222222-2222-2222-2222-222222222222",
        )

        saida = json.loads(ai.executar_tool(
            "previsualizar_plano_execucao",
            {
                "task_id": TASK_ID,
                "objetivo": "Corrigir o fluxo de planos",
                "escopo": "AI Hub",
                "restricoes": ["Não executar automaticamente"],
                "criterios_aceite": ["Prévia não persiste"],
                "validacoes": ["Executar testes"],
                "notas_implementacao": "Revisão humana obrigatória",
            },
            db,
            aut.PLAN,
        ))

        self.assertTrue(saida["ok"])
        self.assertTrue(saida["preview"])
        self.assertFalse(saida["persistido"])
        self.assertIsNone(saida["plano_id"])
        self.assertIsNone(saida["versao"])
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_criacao_sem_aprovacao_nao_toca_no_banco(self):
        db = Mock()

        saida = json.loads(ai.executar_tool(
            "criar_plano_execucao",
            {
                "task_id": TASK_ID,
                "objetivo": "Corrigir o fluxo de planos",
                "criterios_aceite": ["Plano único"],
                "validacoes": ["Executar testes"],
                "aprovado_pelo_usuario": False,
            },
            db,
            aut.PLAN,
        ))

        self.assertFalse(saida["executado"])
        self.assertIn("aprovação explícita", saida["erro"])
        db.query.assert_not_called()
        db.add.assert_not_called()
        db.commit.assert_not_called()

    @patch.object(ai, "create_plan")
    def test_criacao_aprovada_materializa_um_plano(self, create_plan):
        db = Mock()
        task = SimpleNamespace(
            id=TASK_ID,
            title="Task de teste",
            project_id="22222222-2222-2222-2222-222222222222",
        )
        db.query.return_value.filter.return_value.first.return_value = task

        create_plan.return_value = SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            version=1,
            status="draft",
        )

        with patch.object(ai.graph_sync, "sync_safely"):
            saida = json.loads(ai.executar_tool(
                "criar_plano_execucao",
                {
                    "task_id": TASK_ID,
                    "objetivo": "Corrigir o fluxo de planos",
                    "escopo": "AI Hub",
                    "restricoes": [],
                    "criterios_aceite": ["Plano único"],
                    "validacoes": ["Executar testes"],
                    "aprovado_pelo_usuario": True,
                },
                db,
                aut.PLAN,
            ))

        self.assertTrue(saida["ok"])
        self.assertEqual(saida["plano_id"], "33333333-3333-3333-3333-333333333333")
        self.assertEqual(saida["versao"], 1)
        self.assertEqual(saida["status"], "draft")
        create_plan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
