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


if __name__ == "__main__":
    unittest.main()
