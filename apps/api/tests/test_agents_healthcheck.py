import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[3] / "scripts" / "agents_healthcheck.py"
SPEC = importlib.util.spec_from_file_location("agents_healthcheck", SCRIPT)
healthcheck = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = healthcheck
SPEC.loader.exec_module(healthcheck)


class AgentHealthClassificationTest(unittest.TestCase):
    def classify(self, process: str, output: str):
        return healthcheck.classify(
            "kimi", "kimi", process, output, datetime.now(timezone.utc).isoformat()
        )

    def test_shell_process_is_offline(self):
        result = self.classify("bash", "")
        self.assertEqual(result.status, "offline")

    def test_authentication_error_is_blocked(self):
        result = self.classify("kimi-code", "Error 401 Missing Authentication header")
        self.assertEqual((result.status, result.reason), ("blocked", "authentication"))

    def test_insufficient_balance_is_blocked_without_restart(self):
        result = self.classify("kimi-code", "429 account suspended due to insufficient balance")
        self.assertEqual((result.status, result.reason), ("blocked", "billing"))

    def test_running_agent_is_busy(self):
        result = self.classify("kimi-code", "Working (12s • esc to interrupt)")
        self.assertEqual(result.status, "busy")

    def test_gemini_thinking_is_busy(self):
        result = self.classify("node", "Thinking... (esc to cancel, 5m 40s)")
        self.assertEqual(result.status, "busy")

    def test_prompt_ready_agent_is_idle(self):
        result = self.classify("kimi-code", "Kimi Code\n> ")
        self.assertEqual(result.status, "idle")

    def test_only_claude_and_codex_are_always_on(self):
        self.assertEqual(healthcheck.ALWAYS_ON_AGENTS, frozenset({"claude", "codex"}))

    def test_shell_snapshot_does_not_trigger_destructive_recovery(self):
        from app.services import agent_lifecycle as lifecycle
        state = lifecycle.AgentState(agent='gemini', session='gemini', session_exists=True, current_process='bash')
        with patch.object(lifecycle, 'read_state', return_value=state), \
             patch.object(lifecycle, 'read_operation', return_value={}), \
             patch.object(lifecycle, 'start') as start:
            result = healthcheck.collect_agent('gemini', 'gemini', None, allow_restart=True)
        self.assertEqual(result.runtime_state.value, 'ERROR')
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def test_waiting_input_takes_precedence_over_busy_text():
    row = healthcheck.classify('codex', 'codex', 'codex',
        'Working (esc to interrupt)\nWould you like to proceed?\n1. Yes, proceed',
        datetime.now(timezone.utc).isoformat())
    assert row.status == 'waiting_input'


def test_consolidation_reports_survivors_and_missing_models_as_error(tmp_path, monkeypatch):
    from app.services import agent_lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    for state in [
        lifecycle.AgentState(agent='codex', session='codex', group_pids=[123]),
        lifecycle.AgentState(agent='local-code', session=None, model='m', model_loaded=None),
    ]:
        monkeypatch.setattr(lifecycle, 'read_state', lambda *args, **kw: state)
        row = healthcheck.collect_agent(state.agent, state.session, None)
        assert row.runtime_state.value == 'ERROR'


def test_disconnect_intent_prevents_always_on_restart(tmp_path, monkeypatch):
    from app.services import agent_lifecycle as lifecycle, agent_snapshot
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    agent_snapshot.atomic_json(lifecycle.operation_file('codex'), {'phase': 'completed', 'desired': 'OFFLINE'})
    monkeypatch.setattr(lifecycle, 'read_state', lambda *args, **kw: lifecycle.AgentState(agent='codex', session='codex'))
    def forbidden(*args, **kwargs):
        raise AssertionError('explicit disconnect must survive the healthcheck')
    monkeypatch.setattr(lifecycle, 'start', forbidden)
    row = healthcheck.collect_agent('codex', 'codex', None, allow_restart=True)
    assert row.runtime_state.value == 'OFFLINE'


def test_dead_lifecycle_owner_becomes_error(tmp_path, monkeypatch):
    from app.services import agent_lifecycle as lifecycle, agent_snapshot
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    agent_snapshot.atomic_json(lifecycle.operation_file('codex'), {
        'phase': 'STOPPING', 'desired': 'OFFLINE', 'running': True,
        'boot_id': 'old-boot', 'updated_at': agent_snapshot.now(),
    })
    monkeypatch.setattr(lifecycle, 'read_state', lambda *args, **kw: lifecycle.AgentState(
        agent='codex', session='codex', session_exists=True, current_process='codex'))
    monkeypatch.setattr(healthcheck, 'capture_recent', lambda *_args: '')
    row = healthcheck.collect_agent('codex', 'codex', None)
    assert row.runtime_state.value == 'ERROR'
    assert row.reason == 'lifecycle_interrupted'
