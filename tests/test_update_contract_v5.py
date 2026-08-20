from pathlib import Path

def test_update_contract_v5():
    u=Path('xfi_guard/updater.py').read_text(); i=Path('install.sh').read_text()
    assert 'XFI_GUARD_BOT_TOKEN' in u and 'XFI_GUARD_ADMIN_IDS' in u
    assert 'XFI Guard обновлён' in u and 'Обновление XFI Guard не удалось' in u
    assert 'preserve_file /etc/xfi-guard/bot.env' in i and 'restore_file /etc/xfi-guard/bot.env' in i
    assert 'preserve_file /var/lib/xfi-guard/ai.json' in i and 'restore_file /var/lib/xfi-guard/ai.json' in i
