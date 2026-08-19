import pytest
from pydantic import ValidationError

from xfi_guard.config import load_config


def test_load_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[monitor]\ninterval_seconds = 5\n'
        '[thresholds]\ndisk_warning_percent = 80\n'
        '[vpn]\nservices = ["xray"]\nports = [443]\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.interval_seconds == 5
    assert config.disk_warning_percent == 80
    assert config.vpn_services == ("xray",)
    assert config.vpn_ports == (443,)


def test_invalid_monitor_config_is_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[monitor]\ninterval_seconds = 2\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)
