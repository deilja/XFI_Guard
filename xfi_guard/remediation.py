"""Safe, explicit remediation planning for XFI Guard.

Destructive 3X-UI changes always require an explicit confirmation.  This
module is intentionally small so the safety contract is easy to audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeRisk(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class RemediationPlan:
    action: str
    target: str
    reason: str
    risk: ChangeRisk
    affected_clients: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def xui_plan(action: str, target: str, reason: str, *, affected_clients: int = 0) -> RemediationPlan:
    """Build a conservative 3X-UI remediation plan.

    Deleting an inbound or a live client is destructive by definition.
    """
    destructive_actions = {"delete", "remove", "uninstall", "drop", "reset"}
    risk = ChangeRisk.DESTRUCTIVE if action.lower() in destructive_actions else ChangeRisk.MEDIUM
    return RemediationPlan(
        action=action,
        target=target,
        reason=reason,
        risk=risk,
        affected_clients=max(0, int(affected_clients)),
    )


def build_plan(*, action: str, target: str, reason: str, risk: ChangeRisk, affected_clients: int = 0, **metadata: Any) -> RemediationPlan:
    return RemediationPlan(action, target, reason, risk, max(0, int(affected_clients)), metadata)


def approve(plan: RemediationPlan, *, confirmed: bool = False) -> dict[str, Any]:
    """Approve a plan without executing it."""
    if plan.risk is ChangeRisk.DESTRUCTIVE and not confirmed:
        raise PermissionError("Destructive remediation requires explicit confirmation")
    return {
        "approved": True,
        "action": plan.action,
        "target": plan.target,
        "risk": plan.risk.value,
        "confirmed": bool(confirmed),
    }


def safety_policy() -> dict[str, bool]:
    return {
        "auto_delete_live_clients": False,
        "auto_delete_inbounds": False,
        "auto_uninstall_xui": False,
        "network_rollback_required": True,
        "postgres_drop_requires_confirmation": True,
    }
