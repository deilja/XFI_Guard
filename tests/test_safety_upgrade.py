from xfi_guard.remediation import ChangeRisk, approve, build_plan
from xfi_guard.safety.change_guard import build_plan as safety_build_plan


def test_safety_wrapper_matches_remediation_contract():
    plan = safety_build_plan(
        action="inspect",
        target="xray.logs",
        reason="diagnostics",
        risk=ChangeRisk.SAFE,
    )
    assert plan.risk is ChangeRisk.SAFE
    assert plan.target == "xray.logs"


def test_destructive_plan_requires_explicit_confirmation():
    plan = build_plan(
        action="delete",
        target="3x-ui.client",
        reason="test",
        risk=ChangeRisk.DESTRUCTIVE,
    )
    try:
        approve(plan)
    except PermissionError:
        pass
    else:
        raise AssertionError("destructive plan was approved without confirmation")

    assert approve(plan, confirmed=True)["approved"] is True
