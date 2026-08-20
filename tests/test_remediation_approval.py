import pytest

from xfi_guard.remediation import xui_plan
from xfi_guard.remediation_approval import issue_approval, verify_approval, plan_fingerprint


def test_approval_is_bound_to_exact_plan(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_APPROVAL_SECRET", "test-secret")
    plan = xui_plan("restart", "x-ui", "service unhealthy")
    token = issue_approval(plan, admin_id=123, ttl=60)
    assert verify_approval(plan, token, admin_id=123)
    changed = xui_plan("restart", "x-ui", "different reason")
    assert plan_fingerprint(plan) != plan_fingerprint(changed)
    assert not verify_approval(changed, token, admin_id=123)


def test_approval_is_bound_to_admin(monkeypatch):
    monkeypatch.setenv("XFI_GUARD_APPROVAL_SECRET", "test-secret")
    plan = xui_plan("restart", "x-ui", "service unhealthy")
    token = issue_approval(plan, admin_id=123, ttl=60)
    assert not verify_approval(plan, token, admin_id=456)


def test_missing_secret_is_fail_closed(monkeypatch):
    monkeypatch.delenv("XFI_GUARD_APPROVAL_SECRET", raising=False)
    plan = xui_plan("restart", "x-ui", "service unhealthy")
    with pytest.raises(RuntimeError):
        issue_approval(plan, admin_id=123)
