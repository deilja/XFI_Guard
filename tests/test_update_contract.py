from pathlib import Path


def test_update_contract():
    updater = Path("xfi_guard/updater.py").read_text(encoding="utf-8")
    installer = Path("install.sh").read_text(encoding="utf-8")
    assert "XFI_GUARD_BOT_TOKEN" in updater
    assert "XFI_GUARD_ADMIN_IDS" in updater
    assert "XFI Guard обновлён" in updater
    assert "Обновление XFI Guard не удалось" in updater
    assert "preserve_file /etc/xfi-guard/bot.env" in installer
    assert "restore_file /etc/xfi-guard/bot.env" in installer
    assert "preserve_file /var/lib/xfi-guard/ai.json" in installer
    assert "restore_file /var/lib/xfi-guard/ai.json" in installer
