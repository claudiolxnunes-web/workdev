import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


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

    def test_prompt_ready_agent_is_idle(self):
        result = self.classify("kimi-code", "Kimi Code\n> ")
        self.assertEqual(result.status, "idle")


if __name__ == "__main__":
    unittest.main()
