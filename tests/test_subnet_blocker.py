from unittest.mock import patch

import pytest

from xfi_guard import subnet_blocker


def test_validate_public_subnet_canonicalizes_host_bits():
    assert subnet_blocker.validate_public_subnet("8.8.8.7/24") == "8.8.8.0/24"


def test_validate_public_subnet_rejects_broad_network():
    with pytest.raises(ValueError, match="Слишком широкая"):
        subnet_blocker.validate_public_subnet("8.8.0.0/16")


def test_validate_public_subnet_rejects_private_network():
    with pytest.raises(ValueError):
        subnet_blocker.validate_public_subnet("192.168.1.0/24")


def test_validate_public_subnet_rejects_ipv6():
    with pytest.raises(ValueError):
        subnet_blocker.validate_public_subnet("2001:db8::/64")


def test_block_subnet_uses_ufw():
    with patch("xfi_guard.subnet_blocker._run", return_value=(0, "Rule added", "")) as run:
        ok, message = subnet_blocker.block_subnet("8.8.8.0/24")
    assert ok is True
    assert "8.8.8.0/24" in message
    run.assert_called_once_with(["ufw", "insert", "1", "deny", "from", "8.8.8.0/24"])


def test_unblock_subnet_uses_ufw():
    with patch("xfi_guard.subnet_blocker._run", return_value=(0, "Rule deleted", "") ) as run:
        ok, message = subnet_blocker.unblock_subnet("8.8.8.0/24")
    assert ok is True
    assert "8.8.8.0/24" in message
    run.assert_called_once_with(["ufw", "delete", "deny", "from", "8.8.8.0/24"])


def test_list_blocked_subnets_parses_cidr():
    output = "-A ufw-user-input -s 8.8.8.0/24 -j DROP\nRule added deny from 1.1.1.0/24\n"
    with patch("xfi_guard.subnet_blocker._run", return_value=(0, output, "")):
        # Only the UFW persistent form with `from CIDR` is intentionally parsed.
        assert subnet_blocker.list_blocked_subnets() == ["1.1.1.0/24"]
