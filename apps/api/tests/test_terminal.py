import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.terminal import (
    ALLOWED_SESSIONS,
    AgentSendRequest,
    _agent_status,
    _awaiting_approval,
    _capture_history,
    _claim,
    _release,
    _scroll_terminal,
    _send_output,
    _send_text,
    agent_send,
    agents_status,
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

    @patch("app.routers.terminal.subprocess.run")
    async def test_scroll_up_enters_tmux_copy_mode_one_page_up(self, run):
        run.return_value.stdout = "25\n"
        _scroll_terminal("codex", "up")

        self.assertEqual(
            run.call_args_list[0].args[0],
            ["tmux", "copy-mode", "-u", "-t", "codex"],
        )
        self.assertEqual(run.call_args_list[1].args[0], [
            "tmux", "display-message", "-p", "-t", "codex", "#{scroll_position}"
        ])
        self.assertEqual(run.call_count, 2)

    @patch("app.routers.terminal.subprocess.run")
    async def test_scroll_down_returns_to_live_terminal_at_bottom(self, run):
        run.return_value.stdout = "0\n"
        _scroll_terminal("codex", "down")

        self.assertEqual(run.call_args_list[0].args[0], [
            "tmux", "send-keys", "-X", "-t", "codex", "page-down"
        ])
        self.assertEqual(run.call_args_list[2].args[0], [
            "tmux", "send-keys", "-X", "-t", "codex", "cancel"
        ])
        self.assertEqual(run.call_count, 3)

class SendTextTest(unittest.TestCase):
    @patch("app.routers.terminal.subprocess.run")
    def test_sends_literal_text_then_enter(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        _send_text("codex", "gerar relatorio\n")

        self.assertEqual(run.call_args_list[0].args[0], [
            "tmux", "send-keys", "-t", "codex", "-l", "--", "gerar relatorio",
        ])
        self.assertEqual(run.call_args_list[1].args[0], [
            "tmux", "send-keys", "-t", "codex", "Enter",
        ])
        self.assertEqual(run.call_count, 2)

    @patch("app.routers.terminal.subprocess.run")
    def test_blank_text_sends_only_enter_no_literal_call(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        _send_text("codex", "")

        run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "codex", "Enter"],
            capture_output=True, text=True, timeout=5, check=False,
        )

    @patch("app.routers.terminal.subprocess.run")
    def test_raises_when_tmux_session_is_unavailable(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "can't find session"

        with self.assertRaises(RuntimeError):
            _send_text("codex", "oi")


class AgentSendEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_agent(self):
        with self.assertRaises(HTTPException) as ctx:
            await agent_send("desconhecido", AgentSendRequest(text="oi"))
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("app.routers.terminal._send_text")
    async def test_blank_text_is_forwarded_as_a_bare_enter(self, mock_send):
        result = await agent_send("codex", AgentSendRequest(text=""))
        mock_send.assert_called_once_with("codex", "")
        self.assertEqual(result, {"agent": "codex", "sent": True})

    @patch("app.routers.terminal._send_text")
    async def test_sends_text_to_the_mapped_tmux_session(self, mock_send):
        result = await agent_send("claude", AgentSendRequest(text="continuar"))
        mock_send.assert_called_once_with("code", "continuar")
        self.assertEqual(result, {"agent": "claude", "sent": True})

    @patch("app.routers.terminal._send_text", side_effect=RuntimeError("indisponível"))
    async def test_reports_503_when_tmux_session_is_unavailable(self, _mock_send):
        with self.assertRaises(HTTPException) as ctx:
            await agent_send("codex", AgentSendRequest(text="oi"))
        self.assertEqual(ctx.exception.status_code, 503)


class AwaitingApprovalTest(unittest.TestCase):
    @patch("app.routers.terminal._capture_history")
    def test_detects_yes_no_prompt_on_last_line(self, capture):
        capture.return_value = "gerando plano...\npronto.\nProsseguir? (y/n)"
        self.assertTrue(_awaiting_approval("codex"))

    @patch("app.routers.terminal._capture_history")
    def test_detects_claude_style_numbered_menu(self, capture):
        capture.return_value = "Do you want to proceed?\n❯ 1. Yes\n  2. No"
        self.assertTrue(_awaiting_approval("code"))

    @patch("app.routers.terminal._capture_history")
    def test_ignores_normal_output_without_prompt_markers(self, capture):
        capture.return_value = "instalando dependencias...\n1. baixando pacote a\n2. baixando pacote b"
        self.assertFalse(_awaiting_approval("codex"))

    @patch("app.routers.terminal._capture_history")
    def test_ignores_prompt_text_that_already_scrolled_out_of_view(self, capture):
        capture.return_value = "\n".join([
            "Prosseguir? (y/n)",
            "usuario respondeu y",
            "aplicando mudancas",
            "build concluido",
            "continuando execucao normalmente",
        ])
        self.assertFalse(_awaiting_approval("codex"))

    @patch("app.routers.terminal.subprocess.run")
    def test_returns_false_when_tmux_session_is_unavailable(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "can't find session"
        self.assertFalse(_awaiting_approval("codex"))


class AgentStatusTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.routers.terminal._awaiting_approval")
    @patch("app.routers.terminal._current_process")
    async def test_reports_idle_shell_as_not_running_and_not_awaiting(self, current_process, awaiting):
        current_process.return_value = "bash"
        result = await _agent_status("codex", "codex")
        self.assertFalse(result["running"])
        self.assertFalse(result["awaiting_approval"])
        awaiting.assert_not_called()

    @patch("app.routers.terminal._awaiting_approval")
    @patch("app.routers.terminal._current_process")
    async def test_checks_approval_only_when_agent_process_is_running(self, current_process, awaiting):
        current_process.return_value = "claude"
        awaiting.return_value = True
        result = await _agent_status("claude", "code")
        self.assertTrue(result["running"])
        self.assertTrue(result["awaiting_approval"])
        awaiting.assert_called_once_with("code")

    @patch("app.routers.terminal._agent_status")
    async def test_status_endpoint_reports_all_four_agents(self, mock_status):
        mock_status.side_effect = lambda agent, session: {
            "agent": agent, "running": False, "process": "", "awaiting_approval": False,
        }
        result = await agents_status()
        self.assertEqual({item["agent"] for item in result["agents"]}, set(ALLOWED_SESSIONS))


if __name__ == "__main__":
    unittest.main()
