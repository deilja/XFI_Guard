from pathlib import Path

def test_update_contract_v7():
    u=Path('xfi_guard/updater.py').read_text(); i=Path('install.sh').read_text()
    assert 'XFI_GUARD_BOT_TOKEN' in u
    assert 'XFI_GUARD_ADMIN_IDS' in u
    assert 'preserve_file /etc/xfi-guard/bot.env' in i
    assert 'restore_file /etc/xfi-guard/bot.env' in i
