"""API → Git real → política → persistência. Nenhum diff sintético."""
from types import SimpleNamespace
import subprocess

import pytest

from tests.test_review_lifecycle import lifecycle_api, add_evidence
from app.services import review_cycle, review_scope, review_policy, review_package, test_gate


@pytest.fixture
def task_repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Review test')
    git('config', 'user.email', 'review@example.invalid')
    (root / 'auth.py').write_text('\n'.join('old_sensitive_line' for _ in range(900)))
    git('add', '.')
    git('commit', '-qm', 'Unrelated sensitive history')
    base = git('rev-parse', 'HEAD')
    return root, git, base


def bind_repo(monkeypatch, root):
    real_collect = review_cycle.collect_diff_stats
    real_summary = review_scope.diff_summary
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda run: real_collect(run, root))
    monkeypatch.setattr(review_package, 'collect_diff_stats', lambda run: real_collect(run, root))
    monkeypatch.setattr(review_package, 'diff_summary', lambda run: real_summary(run, root))


@pytest.mark.parametrize('sensitive,expected', [(False, 'completed'), (True, 'review')])
def test_real_git_http_policy_and_cycle(lifecycle_api, task_repo, monkeypatch, sensitive, expected):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    root, git, base = task_repo
    (root / ('auth.py' if sensitive else 'readme.md')).write_text('one task change\n')
    git('add', '.')
    git('commit', '-qm', 'This task only')
    target = git('rev-parse', 'HEAD')
    bind_repo(monkeypatch, root)
    monkeypatch.setattr(test_gate, '_get_git_commit_sha', lambda *_: target)
    with factory() as db:
        db.add(Event(run_id=run_id, event_type=review_scope.BASE_EVENT,
                     payload={'base_sha': base}))
        add_evidence(db, Run, Event, run_id)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(Run, run_id).status == expected
        cycle = db.query(Cycle).one()
        assert cycle.diff_files == 1
        assert cycle.context_bytes > 0 and cycle.tokens_estimate > 0
        if not sensitive:
            assert cycle.task_risk == 'low'
            assert cycle.diff_lines == 1
    package = client.get(f'/api/handoffs/runs/{run_id}/review-context').json()
    assert package['base_sha'] == base and package['commit_sha'] == target
    assert len(package['files_changed']) == 1
    assert 'diff' not in package
    expanded = client.get(f'/api/handoffs/runs/{run_id}/review-context?expand=diff').json()
    assert 'one task change' in expanded['diff']
    if not sensitive:
        assert 'old_sensitive_line' not in expanded['diff']


def test_missing_after_initial_gate_returns_to_executor(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    # The first validation succeeds; evidence disappears before policy recheck.
    monkeypatch.setattr(test_gate, 'validate_run_for_status_change', lambda *_: (True, 'PASS'))
    monkeypatch.setattr(test_gate, 'get_gate_evidence_for_run', lambda *_: None)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(Run, run_id).status == 'running'
        assert db.query(Cycle).one().decision == 'NO_REVIEW_GATE_FAIL'


def test_minimal_context_never_collects_full_diff(lifecycle_api, monkeypatch):
    client, run_id, *_ = lifecycle_api
    def forbidden(*args):
        raise AssertionError('minimal context must not request patch')
    monkeypatch.setattr(review_package, 'collect_diff_stats', forbidden)
    assert client.get(f'/api/handoffs/runs/{run_id}/review-context').status_code == 200


def test_count_only_changed_lines_and_honest_medium_reason():
    patch = 'diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n context\n'
    assert review_policy.changed_lines(patch) == 2
    decision = review_policy.decide('medium', 'trusted', 'pass', executor='codex')
    assert decision.tier == 'economic'
    assert 'médio' in decision.justification and 'confiável' in decision.justification


def test_manual_start_captures_base_once(lifecycle_api, task_repo, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    root, git, base = task_repo
    monkeypatch.setattr(review_scope, 'repo_root', lambda: root)
    with factory() as db:
        db.get(Run, run_id).status = 'queued'
        db.commit()
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'running'})
    assert response.status_code == 200, response.text
    (root / 'readme.md').write_text('new work\n')
    git('add', '.')
    git('commit', '-qm', 'work after start')
    client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'running'})
    with factory() as db:
        assert review_scope.load_base(db, run_id) == base
        assert db.query(Event).filter_by(event_type=review_scope.BASE_EVENT).count() == 1


def test_transfer_retains_original_task_base(lifecycle_api):
    from uuid import uuid4
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    original = uuid4()
    with factory() as db:
        db.add(Event(run_id=original, event_type=review_scope.BASE_EVENT,
                     payload={'base_sha': 'a'*40}))
        db.add(Event(run_id=run_id, event_type='build.transferred',
                     payload={'from_run_id': str(original)}))
        db.commit()
        assert review_scope.load_base(db, run_id) == 'a'*40


def test_worker_reuses_recorded_worktree_base(lifecycle_api):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    with factory() as db:
        db.add(Event(run_id=run_id, event_type='build.committed',
                     payload={'base_sha': 'a'*40, 'commit_sha': 'b'*40}))
        db.commit()
        assert review_scope.load_base(db, run_id) == 'a'*40
