"""Contrato do projeto ativo da sessão (E1.3).

O contexto é propriedade da sessão, não da tela: quem manda é
`chat_sessions.project_id`. Estes testes fixam esse contrato.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

from fastapi import HTTPException

from app.routers import chat_sessions as cs
from app.schemas.chat import SessionUpdate

UUID_VALIDO = UUID("11111111-1111-1111-1111-111111111111")


def _sessao(**kwargs):
    padroes = dict(
        id="sess-1", title="Conversa", project_id=None,
        created_at="2026-08-16 22:00:00", updated_at="2026-08-16 22:10:00",
    )
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


def _projeto(**kwargs):
    padroes = dict(id="proj-1", slug="feed-bpf", name="Feed_BPF")
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


class SessaoOutTest(unittest.TestCase):
    def test_sessao_global_nao_traz_projeto(self):
        saida = cs.sessao_out(_sessao())

        self.assertIsNone(saida["project_id"])
        self.assertIsNone(saida["project_slug"])
        self.assertIsNone(saida["project_name"])

    def test_sessao_com_projeto_traz_slug_e_nome(self):
        saida = cs.sessao_out(_sessao(project_id="proj-1"), _projeto())

        self.assertEqual(saida["project_id"], "proj-1")
        self.assertEqual(saida["project_slug"], "feed-bpf")
        self.assertEqual(saida["project_name"], "Feed_BPF")

    def test_forma_da_sessao_e_estavel(self):
        """Listar e abrir precisam devolver as mesmas chaves."""
        esperadas = {"id", "title", "project_id", "project_slug",
                     "project_name", "created_at", "updated_at"}

        self.assertEqual(set(cs.sessao_out(_sessao())), esperadas)

    def test_authority_nao_vaza_no_contrato(self):
        """A coluna existe desde a E1.1, mas sem o gate da E1.4 não é contrato."""
        self.assertNotIn("authority", cs.sessao_out(_sessao()))


class AtualizarContextoTest(unittest.TestCase):
    def _db_com(self, sessao, projeto=None):
        db = Mock()
        sessao_q = Mock()
        sessao_q.filter.return_value.first.return_value = sessao
        projeto_q = Mock()
        projeto_q.filter.return_value.first.return_value = projeto
        db.query.side_effect = [sessao_q, projeto_q]
        return db

    def test_define_projeto_ativo(self):
        sessao = _sessao()
        projeto = _projeto(id=UUID_VALIDO)
        db = self._db_com(sessao, projeto)
        payload = SessionUpdate.model_validate({"project_id": str(UUID_VALIDO)})

        saida = cs.atualizar_contexto("sess-1", payload, db)

        self.assertEqual(sessao.project_id, UUID_VALIDO)
        self.assertEqual(saida["project_slug"], "feed-bpf")
        db.commit.assert_called_once()

    def test_null_devolve_conversa_ao_escopo_global(self):
        sessao = _sessao(project_id="proj-1")
        db = Mock()
        sessao_q = Mock()
        sessao_q.filter.return_value.first.return_value = sessao
        db.query.return_value = sessao_q

        payload = SessionUpdate.model_validate({"project_id": None})
        saida = cs.atualizar_contexto("sess-1", payload, db)

        self.assertIsNone(sessao.project_id)
        self.assertIsNone(saida["project_slug"])
        db.commit.assert_called_once()

    def test_projeto_inexistente_e_422(self):
        db = self._db_com(_sessao(), projeto=None)
        payload = SessionUpdate.model_validate(
            {"project_id": "11111111-1111-1111-1111-111111111111"})

        with self.assertRaises(HTTPException) as erro:
            cs.atualizar_contexto("sess-1", payload, db)

        self.assertEqual(erro.exception.status_code, 422)
        db.commit.assert_not_called()

    def test_sessao_inexistente_e_404(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(HTTPException) as erro:
            cs.atualizar_contexto(
                "sumiu", SessionUpdate.model_validate({"project_id": None}), db)

        self.assertEqual(erro.exception.status_code, 404)

    def test_payload_sem_campo_algum_e_422(self):
        """Omitir project_id é diferente de mandar null — e não é atualização."""
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _sessao()

        with self.assertRaises(HTTPException) as erro:
            cs.atualizar_contexto("sess-1", SessionUpdate(), db)

        self.assertEqual(erro.exception.status_code, 422)
        db.commit.assert_not_called()


class SessionUpdateTest(unittest.TestCase):
    def test_omitir_difere_de_null(self):
        omitido = SessionUpdate()
        nulo = SessionUpdate.model_validate({"project_id": None})

        self.assertNotIn("project_id", omitido.model_dump(exclude_unset=True))
        self.assertIn("project_id", nulo.model_dump(exclude_unset=True))

    def test_uuid_invalido_e_rejeitado(self):
        with self.assertRaises(Exception):
            SessionUpdate.model_validate({"project_id": "nao-e-uuid"})


class ProjetosDasSessoesTest(unittest.TestCase):
    def test_resolve_projetos_em_uma_consulta(self):
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = [_projeto()]
        sessoes = [_sessao(project_id="proj-1"), _sessao(project_id="proj-1"),
                   _sessao()]

        mapa = cs._projetos_das_sessoes(db, sessoes)

        db.query.assert_called_once()
        self.assertEqual(mapa["proj-1"].slug, "feed-bpf")

    def test_sem_projeto_nao_consulta_o_banco(self):
        db = Mock()

        self.assertEqual(cs._projetos_das_sessoes(db, [_sessao()]), {})
        db.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
