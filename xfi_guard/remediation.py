"""Instruction-driven remediation planner.

This module translates the deployment/rollback policy into safe, inspectable
plans. It intentionally does not mutate 3x-ui clients, inbounds or nodes.
"""
from __future__ import annotations

from dataclasses import asdict
from .safety.change_guard import ChangeRisk, ChangePlan, build_plan, validate_plan


def network_plan(reason: str, *, before: str = "", after: str = "") -> ChangePlan:
    return build_plan(
        action="apply-network-change",
        target="network.policy-routing",
        risk=ChangeRisk.DANGEROUS,
        reason=reason,
        before=before,
        after=after,
        rollback="/root/rollback_net.sh or XFI Guard rollback backup",
    )


def firewall_plan(reason: str, *, before: str = "", after: str = "") -> ChangePlan:
    return build_plan(
        action="apply-firewall-change",
        target="firewall",
        risk=ChangeRisk.DANGEROUS,
        reason=reason,
        before=before,
        after=after,
        rollback="restore nftables/iptables backup",
    )


def xui_plan(action: str, target: str, reason: str, *, before: str = "", after: str = "", affected_clients: int = 0) -> ChangePlan:
    """Build a plan for 3x-ui without silently deleting live client state."""
    destructive = action.lower() in {"delete", "remove", "recreate", "reset", "uninstall"}
    return build_plan(
        action=action,
        target=target,
        risk=ChangeRisk.DESTRUCTIVE if destructive else ChangeRisk.REVERSIBLE,
        reason=reason,
        before=before,
        after=after,
        rollback="restore the pre-change x-ui/database backup",
        affected_clients=affected_clients,
    )


def approve(plan: ChangePlan, *, confirmed: bool = False) -> dict:
    """Validate explicit approval and return a serializable execution record."""
    validate_plan(plan, confirmed=confirmed)
    return asdict(plan) | {"approved": True}


def safety_policy() -> dict:
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
