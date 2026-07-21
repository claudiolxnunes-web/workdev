import asyncio
import os
import unittest

from app.routers.terminal import ALLOWED_SESSIONS, _claim, _release, _send_output


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


if __name__ == "__main__":
    unittest.main()
