import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


DEPLOY_DIR = Path(__file__).parents[3] / "scripts/deploy"
sys.path.insert(0, str(DEPLOY_DIR))
MODULE = DEPLOY_DIR / "deploy_broker.py"
spec = importlib.util.spec_from_file_location("deploy_broker", MODULE)
broker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["deploy_broker"] = broker
spec.loader.exec_module(broker)


def test_broker_recusa_usuario_incorreto(monkeypatch):
    monkeypatch.delenv("WORKDEV_DEPLOY_TESTING", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 12345)
    fake_pwd = SimpleNamespace(pw_name="workdev")
    monkeypatch.setattr("pwd.getpwuid", lambda _: fake_pwd)

    with pytest.raises(broker.PipelineError, match="workdev-deploy"):
        broker.require_broker_user()


def test_broker_usa_sudo_nao_interativo_para_restart(monkeypatch):
    called = Mock()
    monkeypatch.setattr(broker, "run", called)

    broker.privileged(["systemctl", "restart", "workdev-api.service"])

    called.assert_called_once_with(
        ["sudo", "-n", "systemctl", "restart", "workdev-api.service"]
    )


def test_prepare_executa_gate_imutavel_com_privilegio_minimo(monkeypatch):
    called = Mock(side_effect=RuntimeError("gate executado"))
    monkeypatch.setattr(broker, "run", called)
    args = SimpleNamespace()

    with pytest.raises(RuntimeError, match="gate executado"):
        broker.prepare(args, b"k" * 32)

    called.assert_called_once_with(
        ["sudo", "-n", "/usr/local/libexec/workdev-predeploy-gate"]
    )


def test_release_manager_exige_grupo_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(broker.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=4567))
    monkeypatch.setattr(os, "getgroups", lambda: [1234])

    with pytest.raises(broker.PipelineError, match="nao pertence"):
        broker.release_manager(tmp_path)


def test_release_manager_recebe_gid_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(broker.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=4567))
    monkeypatch.setattr(os, "getgroups", lambda: [4567])

    manager = broker.release_manager(tmp_path)

    assert manager.runtime_gid == 4567


@pytest.mark.parametrize(
    ("program", "operation"), [("ss", "port"), ("journalctl", "journal")]
)
def test_pos_gate_privilegia_somente_leituras_necessarias(
    monkeypatch, program, operation
):
    called = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(broker, "system_command", called, raising=False)
    monkeypatch.setattr("post_deploy_gate.system_command", called)

    broker.post_deploy_command([program, "argumento"])

    called.assert_called_once_with([
        "sudo", "-n", "/usr/local/libexec/workdev-deploy-readcheck", operation
    ])


def test_pos_gate_nao_eleva_comando_arbitrario(monkeypatch):
    called = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("post_deploy_gate.system_command", called)

    broker.post_deploy_command(["pgrep", "uvicorn"])

    called.assert_called_once_with(["pgrep", "uvicorn"])
