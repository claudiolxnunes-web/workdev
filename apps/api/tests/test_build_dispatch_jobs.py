"""Fatia 2 — despacho vira linha no banco, com lock e idempotência.

O achado 5 do plano de correção: `POST /runs/{id}/dispatch` lia a run, conferia
o status e chamava o driver. Dois POSTs simultâneos passavam os dois — duas
inferências, custo dobrado, e nada registrando a primeira.

Estes testes cobrem as duas defesas e a diferença entre elas:

- `with_for_update()` serializa requisições concorrentes na MESMA run;
- o índice parcial `uq_agent_build_jobs_active_run` (migração `c3f9a5b28d41`)
  cobre o que o lock não alcança: outro processo, outro worker, outra réplica.
  Quem perde recebe IntegrityError no INSERT e vira 409 — não um `if`.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.services import build_jobs


def _run(**overrides):
    base = dict(
        id=uuid4(),
        agent="local-code",
        status="running",
        model=None,
        dispatch_state="idle",
        dispatch_attempts=0,
        last_dispatch_at=None,
        dispatch_token=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _db_com_run(run):
    """Sessão falsa cujo `with_for_update().first()` devolve a run travada."""
    db = Mock()
    cadeia = db.query.return_value.filter.return_value
    cadeia.with_for_update.return_value.first.return_value = run
    cadeia.first.return_value = run
    return db


class AberturaDeJob(unittest.TestCase):
    def test_abre_sob_lock_e_marca_a_run(self):
        run = _run(dispatch_attempts=2)
        db = _db_com_run(run)

        with patch.object(build_jobs, "active_job", return_value=None):
            job = build_jobs.open_job(
                db, run, runtime_id="local-code", model="qwen2.5-coder:14b",
                prompt_sha256="a" * 64,
            )

        # O lock tem que ter sido pedido: sem ele, duas requisições
        # simultâneas leem a mesma ausência de job ativo e ambas inserem.
        db.query.return_value.filter.return_value.with_for_update \
            .assert_called_once()

        self.assertEqual(job.state, "queued")
        self.assertEqual(job.attempt, 3, "attempt continua de onde a run parou")
        self.assertEqual(run.dispatch_state, build_jobs.DISPATCH_QUEUED)
        self.assertEqual(run.dispatch_attempts, 3)
        self.assertIsNotNone(run.last_dispatch_at)
        self.assertIsNotNone(run.dispatch_token)

    def test_job_ativo_existente_vira_conflito_com_o_job_vivo(self):
        run = _run()
        db = _db_com_run(run)
        vivo = SimpleNamespace(
            id=uuid4(), run_id=run.id, state="running", runtime_id="local-code",
            model="m", attempt=1, prompt_sha256=None, error=None,
            created_at=None, started_at=None, finished_at=None,
        )

        with patch.object(build_jobs, "active_job", return_value=vivo):
            with self.assertRaises(build_jobs.DispatchConflict) as caso:
                build_jobs.open_job(
                    db, run, runtime_id="local-code", model="m",
                )

        self.assertIs(caso.exception.job, vivo)
        # Nada foi tocado na run: um despacho recusado não conta tentativa.
        self.assertEqual(run.dispatch_attempts, 0)
        self.assertEqual(run.dispatch_state, "idle")

    def test_corrida_perdida_no_banco_devolve_o_vencedor(self):
        """O `if` da aplicação passou, o índice parcial é que barrou."""
        run = _run()
        db = _db_com_run(run)
        vencedor = SimpleNamespace(
            id=uuid4(), run_id=run.id, state="queued", runtime_id="local-code",
            model="m", attempt=1, prompt_sha256=None, error=None,
            created_at=None, started_at=None, finished_at=None,
        )
        db.flush.side_effect = IntegrityError("insert", {}, Exception("uq"))

        respostas = [None, vencedor]

        with patch.object(
            build_jobs, "active_job", side_effect=lambda *_: respostas.pop(0)
        ):
            with self.assertRaises(build_jobs.DispatchConflict) as caso:
                build_jobs.open_job(
                    db, run, runtime_id="local-code", model="m",
                )

        self.assertIs(caso.exception.job, vencedor)
        db.rollback.assert_called_once()


class CicloDeVida(unittest.TestCase):
    def _job(self, **kw):
        base = dict(
            id=uuid4(), run_id=uuid4(), state="queued", runtime_id="local-code",
            model="m", attempt=1, prompt_sha256=None, error=None, payload={},
            created_at=None, started_at=None, finished_at=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_start_marca_running_na_run_e_no_job(self):
        run = _run()
        db = _db_com_run(run)
        job = self._job(run_id=run.id)

        build_jobs.start_job(db, job)

        self.assertEqual(job.state, "running")
        self.assertIsNotNone(job.started_at)
        self.assertEqual(run.dispatch_state, build_jobs.DISPATCH_RUNNING)

    def test_finish_marca_dispatched(self):
        run = _run()
        db = _db_com_run(run)
        job = self._job(run_id=run.id, state="running")

        build_jobs.finish_job(db, job, payload={"duration_ms": 12})

        self.assertEqual(job.state, "done")
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.payload["duration_ms"], 12)
        self.assertEqual(run.dispatch_state, build_jobs.DISPATCH_DONE)

    def test_fail_guarda_o_motivo(self):
        run = _run()
        db = _db_com_run(run)
        job = self._job(run_id=run.id, state="running")

        build_jobs.fail_job(
            db, job, error="runtime indisponível", payload={"code": "x"},
        )

        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "runtime indisponível")
        self.assertEqual(run.dispatch_state, build_jobs.DISPATCH_FAILED)


class ModelDeclaraOQueOBancoTem(unittest.TestCase):
    """O ORM tem que declarar as colunas que a migração criou.

    Este teste nasceu de um 500 em produção (2026-09-09, 7 ocorrências no
    journal do workdev-api às 23:21). A migração `b2e8f4a17c30` criou
    dispatch_state/attempts/last_dispatch_at/token em `agent_runs`, mas o model
    AgentRun nunca foi atualizado — ler `run.dispatch_state` pelo ORM levantava
    AttributeError e derrubava toda rota que serializasse uma run.

    Os testes de serviço não pegam isso: eles usam Mock e SimpleNamespace, que
    aceitam qualquer atributo. Só olhando o model de verdade é que aparece.
    """

    def test_agent_run_declara_as_colunas_de_despacho(self):
        from app.models.handoff import AgentRun

        colunas = {c.name for c in AgentRun.__table__.columns}

        for nome in (
            "dispatch_state",
            "dispatch_attempts",
            "last_dispatch_at",
            "dispatch_token",
        ):
            self.assertIn(nome, colunas, f"{nome} existe no banco e não no ORM")

    def test_instancia_real_nao_estoura_no_acesso(self):
        from app.models.handoff import AgentRun

        run = AgentRun()

        # Antes do INSERT o valor é None (o default é server_default). O que não
        # pode acontecer é AttributeError — que foi exatamente o 500.
        self.assertIsNone(run.dispatch_state)
        self.assertIsNone(run.dispatch_attempts)

    def test_build_job_declara_o_que_o_servico_escreve(self):
        from app.models.handoff import AgentBuildJob

        colunas = {c.name for c in AgentBuildJob.__table__.columns}

        for nome in (
            "run_id", "runtime_id", "model", "state", "attempt",
            "prompt_sha256", "error", "payload", "started_at", "finished_at",
        ):
            self.assertIn(nome, colunas)


class Fingerprint(unittest.TestCase):
    def test_mesmo_prompt_mesma_impressao(self):
        self.assertEqual(
            build_jobs.prompt_fingerprint("plano X"),
            build_jobs.prompt_fingerprint("plano X"),
        )

    def test_prompt_diferente_muda_a_impressao(self):
        self.assertNotEqual(
            build_jobs.prompt_fingerprint("plano X"),
            build_jobs.prompt_fingerprint("plano Y"),
        )

    def test_tem_64_hex(self):
        impressao = build_jobs.prompt_fingerprint("qualquer")
        self.assertEqual(len(impressao), 64)
        int(impressao, 16)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
