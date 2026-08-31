from pathlib import Path
from unittest.mock import patch

import pytest

from xfi_guard.nodes import Node, _remote_action_argv, _validate_identity, restart_guard


def test_identity_must_exist(tmp_path: Path):
    with pytest.raises(ValueError, match="not found"):
        _validate_identity(tmp_path / "missing")


def test_identity_must_not_be_group_or_world_accessible(tmp_path: Path):
    key = tmp_path / "key"
    key.write_text("placeholder", encoding="utf-8")
    key.chmod(0o644)
    with pytest.raises(ValueError, match="permissions too open"):
        _validate_identity(key)


def test_identity_secure_permissions_are_accepted(tmp_path: Path):
    key = tmp_path / "key"
    key.write_text("placeholder", encoding="utf-8")
    key.chmod(0o600)
    _validate_identity(key)


def test_remote_action_is_allowlisted():
    assert _remote_action_argv("restart_guard") == [
        "sudo", "-n", "systemctl", "restart", "xfi-guard.service"
    ]
    with pytest.raises(ValueError, match="Unsupported remote action"):
        _remote_action_argv("systemctl restart something-else")


def test_restart_guard_rejects_untrusted_action_without_ssh():
    node = Node("test", "192.0.2.10", identity_file="/tmp/key")
    with patch("xfi_guard.nodes.subprocess.run") as run:
        ok, message = restart_guard(node, action="rm -rf /")
    assert not ok
    assert "Unsupported remote action" in message
    run.assert_not_called()
