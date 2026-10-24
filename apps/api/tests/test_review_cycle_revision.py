"""Gate em commit novo: retrabalho após rejeição e tamanho das colunas."""
from types import SimpleNamespace
from unittest.mock import patch

from app.models.review_cycle import ReviewCycle
from app.services import review_cycle

OLD, NEW = "a" * 40, "b" * 40


def _run(commit_sha):
    return SimpleNamespace(commit_sha=commit_sha, agent="claude", reviewer_agent="codex")


def test_gate_em_commit_descendente_da_run_nao_e_divergencia():
    run = _run(OLD)
    with patch.object(review_cycle, "_descends_from", return_value=True), \
         patch.object(review_cycle, "collect_diff_stats", return_value=None):
        decision, _ = review_cycle.evaluate_for_run(run, "pass", gate_sha=NEW)
    assert decision.gate_result != "rev_mismatch"
    assert run.commit_sha == NEW


def test_gate_em_commit_sem_relacao_continua_bloqueando():
    run = _run(OLD)
    with patch.object(review_cycle, "_descends_from", return_value=False):
        decision, _ = review_cycle.evaluate_for_run(run, "pass", gate_sha=NEW)
    assert decision.gate_result == "rev_mismatch"
    assert run.commit_sha == OLD


def test_gate_result_de_divergencia_cabe_na_coluna():
    # SQLite não valida varchar; o Postgres de produção sim (500 em 2026-10-24).
    limite = ReviewCycle.__table__.c.gate_result.type.length
    with patch.object(review_cycle, "_descends_from", return_value=False):
        decision, _ = review_cycle.evaluate_for_run(_run(OLD), "pass", gate_sha=NEW)
    assert len(decision.gate_result) <= limite
