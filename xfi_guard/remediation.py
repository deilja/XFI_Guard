"""Human-gated remediation planning.

Destructive 3X-UI/Xray changes are never approved automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .safety.change_guard import ChangePlan, ChangeRisk, build_plan


_POLICY = {
    "auto_delete_live_clients": False,
    "auto_delete_inbounds": False,
    "auto_uninstall_xui": False,
    "network_rollback_required": True,
    "postgres_drop_requires_confirmation": True,
}


def safety_policy() -> dict[str, bool]:
    return dict(_POLICY)


def xui_plan(
    action: str,
    target: str,
    reason: str,
    *,
    affected_clients: int = 0,
) -> ChangePlan:
    action_l = action.strip().lower()
    target_l = target.strip().lower()

    destructive_actions = {"delete", "remove", "destroy", "uninstall", "drop"}
    destructive_target = any(
        marker in target_l
        for marker in ("inbound", "client", "database", "postgres", "x-ui", "3x-ui")
    )
    risk = (
        ChangeRisk.DESTRUCTIVE
        if action_l in destructive_actions or destructive_target and action_l in destructive_actions
        else ChangeRisk.WARNING
    )

    if action_l in {"inspect", "status", "logs", "diagnose"}:
        risk = ChangeRisk.SAFE

    return build_plan(
        action=action,
        target=target,
        reason=reason,
        risk=risk,
        affected_clients=affected_clients,
        metadata={"component": "3x-ui"},
    )


def approve(plan: ChangePlan, *, confirmed: bool = False, actor: str = "admin") -> dict[str, Any]:
    if plan.risk is ChangeRisk.DESTRUCTIVE and not confirmed:
        raise PermissionError("Destructive remediation requires explicit confirmation")

    return {
        "approved": True,
        "action": plan.action,
        "target": plan.target,
        "reason": plan.reason,
        "risk": plan.risk.value,
        "affected_clients": plan.affected_clients,
        "actor": actor,
        "confirmed": bool(confirmed),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
