from pathlib import Path

def test_update_contract_v6():
    u=Path('xfi_guard/updater.py').read_text(); i=Path('install.sh').read_text()
    assert 'def notify(' in u
    assert 'preserve_file /etc/xfi-guard/bot.env' in i
