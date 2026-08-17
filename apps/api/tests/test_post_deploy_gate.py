import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[3] / "scripts/deploy/post_deploy_gate.py"
DEPLOY_DIR = MODULE.parent
import sys
sys.path.insert(0, str(DEPLOY_DIR))
spec = importlib.util.spec_from_file_location("post_deploy_gate", MODULE)
post = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["post_deploy_gate"] = post
spec.loader.exec_module(post)


def command_ok(command):
    if command[:2] == ["systemctl", "show"]:
        return post.CommandResult(0, "ActiveState=active\nSubState=running\nMainPID=42\nNRestarts=0\n")
    if command[0] == "ss":
        return post.CommandResult(0, 'LISTEN users:(("uvicorn",pid=42,fd=6))')
    if command[0] == "pgrep":
        return post.CommandResult(0, "42 /venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000\n")
    return post.CommandResult(0, "startup complete")


def test_todos_checks_passam():
    result = post.run_checks(command_ok, lambda _url: 200)

    assert result["status"] == "DEPLOY_SUCCEEDED"


def test_mainpid_diferente_da_porta_falha():
    def command(args):
        result = command_ok(args)
        if args[0] == "ss":
            return post.CommandResult(0, 'LISTEN users:(("uvicorn",pid=99,fd=6))')
        return result

    assert post.run_checks(command, lambda _url: 200)["status"] == "DEPLOY_FAILED"


def test_journal_critico_degrada():
    def command(args):
        if args[0] == "journalctl":
            return post.CommandResult(0, "Traceback: boom")
        return command_ok(args)

    assert post.run_checks(command, lambda _url: 200)["status"] == "DEPLOY_DEGRADED"


def test_health_falho_e_critico():
    def http(url):
        return 500 if url.endswith("/health") else 200

    assert post.run_checks(command_ok, http)["status"] == "DEPLOY_FAILED"


def test_rota_essencial_da_api_falha_deploy():
    def http(url):
        return 500 if url.endswith("/api/projects") else 200

    assert post.run_checks(command_ok, http)["status"] == "DEPLOY_FAILED"
