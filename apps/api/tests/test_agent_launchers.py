from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / "scripts"


def launcher(name: str) -> str:
    return (SCRIPTS / f"start_{name}_agent.sh").read_text(encoding="utf-8")


def test_bootstrap_starts_all_five_agents_and_uses_exact_tmux_targets():
    content = (SCRIPTS / "bootstrap_agents.sh").read_text(encoding="utf-8")

    assert "for session in code codex kimi qwen gemini" in content
    assert 'tmux has-session -t "=$session"' in content
    assert "--no-restart" not in content


def test_launchers_disable_update_checks():
    assert "DISABLE_AUTOUPDATER=1" in launcher("claude")
    assert "--disable in_app_updates" in launcher("codex")
    assert "check_for_update_on_startup=false" in launcher("codex")
    assert 'KIMI_CODE_NO_AUTO_UPDATE="1"' in launcher("kimi")
    assert 'QWEN_CODE_SKIP_UPDATE_CHECK_ONCE="true"' in launcher("qwen")
    assert "GEMINI_CLI_SYSTEM_SETTINGS_PATH" in launcher("gemini")


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
