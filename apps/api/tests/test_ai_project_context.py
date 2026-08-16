"""Contrato do system prompt do AI Hub.

`build_project_system` mantém a assinatura da E0 (`None` para slug
desconhecido); a montagem em si passou para o Context Engine na E1.2.
`build_system` é o caminho novo: sempre devolve um system, com contexto global
quando não há projeto ativo.
"""

import unittest
from unittest.mock import Mock, patch

from app.routers import ai
from app.services import context_engine as ce


CONTEXTO_PROJETO = {
    "escopo": ce.ESCOPO_PROJETO,
    "gerado_em": "2026-08-16T22:00:00+00:00",
    "projeto": {
        "id": "p1", "nome": "WorkDev Core", "slug": "workdev-core",
        "status": "Production", "tipo": "plataforma", "stack": None,
        "descricao": None, "github_url": None, "vps": None,
        "dev_branch": None, "prod_branch": None,
    },
    "backlog_por_status": {"todo": 1, "done": 1},
    "backlog_aberto": [{
        "id": "1", "titulo": "Implementar X", "status": "todo",
        "prioridade": "high", "tipo": "feature", "sprint": None,
    }],
    "em_andamento": [], "planos": [], "execucoes": [], "adrs": [],
    "knowledge": [],
}

CONTEXTO_GLOBAL = {
    "escopo": ce.ESCOPO_GLOBAL,
    "gerado_em": "2026-08-16T22:00:00+00:00",
    "projetos": [{"slug": "workdev-core", "nome": "WorkDev Core",
                  "status": "Production", "tipo": "plataforma"}],
    "backlog_por_status": {"todo": 2},
    "atencao": [], "planos": [], "execucoes": [], "knowledge": [],
}


class BuildProjectSystemTest(unittest.TestCase):
    def test_returns_none_for_unknown_slug(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=None):
            self.assertIsNone(ai.build_project_system("inexistente", db))

    def test_includes_slug_and_backlog_summary(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=CONTEXTO_PROJETO):
            system = ai.build_project_system("workdev-core", db)

        self.assertIn("workdev-core", system)
        self.assertIn("Implementar X", system)
        self.assertIn("todo", system)

    def test_empty_backlog_still_returns_system(self):
        db = Mock()
        contexto = {**CONTEXTO_PROJETO, "backlog_aberto": [],
                    "backlog_por_status": {}}
        with patch.object(ce, "build_chat_context", return_value=contexto):
            system = ai.build_project_system("nutricontrole", db)

        self.assertIn("nenhum item em aberto", system)

    def test_keeps_base_system_and_project_focus(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=CONTEXTO_PROJETO):
            system = ai.build_project_system("workdev-core", db)

        self.assertIn("assistente do WorkDev", system)
        self.assertIn(ai.FOCO_PROJETO, system)


class BuildSystemTest(unittest.TestCase):
    def test_sem_projeto_usa_contexto_global(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=CONTEXTO_GLOBAL):
            system = ai.build_system(db)

        self.assertIn("Estado atual do WorkDev", system)
        self.assertIn("WorkDev Core (`workdev-core`)", system)
        self.assertNotIn(ai.FOCO_PROJETO, system)

    def test_com_projeto_adiciona_foco(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=CONTEXTO_PROJETO):
            system = ai.build_system(db, "workdev-core")

        self.assertIn("Projeto ativo: WorkDev Core", system)
        self.assertIn(ai.FOCO_PROJETO, system)

    def test_slug_inexistente_degrada_para_global_e_avisa(self):
        db = Mock()
        with patch.object(ce, "build_chat_context", return_value=None), \
             patch.object(ce, "montar_contexto_global", return_value=CONTEXTO_GLOBAL):
            system = ai.build_system(db, "nao-existe")

        self.assertIn("não existe no WorkDev", system)
        self.assertIn("Estado atual do WorkDev", system)

    def test_falha_de_contexto_nao_derruba_a_conversa(self):
        db = Mock()
        with patch.object(ce, "build_chat_context",
                          side_effect=RuntimeError("banco fora")):
            system = ai.build_system(db)

        self.assertIn("contexto indisponível", system)
        self.assertIn("assistente do WorkDev", system)

    def test_system_base_nao_tem_mais_slugs_fixos(self):
        """Os slugs vêm do banco desde a E1.2; a lista fixa mentia (6 de 19)."""
        self.assertNotIn("nutrigestor-crm", ai.SYSTEM)
        self.assertNotIn("openclaw", ai.SYSTEM)


if __name__ == "__main__":
    unittest.main()
