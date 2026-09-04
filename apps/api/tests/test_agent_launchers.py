from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / "scripts"


def launcher(name: str) -> str:
    return (SCRIPTS / f"start_{name}_agent.sh").read_text(encoding="utf-8")


def test_bootstrap_starts_all_five_agents_and_uses_exact_tmux_targets():
    content = (SCRIPTS / "bootstrap_agents.sh").read_text(encoding="utf-8")

    assert "for session in code codex kimi qwen gemini" in content
    assert 'tmux has-session -t "=$session"' in content
    assert "tmux set-option -g extended-keys on" in content
    assert "tmux set-option -g history-limit 100000" in content
    assert "alternate-screen" in content
    assert "set-option -gw alternate-screen off" not in content
    assert "--no-restart" not in content


def test_launchers_disable_update_checks():
    assert "DISABLE_AUTOUPDATER=1" in launcher("claude")
    assert "--disable in_app_updates" in launcher("codex")
    assert "check_for_update_on_startup=false" in launcher("codex")
    assert 'KIMI_CODE_NO_AUTO_UPDATE="1"' in launcher("kimi")
    assert 'QWEN_CODE_SKIP_UPDATE_CHECK_ONCE="true"' in launcher("qwen")
    assert "GEMINI_CLI_SYSTEM_SETTINGS_PATH" in launcher("gemini")


def test_all_launchers_honor_task_worktree_cwd():
    expected = 'cd "${WORKDEV_AGENT_CWD:-${WORKDEV_DIR:-/opt/workdev}}"'

    for agent in ("claude", "codex", "kimi", "qwen", "gemini"):
        content = launcher(agent)
        assert expected in content
        assert "cd /opt/workdev" not in content


def test_claude_launcher_enters_configured_task_worktree(tmp_path):
    executable = tmp_path / "print-cwd"
    executable.write_text("#!/usr/bin/env sh\npwd\n", encoding="utf-8")
    executable.chmod(0o755)
    worktree = tmp_path / "task-worktree"
    worktree.mkdir()
    env = {
        **os.environ,
        "CLAUDE_EXECUTABLE": str(executable),
        "WORKDEV_AGENT_CWD": str(worktree),
    }

    result = subprocess.run(
        [str(SCRIPTS / "start_claude_agent.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(worktree)


def test_qwen_has_noninteractive_provider_default_and_no_read_prompt():
    content = launcher("qwen")

    assert 'QWEN_PROVIDER="${QWEN_PROVIDER:-openrouter}"' in content
    assert "read -r -p" not in content


def test_kimi_disables_update_and_telemetry_before_exec():
    content = launcher("kimi")

    assert content.index("KIMI_DISABLE_TELEMETRY") < content.index('exec "$KIMI_EXECUTABLE"')
    assert content.index("KIMI_CODE_NO_AUTO_UPDATE") < content.index('exec "$KIMI_EXECUTABLE"')


def test_gemini_system_settings_disable_update_and_notification():
    settings = (SCRIPTS / "gemini-agent-settings.json").read_text(encoding="utf-8")

    assert '"enableAutoUpdate": false' in settings
    assert '"enableAutoUpdateNotification": false' in settings
