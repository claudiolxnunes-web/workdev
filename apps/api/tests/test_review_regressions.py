from types import SimpleNamespace
from pathlib import Path
from app.services import review_cycle, review_policy
from tests.test_review_lifecycle import lifecycle_api, add_evidence


def test_missing_diff_must_not_autocomplete(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('repository unavailable')
    monkeypatch.setattr(review_cycle.subprocess, 'run', unavailable)
    decision, _ = review_cycle.evaluate_for_run(SimpleNamespace(agent='kimi', complexity=None), 'pass')
    assert decision.decision != 'NO_REVIEW_COMPLETE'


def test_diff_must_use_run_commit(monkeypatch):
    commands = []
    def capture(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(review_cycle.subprocess, 'run', capture)
    sha = '98140b08605e99253b8798f32fe6040fada98c12'
    review_cycle.collect_diff_stats(SimpleNamespace(commit_sha=sha, branch='task/e45f5f46-review-policy'))
    assert any(sha in arg for command in commands for arg in command), commands


def test_default_config_is_repository_config():
    expected = Path(review_policy.__file__).resolve().parents[4] / 'config/review-policy.json'
    assert expected.exists()
    assert review_policy._CONFIG_PATH == expected


def test_strong_policy_must_route_away_from_economic_reviewer(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['app/auth.py'], 'auth'))
    with factory() as db:
        db.query(Run).filter_by(id=run_id).update({'reviewer_agent': 'qwen', 'complexity': 'high'})
        db.commit()
        add_evidence(db, Run, Event, run_id, passed=True)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.query(Cycle).one().tier == 'strong'
        assert db.query(Run).one().reviewer_agent in ('claude', 'kimi')


def test_partial_diff_failure_must_not_autocomplete(monkeypatch):
    def partial(args, **kwargs):
        if '--name-only' in args:
            return SimpleNamespace(returncode=0, stdout='app/services/worker.py\n')
        return SimpleNamespace(returncode=128, stdout='')
    monkeypatch.setattr(review_cycle.subprocess, 'run', partial)
    decision, _ = review_cycle.evaluate_for_run(SimpleNamespace(agent='kimi', complexity=None, commit_sha='a'*40), 'pass')
    assert decision.decision != 'NO_REVIEW_COMPLETE'


def test_run_without_revision_must_not_use_shared_head(monkeypatch):
    commands = []
    def capture(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(review_cycle.subprocess, 'run', capture)
    decision, _ = review_cycle.evaluate_for_run(SimpleNamespace(agent='kimi', complexity=None, commit_sha=None, branch=None), 'pass')
    assert decision.decision != 'NO_REVIEW_COMPLETE', commands


def test_review_context_handles_missing_diff(lifecycle_api, monkeypatch):
    from app.services import review_package
    client, run_id, *_ = lifecycle_api
    monkeypatch.setattr(review_package, 'collect_diff_stats', lambda *_: None)
    response = client.get(f'/api/handoffs/runs/{run_id}/review-context')
    assert response.status_code in (200, 409, 503)


def test_gate_revision_is_persisted_before_policy(lifecycle_api, monkeypatch):
    from app.services import test_gate
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    expected = test_gate._get_git_commit_sha()
    observed = []
    def diff(run):
        observed.append(run.commit_sha)
        return ['docs/readme.md'], 'docs only'
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', diff)
    with factory() as db:
        add_evidence(db, Run, Event, run_id)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    assert observed == [expected]
    with factory() as db:
        assert db.get(Run, run_id).commit_sha == expected


def test_gate_revision_mismatch_blocks_before_diff(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    def forbidden(*args):
        raise AssertionError('Must not analyze mismatched revision')
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', forbidden)
    with factory() as db:
        db.get(Run, run_id).commit_sha = '0' * 40
        add_evidence(db, Run, Event, run_id)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(Run, run_id).status == 'blocked'
        assert db.query(Cycle).one().decision == 'BLOCKED_OPERATIONAL'


def test_partial_collection_blocks_http_transition(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: None)
    with factory() as db:
        add_evidence(db, Run, Event, run_id)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(Run, run_id).status == 'blocked'


def test_git_fallback_uses_same_base_for_content(monkeypatch):
    commands = []
    def capture(args, **kwargs):
        commands.append(args)
        if any('origin/develop' in arg for arg in args):
            return SimpleNamespace(returncode=128, stdout='')
        return SimpleNamespace(returncode=0, stdout='app/services/worker.py\n' if '--name-only' in args else '+Lock()\n')
    monkeypatch.setattr(review_cycle.subprocess, 'run', capture)
    stats = review_cycle.collect_diff_stats(SimpleNamespace(commit_sha='a' * 40))
    assert stats == (['app/services/worker.py'], '+Lock()\n')
    assert commands[-1][-1] == 'develop...' + 'a' * 40


def test_sensitive_low_never_skips_review():
    decision = review_policy.decide('low', 'trusted', 'pass', sensitive=['auth'], executor='codex')
    assert decision.decision == 'REVISAR'


def test_empty_independent_tier_blocks():
    config = review_policy.load_config()
    config['tier_reviewers']['strong'] = ['codex']
    decision = review_policy.decide('high', 'trusted', 'pass', executor='codex', config=config)
    assert decision.decision == 'BLOCKED_OPERATIONAL'


def test_failed_guardrail_does_not_execute_project_code(monkeypatch):
    from uuid import uuid4
    from app.services import test_gate
    monkeypatch.setattr(test_gate, '_get_git_commit_sha', lambda *_: 'a' * 40)
    monkeypatch.setattr(test_gate, '_check_guardrails', lambda *_: test_gate.CheckResult(
        name='guardrails', passed=False, mandatory=True, reason='root rejected'))
    called = []
    for name in ('_check_pytest', '_check_vitest', '_check_lint', '_check_build'):
        monkeypatch.setattr(test_gate, name, lambda *_: called.append(True))
    result = test_gate.execute_gate(SimpleNamespace(id=uuid4(), backlog_id=uuid4()))
    assert not result.passed
    assert result.mandatory_failed == ['guardrails']
    assert not called
