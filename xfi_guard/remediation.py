"""Safe, explicit remediation planning for XFI Guard.

The planner describes changes but never executes them. Destructive and
network-sensitive operations require an explicit confirmation gate.
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
    DANGEROUS = "dangerous"
    REVERSIBLE = "reversible"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class RemediationPlan:
    action: str
    target: str
    reason: str
    risk: ChangeRisk
    affected_clients: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def build_plan(
    *,
    action: str,
    target: str,
    reason: str,
    risk: ChangeRisk,
    affected_clients: int = 0,
    **metadata: Any,
) -> RemediationPlan:
    if not action or not target:
        raise ValueError("action and target are required")
    if affected_clients < 0:
        raise ValueError("affected_clients cannot be negative")
    return RemediationPlan(
        action=action,
        target=target,
        reason=reason,
        risk=risk,
        affected_clients=affected_clients,
        metadata=dict(metadata),
    )


def network_plan(reason: str, *, before: str = "", after: str = "") -> RemediationPlan:
    """Create a network-change plan that requires rollback protection."""
    return build_plan(
        action="apply-network-change",
        target="network.policy-routing",
        risk=ChangeRisk.DANGEROUS,
        reason=reason,
        before=before,
        after=after,
        rollback="restore nftables/iptables backup",
    )


def firewall_plan(reason: str, *, before: str = "", after: str = "") -> RemediationPlan:
    """Create a firewall-change plan that requires rollback protection."""
    return build_plan(
        action="apply-firewall-change",
        target="firewall",
        risk=ChangeRisk.DANGEROUS,
        reason=reason,
        before=before,
        after=after,
        rollback="restore nftables/iptables backup",
    )


def xui_plan(
    action: str,
    target: str,
    reason: str,
    *,
    before: str = "",
    after: str = "",
    affected_clients: int = 0,
) -> RemediationPlan:
    """Build a conservative 3X-UI remediation plan."""
    action_l = action.strip().lower()
    destructive_actions = {"delete", "remove", "uninstall", "drop", "reset", "recreate"}
    if action_l in destructive_actions:
        risk = ChangeRisk.DESTRUCTIVE
    elif action_l in {"inspect", "status", "logs", "diagnose"}:
        risk = ChangeRisk.SAFE
    elif action_l in {"restart", "reload"}:
        risk = ChangeRisk.REVERSIBLE
    else:
        risk = ChangeRisk.MEDIUM

    return build_plan(
        action=action,
        target=target,
        reason=reason,
        risk=risk,
        before=before,
        after=after,
        rollback="restore the pre-change x-ui/database backup",
        affected_clients=affected_clients,
    )


def approve(plan: RemediationPlan, *, confirmed: bool = False, actor: str = "admin") -> dict[str, Any]:
    """Approve a plan without executing it."""
    if plan.risk in {ChangeRisk.DANGEROUS, ChangeRisk.DESTRUCTIVE} and not confirmed:
        raise PermissionError("Dangerous remediation requires explicit confirmation")
    return {
        "approved": True,
        "action": plan.action,
        "target": plan.target,
        "reason": plan.reason,
        "risk": plan.risk.value,
        "affected_clients": plan.affected_clients,
        "actor": actor,
        "confirmed": bool(confirmed),
    }


def safety_policy() -> dict[str, Any]:
    return {
        "mode": "detect-propose-confirm-apply-verify-rollback",
        "auto_delete_live_clients": False,
        "auto_delete_inbounds": False,
        "auto_uninstall_xui": False,
        "network_rollback_required": True,
        "postgres_drop_requires_confirmation": True,
        "protected_targets": [
            "3x-ui.inbound",
            "3x-ui.client",
            "3x-ui.subscription",
            "3x-ui.node",
            "xray.reality_credentials",
            "wireguard.peer",
            "amneziawg.peer",
        ],
    }
