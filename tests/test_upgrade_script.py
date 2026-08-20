from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "upgrade.sh"


def test_upgrade_preserves_sensitive_configuration():
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"$CONFIG_DIR/bot.env"' in text
    assert '"$STATE_DIR/ai.json"' in text
    assert '"$INSTALL_DIR/.env"' in text
    assert '"$INSTALL_DIR/.env.local"' in text
    assert 'trap ' in text
    assert 'restore_all' in text


def test_upgrade_never_prints_secret_values():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'cat "$file"' not in text
    assert 'printf "%s" "$' not in text
    assert 'XFI_GUARD_BOT_TOKEN' in text
    assert 'GEMINI_API_KEY' in text
    assert 'GROQ_API_KEY' in text
    assert 'OPENROUTER_API_KEY' in text
