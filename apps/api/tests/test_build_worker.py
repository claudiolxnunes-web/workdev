"""Consumidor definitivo da fila de Build (ADR 005, fatia 3f)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import build_worker
from app.services.build_executor import BuildOutcome
from app.services.run_pause import RunPaused


class TestInstrucoesDeEnvelope:
    def test_prompt_carrega_o_contrato(self):
        texto = build_worker.ENVELOPE_INSTRUCTIONS

        assert "summary" in texto
        assert "files" in texto
        assert "checks" in texto

    def test_contrato_lista_os_caminhos_proibidos(self):
        texto = build_worker.ENVELOPE_INSTRUCTIONS

        for proibido in (".env", "venv/", ".github/workflows/", "deploy.sh"):
            assert proibido in texto

    def test_contrato_lista_apenas_os_checks_do_gate(self):
        texto = build_worker.ENVELOPE_INSTRUCTIONS

        for check in ("pytest", "vitest", "lint", "build"):
            assert check in texto

    def test_contrato_diz_que_o_modelo_nao_executa(self):
        assert "NÃO executa comandos" in build_worker.ENVELOPE_INSTRUCTIONS

    def test_prompt_final_concatena_contexto_e_contrato(self, monkeypatch):
        monkeypatch.setattr(
            build_worker, "build_context", lambda db, run: {"task": {}}
        )
        monkeypatch.setattr(
            build_worker, "augment_prompt", lambda ctx: "CONTEXTO DO BUILD"
        )

        prompt = build_worker.build_prompt(None, SimpleNamespace(id=uuid4()))

        assert prompt.startswith("CONTEXTO DO BUILD")
        assert "FORMATO OBRIGATÓRIO" in prompt


class TestClaim:
    def test_fila_vazia_devolve_none(self):
        class DbVazio:
            def execute(self, *_args, **_kwargs):
                return SimpleNamespace(first=lambda: None)

        assert build_worker.claim_next_job(DbVazio()) is None

    def test_usa_skip_locked(self):
        """Sem SKIP LOCKED, dois workers serializam na mesma linha."""
        capturado = {}

        class DbEspiao:
            def execute(self, clausula, *_a, **_kw):
                capturado["sql"] = str(clausula)
                return SimpleNamespace(first=lambda: None)

        build_worker.claim_next_job(DbEspiao())

        assert "SKIP LOCKED" in capturado["sql"]
        assert "FOR UPDATE" in capturado["sql"]
        assert "state = 'queued'" in capturado["sql"]
        assert "run.status IN ('queued', 'running')" in capturado["sql"]


def test_response_is_held_without_applying_when_paused(monkeypatch):
    run = SimpleNamespace(id=uuid4())
    job = SimpleNamespace(state='running', payload={'held_response':'response'})
    class Db:
        committed=False
        def commit(self): self.committed=True
    db=Db()
    monkeypatch.setattr(build_worker,'assert_run_can_continue',
                        lambda *_: (_ for _ in ()).throw(RunPaused('paused')))
    monkeypatch.setattr(build_worker,'execute_build',
                        lambda *_a,**_kw: pytest.fail('envelope applied while paused'))
    assert build_worker._apply_response(db,run,job,'response') is None
    assert job.state=='queued'
    assert job.payload['held_response']=='response'
    assert db.committed


def test_pause_during_build_defers_final_transition(monkeypatch):
    run = SimpleNamespace(id=uuid4(), dispatch_attempts=1, status='blocked')
    job = SimpleNamespace(id=uuid4(), attempt=1,
                          payload={'held_response': 'response'}, state='running')
    events = []
    class Db:
        committed = False
        def refresh(self, *_args, **_kwargs): pass
        def commit(self): self.committed = True
    db = Db()
    monkeypatch.setattr(build_worker, 'assert_run_can_continue', lambda *_: run)
    monkeypatch.setattr(build_worker, 'is_paused', lambda *_: True)
    monkeypatch.setattr(build_worker, 'execute_build', lambda *_a, **_kw: BuildOutcome(
        ok=True, code='build_committed', message='done', branch='build/x', gate_passed=True))
    monkeypatch.setattr(build_worker, 'persist_outcome', lambda *_: None)
    monkeypatch.setattr(build_worker, 'add_run_event',
                        lambda _db, _run, kind, *_args: events.append(kind))
    monkeypatch.setattr(build_worker.build_jobs, 'finish_job',
                        lambda _db, item, payload: setattr(item, 'state', 'done'))
    monkeypatch.setattr(build_worker, '_transicionar',
                        lambda *_: pytest.fail('PAUSE was cleared by worker'))
    outcome = build_worker._apply_response(db, run, job, 'response')
    assert outcome.ok
    assert job.payload['deferred_transition'] == 'review'
    assert 'held_response' not in job.payload
    assert 'build.transition_deferred' in events
    assert db.committed


def test_deferred_transition_requires_explicit_resume(monkeypatch):
    run = SimpleNamespace(id=uuid4(), status='running')
    job = SimpleNamespace(id=uuid4(), payload={'deferred_transition': 'review'})
    class Query:
        def filter(self, *_): return self
        def order_by(self, *_): return self
        def first(self): return job
    class Db:
        committed = False
        def query(self, *_): return Query()
        def commit(self): self.committed = True
    db = Db()
    monkeypatch.setattr(build_worker, 'assert_run_can_continue', lambda *_: run)
    monkeypatch.setattr(build_worker, 'update_run',
                        lambda _db, item, data: setattr(item, 'status', data['status']))
    monkeypatch.setattr(build_worker, 'add_run_event', lambda *_: None)
    assert build_worker.continue_paused_outcome(db, run)
    assert run.status == 'review'
    assert 'deferred_transition' not in job.payload
    assert db.committed


class TestHabilitacao:
    def test_fila_cli_independe_da_flag_http(self, monkeypatch):
        monkeypatch.delenv("WORKDEV_OLLAMA_BUILD_ENABLED", raising=False)

        pode, motivo = build_worker.worker_should_run()

        assert pode is True
        assert "WORKDEV_OLLAMA_BUILD_ENABLED" in motivo

    def test_ligado_quando_a_flag_esta_on(self, monkeypatch):
        monkeypatch.setenv("WORKDEV_OLLAMA_BUILD_ENABLED", "true")

        pode, _motivo = build_worker.worker_should_run()

        assert pode is True


class TestTransicao:
    """`completed` não é alcançável pelo worker — é da revisão (ADR 004)."""

    def _run(self, status="running"):
        return SimpleNamespace(id=uuid4(), status=status, agent="local-code")

    def test_gate_aprovado_vai_para_review(self, monkeypatch):
        chamadas = {}

        def falso_update(db, run, dados):
            chamadas["status"] = dados["status"]
            return run, None

        monkeypatch.setattr(build_worker, "update_run", falso_update)

        outcome = BuildOutcome(
            ok=True, code="build_committed", message="ok",
            branch="build/x", gate_passed=True,
        )

        build_worker._transicionar(None, self._run(), outcome)

        assert chamadas["status"] == "review"

    def test_gate_reprovado_vai_para_blocked(self, monkeypatch):
        chamadas = {}

        monkeypatch.setattr(
            build_worker,
            "update_run",
            lambda db, run, dados: (chamadas.setdefault("status", dados["status"]), None),
        )

        outcome = BuildOutcome(
            ok=True, code="build_committed", message="ok",
            branch="build/x", gate_passed=False,
        )

        build_worker._transicionar(None, self._run(), outcome)

        assert chamadas["status"] == "blocked"

    def test_nunca_pede_completed(self, monkeypatch):
        pedidos = []

        monkeypatch.setattr(
            build_worker,
            "update_run",
            lambda db, run, dados: (pedidos.append(dados["status"]), None),
        )

        for passou in (True, False):
            outcome = BuildOutcome(
                ok=True, code="build_committed", message="ok",
                branch="build/x", gate_passed=passou,
            )
            build_worker._transicionar(None, self._run(), outcome)

        assert "completed" not in pedidos

    def test_recusa_do_contrato_nao_apaga_o_trabalho(self, monkeypatch):
        """Transição negada vira evento; o commit já feito não é revertido."""
        from app.services.handoff import HandoffError

        eventos = []

        def update_que_recusa(db, run, dados):
            raise HandoffError("transição não permitida")

        monkeypatch.setattr(build_worker, "update_run", update_que_recusa)
        monkeypatch.setattr(
            build_worker,
            "add_run_event",
            lambda db, run, tipo, msg, payload: eventos.append(tipo),
        )

        outcome = BuildOutcome(
            ok=True, code="build_committed", message="ok",
            branch="build/x", gate_passed=True,
        )

        build_worker._transicionar(None, self._run(), outcome)

        assert eventos == ["build.transition_refused"]

    def test_status_ja_correto_nao_transiciona(self, monkeypatch):
        chamou = []

        monkeypatch.setattr(
            build_worker,
            "update_run",
            lambda *a, **k: chamou.append(1),
        )

        outcome = BuildOutcome(
            ok=True, code="build_committed", message="ok", gate_passed=True,
        )

        build_worker._transicionar(None, self._run(status="review"), outcome)

        assert chamou == []
