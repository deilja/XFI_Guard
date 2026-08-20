from pathlib import Path


def test_updater_has_telegram_notifications_and_status():
    source = Path("xfi_guard/updater.py").read_text(encoding="utf-8")
    assert "def notify(" in source
    assert "XFI_GUARD_BOT_TOKEN" in source
    assert "XFI_GUARD_ADMIN_IDS" in source
    assert "api.telegram.org" in source
    assert "✅ XFI Guard обновлён" in source
    assert "❌ Обновление XFI Guard не удалось" in source


def test_force_update_uses_same_notification_path():
    source = Path("xfi_guard/force_update.py").read_text(encoding="utf-8")
    assert "updater.notify(" in source
    assert "Принудительное обновление XFI Guard завершено" in source
    assert "Автоматический откат" in source


def test_installer_preserves_existing_config_before_reset():
    source = Path("install.sh").read_text(encoding="utf-8")
    preserve = source.index("# Preserve secrets before any git reset")
    reset = source.index('git -C "$INSTALL_DIR" reset --hard origin/main')
    assert preserve < reset
    assert "preserve_file /etc/xfi-guard/bot.env" in source
    assert "preserve_file /var/lib/xfi-guard/ai.json" in source
    assert "restore_file /etc/xfi-guard/bot.env" in source
    assert "restore_file /var/lib/xfi-guard/ai.json" in source
