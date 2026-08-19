import pytest

from xfi_guard.remediation import network_plan, xui_plan
from xfi_guard.remediation_executor import RemediationExecutionError, execute_plan


def test_dangerous_network_change_stays_manual():
    plan = network_plan("routing issue")
    result = execute_plan(plan, confirmed=True)
    assert result["status"] == "manual_required"


def test_destructive_xui_change_stays_manual():
    plan = xui_plan("delete", "3x-ui.inbound", "bad inbound", affected_clients=2)
    result = execute_plan(plan, confirmed=True)
    assert result["status"] == "manual_required"


def test_restart_requires_explicit_confirmation():
    plan = xui_plan("restart", "x-ui", "service unhealthy")
    with pytest.raises(PermissionError):
        execute_plan(plan, confirmed=False)


def test_restart_rejects_unapproved_target():
    plan = xui_plan("restart", "arbitrary-command", "test")
    with pytest.raises(RemediationExecutionError):
        execute_plan(plan, confirmed=True)


def test_inspect_is_read_only():
    plan = xui_plan("inspect", "xray.logs", "diagnostics")
    result = execute_plan(plan)
    assert result["status"] == "executed"
    assert result["output"] == "plan inspection only"
