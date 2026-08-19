import pytest

from xfi_guard.remediation import approve, safety_policy, xui_plan
from xfi_guard.remediation import ChangeRisk, build_plan


def test_live_inbound_requires_confirmation():
    plan = xui_plan("delete", "3x-ui.inbound", "broken inbound", affected_clients=3)
    assert plan.risk is ChangeRisk.DESTRUCTIVE
    with pytest.raises(PermissionError):
        approve(plan)
    record = approve(plan, confirmed=True)
    assert record["approved"] is True


def test_safe_plan_can_be_approved_without_confirmation():
    plan = build_plan(
        action="inspect",
        target="xray.logs",
        reason="diagnostics",
        risk=ChangeRisk.SAFE,
    )
    assert approve(plan, confirmed=False)["approved"] is True


def test_policy_never_auto_deletes_clients():
    policy = safety_policy()
    assert policy["auto_delete_live_clients"] is False
    assert policy["auto_delete_inbounds"] is False
    assert policy["auto_uninstall_xui"] is False


def test_ai_remediation_module_exists_and_is_non_destructive():
    from xfi_guard.ai_remediation import build_ai_remediation

    assert callable(build_ai_remediation)
    policy = safety_policy()
    assert policy["network_rollback_required"] is True
    assert policy["postgres_drop_requires_confirmation"] is True
