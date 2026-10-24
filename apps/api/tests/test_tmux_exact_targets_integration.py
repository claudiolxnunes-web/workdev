import os
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("tmux"), "tmux não instalado")
class TmuxExactTargetIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.socket = f"/tmp/workdev-tmux-test-{os.getpid()}-{id(self)}.sock"
        result = self.tmux(
            "new-session",
            "-d",
            "-s",
            "codex",
            "sh",
            "-c",
            "printf 'ready\\n'; exec sleep 30",
        )
        if "Operation not permitted" in result.stderr:
            self.skipTest("sandbox não permite criar socket tmux")
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        self.tmux("kill-server")

    def tmux(self, *args):
        return subprocess.run(
            ["tmux", "-S", self.socket, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_exact_pane_target_captures_and_reports_current_command(self):
        capture = self.tmux("capture-pane", "-p", "-S", "-1", "-t", "=codex:")
        display = self.tmux(
            "display-message",
            "-p",
            "-t",
            "=codex:",
            "#{pane_current_command}",
        )

        self.assertEqual(capture.returncode, 0, capture.stderr)
        self.assertIn("ready", capture.stdout)
        self.assertEqual(display.returncode, 0, display.stderr)
        self.assertTrue(display.stdout.strip())

    def test_exact_session_target_never_kills_prefix_match(self):
        stop = self.tmux("kill-session", "-t", "=code")
        survivor = self.tmux("has-session", "-t", "=codex")

        self.assertNotEqual(stop.returncode, 0)
        self.assertEqual(survivor.returncode, 0, survivor.stderr)
