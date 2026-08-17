"""Tests for VPN checks."""

from unittest.mock import patch

from xfi_guard.vpn import check_listening_ports, check_service_candidates


def test_vpn_service_active():
    with patch("xfi_guard.vpn._run", return_value=(0, "active", "")):
        assert check_service_candidates(("xray",))[0].status == "ok"


def test_listening_ports_detects_443():
    output = "State Recv-Q Send-Q Local Address:Port Peer Address:Port Process\nLISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(('xray',pid=1,fd=3))"
    with patch("xfi_guard.vpn._run", return_value=(0, output, "")):
        result = check_listening_ports((443,))
    assert result.details["listeners"][0]["port"] == 443
