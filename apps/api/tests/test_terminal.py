import asyncio
import os
import unittest
from unittest.mock import patch

from app.routers.terminal import (
    ALLOWED_SESSIONS,
    _capture_history,
    _claim,
    _release,
    _send_output,
)


class FailingWebSocket:
    async def send_bytes(self, _data: bytes) -> None:
        raise RuntimeError("client disconnected")


class TerminalLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_agents_have_isolated_tmux_sessions(self):
        self.assertEqual(
            ALLOWED_SESSIONS,
            {"claude": "code", "codex": "codex", "kimi": "kimi", "qwen": "qwen"},
        )

    async def test_output_sender_stops_when_websocket_disconnects(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"terminal output")
            os.close(write_fd)
            write_fd = -1

            await asyncio.wait_for(
                _send_output(FailingWebSocket(), read_fd),
                timeout=1,
            )
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    async def test_connection_claim_can_be_released(self):
        session = "test-terminal-lifecycle"
        await _release(session)

        self.assertTrue(await _claim(session))
        self.assertFalse(await _claim(session))

        await _release(session)
        self.assertTrue(await _claim(session))
        await _release(session)

    @patch("app.routers.terminal.subprocess.run")
    async def test_history_uses_tmux_capture_pane_without_shell(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "linha antiga\nlinha atual\n"
        run.return_value.stderr = ""

        self.assertEqual(_capture_history("codex", 5000), "linha antiga\nlinha atual")
        run.assert_called_once_with(
            ["tmux", "capture-pane", "-p", "-J", "-S", "-5000", "-t", "codex"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

if __name__ == "__main__":
    unittest.main()
