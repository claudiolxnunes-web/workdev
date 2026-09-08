import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.models.chat import ChatMessage, ChatSession
from app.routers import chat_sessions
from app.schemas.chat import SessionFromTask


TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
PROJECT_ID = UUID("22222222-2222-2222-2222-222222222222")
SESSION_ID = UUID("33333333-3333-3333-3333-333333333333")


def _task(**overrides):
    values = dict(
        id=TASK_ID,
        project_id=PROJECT_ID,
        title="Adicionar integração",
        description=None,
        priority="medium",
        sprint=None,
        type="feature",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _project():
    return SimpleNamespace(
        id=PROJECT_ID, name="WorkDev Core", slug="workdev-core"
    )


class TaskContextTest(unittest.TestCase):
    def test_contexto_completo_tolera_campos_ausentes(self):
        context = chat_sessions._task_context(_task(), _project(), [])

        self.assertIn(f"**Task ID:** `{TASK_ID}`", context)
        self.assertIn("**Projeto:** WorkDev Core (`workdev-core`)", context)
        self.assertIn("**Descrição:** Sem descrição", context)
        self.assertIn("**Sprint:** Sem sprint", context)
        self.assertIn("Nenhuma subtask cadastrada", context)
        self.assertIn("permanecer em `draft`", context)
        self.assertIn("não inicie agente ou tmux", context)

    def test_subtasks_sao_ordenadas_e_exibem_status(self):
        subtasks = [
            SimpleNamespace(title="Primeira", status="done"),
            SimpleNamespace(title="Segunda", status="todo"),
        ]

        context = chat_sessions._task_context(_task(), _project(), subtasks)

        self.assertLess(context.index("[done] Primeira"), context.index("[todo] Segunda"))


class CreateSessionFromTaskTest(unittest.TestCase):
    def test_cria_sessao_plan_com_projeto_e_contexto_system(self):
        task_query = Mock()
        task_query.filter.return_value.first.return_value = _task()
        project_query = Mock()
        project_query.filter.return_value.first.return_value = _project()
        active_plan_query = Mock()
        active_plan_query.filter.return_value.first.return_value = None
        existing_session_query = Mock()
        existing_session_query.filter.return_value.first.return_value = None
        subtask_query = Mock()
        subtask_query.filter.return_value.order_by.return_value.all.return_value = []
        db = Mock()
        db.query.side_effect = [task_query, project_query, active_plan_query, existing_session_query, subtask_query]

        def assign_session_id():
            session = db.add.call_args_list[0].args[0]
            session.id = SESSION_ID
            session.created_at = "agora"
            session.updated_at = "agora"

        db.flush.side_effect = assign_session_id

        result = chat_sessions.criar_sessao_da_task(
            SessionFromTask(task_id=TASK_ID), db
        )

        session = db.add.call_args_list[0].args[0]
        message = db.add.call_args_list[1].args[0]
        self.assertIsInstance(session, ChatSession)
        self.assertEqual(session.project_id, PROJECT_ID)
        self.assertEqual(session.authority, "plan")
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "system")
        self.assertIn(str(TASK_ID), message.content)
        self.assertEqual(result["project_slug"], "workdev-core")
        self.assertEqual(result["task_id"], str(TASK_ID))
        db.commit.assert_called_once()

    def test_reutiliza_sessao_existente_da_mesma_task(self):
        task_query = Mock()
        task_query.filter.return_value.first.return_value = _task()
        project_query = Mock()
        project_query.filter.return_value.first.return_value = _project()
        active_plan_query = Mock()
        active_plan_query.filter.return_value.first.return_value = None
        existing_session = SimpleNamespace(
            id=SESSION_ID,
            title="Planejar: Adicionar integração",
            project_id=PROJECT_ID,
            authority="plan",
            created_at="agora",
            updated_at="agora",
        )
        existing_session_query = Mock()
        existing_session_query.filter.return_value.first.return_value = existing_session
        db = Mock()
        db.query.side_effect = [task_query, project_query, active_plan_query, existing_session_query]

        result = chat_sessions.criar_sessao_da_task(
            SessionFromTask(task_id=TASK_ID), db
        )

        self.assertEqual(result["id"], str(SESSION_ID))
        self.assertEqual(result["task_id"], str(TASK_ID))
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_rejeita_sessao_se_plano_ativo_existente(self):
        task_query = Mock()
        task_query.filter.return_value.first.return_value = _task()
        project_query = Mock()
        project_query.filter.return_value.first.return_value = _project()
        active_plan = SimpleNamespace(id=uuid4(), status="approved", version=1)
        active_plan_query = Mock()
        active_plan_query.filter.return_value.first.return_value = active_plan
        db = Mock()
        db.query.side_effect = [task_query, project_query, active_plan_query]

        with self.assertRaises(HTTPException) as error:
            chat_sessions.criar_sessao_da_task(
                SessionFromTask(task_id=TASK_ID), db
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail["code"], "active_plan_exists")
        db.add.assert_not_called()
        db.commit.assert_not_called()


    def test_task_inexistente_retorna_404_sem_escrita(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(HTTPException) as error:
            chat_sessions.criar_sessao_da_task(
                SessionFromTask(task_id=TASK_ID), db
            )

        self.assertEqual(error.exception.status_code, 404)
        db.add.assert_not_called()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
