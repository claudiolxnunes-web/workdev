"""Regressão: o payload do chat não é canal de mudança de privilégio (E1.4).

Uma auditoria independente demonstrou que `POST /api/ai/chat` persistia o
campo `authority` do corpo da mensagem — uma sessão em `observe` podia ser
elevada a `execute` ou `admin` mandando o campo junto com o texto.

A regra violada: **a autoridade persistida na sessão é a fonte de verdade, e
uma mensagem de chat nunca pode elevá-la.** Só o PATCH explícito altera.

Cada teste aqui é um dos ataques demonstrados.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import ai
from app.routers.ai import ChatRequest
from app.services import autoridade as aut


def _sessao(authority="observe", **kwargs):
    padroes = dict(id="sess-1", title="Conversa", project_id=None,
                   authority=authority,
                   created_at="2026-08-17 00:00:00",
                   updated_at="2026-08-17 00:00:00")
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


class _Capturado:
    """Guarda o nível com que o provider foi realmente chamado."""

    def __init__(self):
        self.nivel = None

    def __call__(self, messages, db, model=None, system=None,
                 nivel=aut.NIVEL_PADRAO, **kwargs):
        self.nivel = nivel
        return "resposta"


def _chamar(payload_authority, sessao):
    """Executa ai_chat com a sessão dada e devolve (nível usado, resposta)."""
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = sessao
    capturado = _Capturado()
    req = ChatRequest(
        messages=[{"role": "user", "content": "cria uma task"}],
        session_id="sess-1",
        authority=payload_authority,
        provider="anthropic",
        model="claude-haiku-4-5",
    )
    with patch.object(ai, "chat_anthropic", capturado), \
         patch.object(ai, "build_system", return_value="system"):
        resposta = ai.ai_chat(req, db)
    return capturado.nivel, resposta, sessao, db


class PayloadNaoElevaTest(unittest.TestCase):
    """(a)-(d): sessão OBSERVE resiste a qualquer valor no payload."""

    def _assert_continua_observe(self, payload_valor):
        sessao = _sessao("observe")
        nivel, resposta, sessao, db = _chamar(payload_valor, sessao)

        self.assertEqual(nivel, aut.OBSERVE,
                         f"payload '{payload_valor}' mudou o nível efetivo")
        self.assertEqual(sessao.authority, "observe",
                         f"payload '{payload_valor}' persistiu na sessão")
        self.assertEqual(resposta["authority"], aut.OBSERVE)
        return resposta

    def test_a_observe_com_payload_plan_continua_observe(self):
        self._assert_continua_observe("plan")

    def test_b_observe_com_payload_execute_continua_observe(self):
        self._assert_continua_observe("execute")

    def test_c_observe_com_payload_admin_continua_observe(self):
        self._assert_continua_observe("admin")

    def test_d_observe_com_payload_root_nao_normaliza_para_plan(self):
        resposta = self._assert_continua_observe("root")

        self.assertNotEqual(resposta["authority"], aut.PLAN)

    def test_payload_divergente_e_sinalizado_na_resposta(self):
        sessao = _sessao("observe")
        _, resposta, _, _ = _chamar("admin", sessao)

        self.assertTrue(resposta["authority_payload_ignorada"])

    def test_payload_coerente_nao_sinaliza(self):
        sessao = _sessao("observe")
        _, resposta, _, _ = _chamar("observe", sessao)

        self.assertFalse(resposta["authority_payload_ignorada"])

    def test_sem_payload_nao_sinaliza(self):
        sessao = _sessao("observe")
        _, resposta, _, _ = _chamar(None, sessao)

        self.assertFalse(resposta["authority_payload_ignorada"])
        self.assertEqual(resposta["authority"], aut.OBSERVE)


class PayloadNaoRebaixaNemSobrescreveTest(unittest.TestCase):
    """(e): sessão PLAN também não é alterada por payload adulterado."""

    def test_e_plan_com_payload_observe_permanece_plan(self):
        sessao = _sessao("plan")
        nivel, resposta, sessao, _ = _chamar("observe", sessao)

        self.assertEqual(nivel, aut.PLAN)
        self.assertEqual(sessao.authority, "plan")
        self.assertEqual(resposta["authority"], aut.PLAN)

    def test_e_plan_com_payload_admin_permanece_plan(self):
        sessao = _sessao("plan")
        nivel, resposta, sessao, _ = _chamar("admin", sessao)

        self.assertEqual(nivel, aut.PLAN)
        self.assertEqual(sessao.authority, "plan")

    def test_payload_nunca_gera_evento_de_auditoria(self):
        """Trocar de nível é evento; o payload não troca, então não registra."""
        sessao = _sessao("observe")
        with patch("app.services.chat_audit.registrar_troca_autoridade") as reg:
            _chamar("admin", sessao)

        reg.assert_not_called()


class SomentePatchAlteraTest(unittest.TestCase):
    """(f): o PATCH explícito é o único mecanismo de mudança."""

    def test_ai_chat_nao_importa_o_registrador_de_troca(self):
        import inspect

        fonte = inspect.getsource(ai.ai_chat)
        self.assertNotIn("registrar_troca_autoridade", fonte)
        self.assertNotIn("session.authority =", fonte)

    def test_patch_altera_e_audita(self):
        from app.routers import chat_sessions as cs
        from app.schemas.chat import SessionUpdate

        sessao = _sessao("observe")
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = sessao
        with patch.object(cs.chat_audit, "registrar_troca_autoridade") as reg:
            saida = cs.atualizar_contexto(
                "sess-1", SessionUpdate.model_validate({"authority": "plan"}), db
            )

        self.assertEqual(sessao.authority, "plan")
        self.assertEqual(saida["authority"], "plan")
        reg.assert_called_once()

    def test_patch_recusa_nivel_invalido(self):
        from app.schemas.chat import SessionUpdate

        with self.assertRaises(Exception):
            SessionUpdate.model_validate({"authority": "root"})


class SessaoNovaTest(unittest.TestCase):
    def test_sessao_nova_usa_o_padrao_e_nao_o_payload(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        capturado = _Capturado()
        req = ChatRequest(
            messages=[{"role": "user", "content": "oi"}],
            session_id=None,
            authority="admin",
            provider="anthropic",
            model="claude-haiku-4-5",
        )
        with patch.object(ai, "chat_anthropic", capturado), \
             patch.object(ai, "build_system", return_value="system"):
            resposta = ai.ai_chat(req, db)

        self.assertEqual(capturado.nivel, aut.NIVEL_PADRAO)
        self.assertEqual(resposta["authority"], aut.NIVEL_PADRAO)
        self.assertNotEqual(resposta["authority"], aut.ADMIN)


class ContratoTest(unittest.TestCase):
    def test_campo_segue_aceito_para_nao_quebrar_clientes(self):
        """Compatibilidade: aceitar e ignorar, em vez de recusar a requisição."""
        req = ChatRequest(
            messages=[{"role": "user", "content": "oi"}], authority="admin"
        )

        self.assertEqual(req.authority, "admin")

    def test_documentacao_marca_o_campo_como_nao_autoritativo(self):
        import inspect

        fonte = inspect.getsource(ChatRequest)
        self.assertIn("NÃO AUTORITATIVO", fonte)


if __name__ == "__main__":
    unittest.main()
