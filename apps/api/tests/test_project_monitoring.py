import subprocess
import unittest
from unittest.mock import patch, MagicMock

from app.routers import monitoring


class ProcMetricsTest(unittest.TestCase):
    def test_returns_empty_dict_for_pid_zero(self):
        self.assertEqual(monitoring._proc_metrics(0), {})

    @patch("app.routers.monitoring._run")
    def test_parses_ps_output(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="%CPU %MEM ELAPSED\n 1.5  2.3 01:02:03\n"
        )
        result = monitoring._proc_metrics(1234)
        self.assertEqual(result["cpu_percent"], 1.5)
        self.assertEqual(result["mem_percent"], 2.3)
        self.assertEqual(result["uptime"], "01:02:03")


class StatusBySlugTest(unittest.TestCase):
    def test_unknown_slug_reports_not_monitored(self):
        result = monitoring.status_by_slug("nutrigestor-crm")
        self.assertFalse(result["monitored"])
        self.assertIn("reason", result)

    @patch("app.routers.monitoring._local_systemd_metrics")
    def test_workdev_core_uses_local_systemd_metrics(self, mock_metrics):
        mock_metrics.return_value = {
            "active_state": "active", "sub_state": "running",
            "cpu_percent": 0.5, "mem_percent": 1.2, "uptime": "02:00", "logs": ["ok"],
        }
        result = monitoring.status_by_slug("workdev-core")
        mock_metrics.assert_called_once_with("workdev-api")
        self.assertTrue(result["monitored"])
        self.assertEqual(result["service"], "workdev-api")
        self.assertEqual(result["cpu_percent"], 0.5)

    @patch("app.routers.monitoring._vps2_systemd_metrics")
    def test_agente_pessoal_uses_vps2_systemd_metrics(self, mock_metrics):
        mock_metrics.return_value = {"active_state": "active", "logs": []}
        result = monitoring.status_by_slug("agente-pessoal")
        mock_metrics.assert_called_once_with("agente-api.service")
        self.assertTrue(result["monitored"])

    @patch("app.routers.monitoring._vps2_process_metrics")
    def test_openclaw_uses_vps2_process_metrics(self, mock_metrics):
        mock_metrics.return_value = {"active_state": "active", "logs": []}
        result = monitoring.status_by_slug("openclaw")
        mock_metrics.assert_called_once()
        self.assertTrue(result["monitored"])


class Vps2ProcessMetricsTest(unittest.TestCase):
    @patch("app.routers.monitoring._vps2_ssh")
    def test_no_pid_reports_inactive(self, mock_ssh):
        mock_ssh.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="NOPID\n"
        )
        result = monitoring._vps2_process_metrics("pattern")
        self.assertEqual(result["active_state"], "inactive")

    @patch("app.routers.monitoring._vps2_ssh")
    def test_ssh_unavailable_reports_error(self, mock_ssh):
        mock_ssh.return_value = None
        result = monitoring._vps2_process_metrics("pattern")
        self.assertIn("error", result)




class JevMcpMonitorTest(unittest.TestCase):
    """Monitor de conectividade MCP/Jev (achado 26/set/2026): link
    Tailscale VPS1<->VPS2 + alcance HTTP do MCP na porta 8891."""

    @staticmethod
    def _run_side_effect(tailscale_stdout, tailscale_returncode, curl_stdout, curl_returncode, curl_stderr=""):
        def _fake_run(command, timeout=6):
            if command[0] == "tailscale":
                return subprocess.CompletedProcess(
                    args=command, returncode=tailscale_returncode, stdout=tailscale_stdout, stderr="",
                )
            return subprocess.CompletedProcess(
                args=command, returncode=curl_returncode, stdout=curl_stdout, stderr=curl_stderr,
            )
        return _fake_run

    @patch("app.routers.monitoring._run")
    def test_online_when_peer_online_and_http_reachable(self, mock_run):
        tailscale_json = (
            '{"Peer": {"x": {"HostName": "srv1750921", "Online": true}}}'
        )
        mock_run.side_effect = self._run_side_effect(tailscale_json, 0, "404", 0)
        tailscale_service, jev_service = monitoring._check_jev_mcp()
        self.assertEqual(tailscale_service["status"], "online")
        self.assertIn("srv1750921", tailscale_service["detail"])
        self.assertEqual(jev_service["status"], "online")
        self.assertIn("404", jev_service["detail"])

    @patch("app.routers.monitoring._run")
    def test_offline_when_peer_reported_offline(self, mock_run):
        tailscale_json = (
            '{"Peer": {"x": {"HostName": "srv1750921", "Online": false}}}'
        )
        mock_run.side_effect = self._run_side_effect(tailscale_json, 0, "404", 0)
        tailscale_service, _jev_service = monitoring._check_jev_mcp()
        self.assertEqual(tailscale_service["status"], "offline")

    @patch("app.routers.monitoring._run")
    def test_offline_when_peer_missing_from_status(self, mock_run):
        tailscale_json = '{"Peer": {}}'
        mock_run.side_effect = self._run_side_effect(tailscale_json, 0, "404", 0)
        tailscale_service, _jev_service = monitoring._check_jev_mcp()
        self.assertEqual(tailscale_service["status"], "offline")
        self.assertIn("nao encontrado", tailscale_service["detail"])

    @patch("app.routers.monitoring._run")
    def test_jev_mcp_unreachable_when_curl_fails(self, mock_run):
        tailscale_json = (
            '{"Peer": {"x": {"HostName": "srv1750921", "Online": true}}}'
        )
        mock_run.side_effect = self._run_side_effect(
            tailscale_json, 0, "", 7, curl_stderr="Connection refused",
        )
        _tailscale_service, jev_service = monitoring._check_jev_mcp()
        self.assertEqual(jev_service["status"], "offline")
        self.assertIn("Connection refused", jev_service["detail"])

    @patch("app.routers.monitoring._run", side_effect=OSError("boom"))
    def test_tailscale_check_survives_os_error(self, _mock_run):
        tailscale_service, jev_service = monitoring._check_jev_mcp()
        self.assertEqual(tailscale_service["status"], "offline")
        self.assertEqual(jev_service["status"], "offline")


if __name__ == "__main__":
    unittest.main()
