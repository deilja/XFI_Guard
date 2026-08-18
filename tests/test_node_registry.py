from datetime import datetime, timedelta, timezone

import pytest

from xfi_guard.node_registry import NodeRegistry, NodeStatus


def test_node_requires_approval_before_authentication():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    registry = NodeRegistry()
    node = registry.register("entry-01", "ENTRY", "AA:BB", ttl_days=90, now=now)
    assert node.status is NodeStatus.PENDING
    with pytest.raises(PermissionError):
        registry.authorize("entry-01", "aa:bb", now)

    registry.approve("entry-01")
    assert registry.authorize("entry-01", "aa:bb", now).status is NodeStatus.ACTIVE


def test_revoked_certificate_is_denied():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    registry = NodeRegistry()
    registry.register("exit-01", "EXIT", "AA:11", now=now)
    registry.approve("exit-01")
    registry.revoke("exit-01")
    with pytest.raises(PermissionError):
        registry.authorize("exit-01", "aa:11", now)


def test_expired_certificate_is_denied():
    issued = datetime(2026, 8, 18, tzinfo=timezone.utc)
    later = issued + timedelta(days=91)
    registry = NodeRegistry()
    registry.register("master", "MASTER", "FF:00", ttl_days=90, now=issued)
    registry.approve("master")
    assert registry.expire(later)[0].status is NodeStatus.EXPIRED
    with pytest.raises(PermissionError):
        registry.authorize("master", "ff:00", later)
