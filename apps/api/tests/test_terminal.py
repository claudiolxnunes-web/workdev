import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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
    _read_pty,
    _load_supervisor_health,
    _requested_terminal_size,
    _send_output,
    _send_text,
    _pane_target,
    _session_target,
    _start_gemini_headless_runtime,
    _start_standby_session,
    _stop_standby_session,
    finalize_auto_runtime,
    agent_send,
    agent_transcript,
    agents_status,
    start_agent_session,
    start_agent_runtime,
    stop_agent_runtime,
    stop_agent_session,
)


class FailingWebSocket:
    async def send_bytes(self, _data: bytes) -> None:
        raise RuntimeError("client disconnected")


class TerminalLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_tmux_targets_require_exact_session_name(self):
        self.assertEqual(_session_target("code"), "=code")
        self.assertEqual(_pane_target("code"), "=code:")

    async def test_all_agents_have_isolated_tmux_sessions(self):
        self.assertEqual(
            ALLOWED_SESSIONS,
            {"claude": "code", "codex": "codex", "kimi": "kimi", "qwen": "qwen", "gemini": "gemini"},
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

    async def test_pty_read_can_be_cancelled_without_blocking_executor(self):
        read_fd, write_fd = os.pipe()
        task = asyncio.create_task(_read_pty(read_fd))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        os.close(read_fd)
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
            ["tmux", "capture-pane", "-p", "-J", "-S", "-5000", "-t", "=codex:"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )


class RequestedTerminalSizeTest(unittest.TestCase):
    def test_accepts_size_inside_limits(self):
        websocket = SimpleNamespace(query_params={"rows": "42", "cols": "132"})
        self.assertEqual(_requested_terminal_size(websocket), (42, 132))

    def test_clamps_untrusted_size(self):
        websocket = SimpleNamespace(query_params={"rows": "999", "cols": "1"})
        self.assertEqual(_requested_terminal_size(websocket), (300, 10))

    def test_uses_safe_default_for_invalid_size(self):
        websocket = SimpleNamespace(query_params={"rows": "invalid", "cols": "80"})
        self.assertEqual(_requested_terminal_size(websocket), (24, 80))


class SendTextTest(unittest.TestCase):
    @patch("app.routers.terminal.subprocess.run")
    def test_sends_literal_text_then_enter(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        _send_text("codex", "gerar relatorio\n")

        self.assertEqual(run.call_args_list[0].args[0], [
            "tmux", "send-keys", "-t", "=codex:", "-l", "--", "gerar relatorio",
        ])
        self.assertEqual(run.call_args_list[1].args[0], [
            "tmux", "send-keys", "-t", "=codex:", "Enter",
        ])
        self.assertEqual(run.call_count, 2)

    @patch("app.routers.terminal.subprocess.run")
    def test_blank_text_sends_only_enter_no_literal_call(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        _send_text("codex", "")

        run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "=codex:", "Enter"],
            capture_output=True, text=True, timeout=5, check=False,
        )

    @patch("app.routers.terminal.subprocess.run")
    def test_raises_when_tmux_session_is_unavailable(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "can't find session"

        with self.assertRaises(RuntimeError):
            _send_text("codex", "oi")

class AgentRuntimeReadinessTest(unittest.TestCase):
    @patch("app.routers.terminal._start_gemini_headless_runtime")
    def test_gemini_uses_headless_runtime(
        self,
        start_headless,
    ):
        start_headless.return_value = {
            "agent": "gemini",
            "session": "gemini",
            "started": True,
            "process": "node",
        }

        result = start_agent_runtime(
            "gemini",
            "execute esta tarefa",
            timeout_seconds=1,
            model="gemini-2.5-flash",
        )

        start_headless.assert_called_once_with(
            "gemini",
            "execute esta tarefa",
            "gemini-2.5-flash",
        )
        self.assertEqual(result["agent"], "gemini")
        self.assertEqual(result["process"], "node")

    @patch("app.routers.terminal.subprocess.run")
    def test_gemini_headless_runs_without_tmux_with_prompt(
        self,
        run,
    ):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        result = _start_gemini_headless_runtime(
            "gemini",
            "execute esta tarefa",
            "gemini-2.5-flash",
        )

        self.assertEqual(
            run.call_args.args[0],
            [
                "/opt/workdev/scripts/start_gemini_agent.sh",
                "--model",
                "gemini-2.5-flash",
                "--prompt",
                "execute esta tarefa",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], "/opt/workdev")
        self.assertEqual(result["agent"], "gemini")
        self.assertTrue(result["started"])

    @patch("app.routers.terminal._send_text")
    @patch("app.routers.terminal._current_process", return_value="codex")
    @patch("app.routers.terminal._start_standby_session", return_value=True)
    def test_auto_runtime_uses_run_scoped_session(self, start_session, current_process, send_text):
        result = start_agent_runtime("codex", "prompt", timeout_seconds=1, run_id="run-1")
        start_session.assert_called_once_with("codex", "auto-codex-run-1")
        send_text.assert_called_once_with("auto-codex-run-1", "prompt")
        self.assertEqual(result["session"], "auto-codex-run-1")
    @patch("app.routers.terminal._stop_standby_session", return_value=True)
    def test_stop_auto_runtime_uses_run_scoped_session(self, stop_session):
        result = stop_agent_runtime("codex", "run-1")
        stop_session.assert_called_once_with("auto-codex-run-1")
        self.assertTrue(result)

    @patch("app.routers.terminal._current_process", return_value="codex")
    @patch("app.routers.terminal._start_standby_session", return_value=False)
    @patch("app.routers.terminal._stop_standby_session", return_value=True)
    def test_finalize_auto_stops_only_run_and_confirms_standby(
        self, stop_session, start_standby, _current_process,
    ):
        result = finalize_auto_runtime("codex", "run-1")
        stop_session.assert_called_once_with("auto-codex-run-1")
        start_standby.assert_called_once_with("codex", "codex")
        self.assertEqual(result["standby_process"], "codex")




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

    @patch("app.routers.terminal.read_transcript", return_value=("linha limpa", 123.0))
    async def test_transcript_endpoint_returns_clean_persistent_text(self, read):
        result = await agent_transcript("codex")
        read.assert_called_once_with("codex")
        self.assertEqual(result["content"], "linha limpa")
        self.assertEqual(result["lines"], 1)

    async def test_transcript_endpoint_rejects_unknown_agent(self):
        with self.assertRaises(HTTPException) as ctx:
            await agent_transcript("desconhecido")
        self.assertEqual(ctx.exception.status_code, 404)


class StandbySessionTest(unittest.IsolatedAsyncioTestCase):
    @patch("app.routers.terminal._current_process", return_value="qwen")
    @patch("app.routers.terminal.subprocess.run")
    def test_start_is_idempotent_when_agent_is_running(self, run, _current):
        self.assertFalse(_start_standby_session("qwen", "qwen"))
        run.assert_not_called()

    @patch("app.routers.terminal._current_process", return_value="")
    @patch("app.routers.terminal.subprocess.run")
    def test_start_uses_the_approved_launcher(self, run, _current):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        self.assertTrue(_start_standby_session("kimi", "kimi"))
        self.assertEqual(run.call_args.args[0], [
            "tmux", "new-session", "-d", "-s", "kimi", "-c", "/opt/workdev",
            "/opt/workdev/scripts/start_kimi_agent.sh",
        ])

    @patch("app.routers.terminal.subprocess.run")
    def test_stop_is_idempotent_when_session_is_absent(self, run):
        run.return_value.returncode = 1
        run.return_value.stderr = "can't find session: kimi"
        self.assertFalse(_stop_standby_session("kimi"))

    @patch("app.routers.terminal._stop_standby_session", return_value=True)
    async def test_codex_can_be_stopped_as_standby(self, stop):
        result = await stop_agent_session("codex")
        stop.assert_called_once_with("codex")
        self.assertEqual(
            result,
            {"agent": "codex", "running": False, "stopped": True},
        )

    @patch("app.routers.terminal._start_standby_session", return_value=True)
    async def test_start_endpoint_reconnects_standby_agent(self, start):
        result = await start_agent_session("qwen")
        start.assert_called_once_with("qwen", "qwen")
        self.assertEqual(result, {"agent": "qwen", "running": True, "started": True})

    @patch("app.routers.terminal._stop_standby_session", return_value=True)
    async def test_stop_endpoint_disconnects_standby_agent(self, stop):
        result = await stop_agent_session("kimi")
        stop.assert_called_once_with("kimi")
        self.assertEqual(result, {"agent": "kimi", "running": False, "stopped": True})


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
        self.assertEqual(result["health"], "offline")
        self.assertFalse(result["awaiting_approval"])
        awaiting.assert_not_called()

    @patch("app.routers.terminal._awaiting_approval")
    @patch("app.routers.terminal._current_process")
    async def test_checks_approval_only_when_agent_process_is_running(self, current_process, awaiting):
        current_process.return_value = "claude"
        awaiting.return_value = True
        result = await _agent_status("claude", "code")
        self.assertTrue(result["running"])
        self.assertEqual(result["health"], "idle")
        self.assertTrue(result["awaiting_approval"])
        awaiting.assert_called_once_with("code")

    @patch("app.routers.terminal._agent_status")
    async def test_status_endpoint_reports_all_four_agents(self, mock_status):
        mock_status.side_effect = lambda agent, session, supervisor=None: {
            "agent": agent, "running": False, "process": "", "awaiting_approval": False,
            "health": "offline", "health_reason": None, "checked_at": None, "recovered": False,
        }
        result = await agents_status()
        self.assertEqual({item["agent"] for item in result["agents"]}, set(ALLOWED_SESSIONS))

    @patch("app.routers.terminal._awaiting_approval", return_value=False)
    @patch("app.routers.terminal._current_process", return_value="kimi-code")
    async def test_exposes_blocked_supervisor_state(self, _current, _awaiting):
        result = await _agent_status(
            "kimi", "kimi", {"status": "blocked", "reason": "billing", "checked_at": "now"}
        )
        self.assertEqual(result["health"], "blocked")
        self.assertEqual(result["health_reason"], "billing")


class SupervisorHealthStateTest(unittest.TestCase):
    def test_loads_recent_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps({
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "agents": {"kimi": {"status": "idle"}},
            }))
            with patch("app.routers.terminal._HEALTH_STATE_FILE", path):
                self.assertEqual(_load_supervisor_health()["kimi"]["status"], "idle")

    def test_ignores_stale_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps({
                "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "agents": {"kimi": {"status": "idle"}},
            }))
            with patch("app.routers.terminal._HEALTH_STATE_FILE", path):
                self.assertEqual(_load_supervisor_health(), {})


if __name__ == "__main__":
    unittest.main()
