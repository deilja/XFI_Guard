"""Safety policy for reversible XFI Guard remediations.

The guard deliberately separates diagnosis from mutation. Destructive operations
involving live 3x-ui clients are never auto-approved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class ChangeRisk(str, Enum):
    SAFE = "safe"
    REVERSIBLE = "reversible"
    DANGEROUS = "dangerous"
    DESTRUCTIVE = "destructive"


PROTECTED_TARGETS = {
    "3x-ui.inbound",
    "3x-ui.client",
    "3x-ui.subscription",
    "3x-ui.node",
    "xray.reality_credentials",
    "wireguard.peer",
    "amneziawg.peer",
}


@dataclass(frozen=True)
class ChangePlan:
    action: str
    target: str
    risk: ChangeRisk
    reason: str
    before: str = ""
    after: str = ""
    rollback: str = ""
    affected_clients: int = 0
    requires_confirmation: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def protected(self) -> bool:
        return self.target in PROTECTED_TARGETS

    def can_apply(self, confirmed: bool = False) -> bool:
        if self.risk in {ChangeRisk.DANGEROUS, ChangeRisk.DESTRUCTIVE}:
            return bool(confirmed)
        if self.protected:
            return bool(confirmed)
        return True


def build_plan(*, action: str, target: str, reason: str,
               risk: ChangeRisk = ChangeRisk.REVERSIBLE,
               before: str = "", after: str = "", rollback: str = "",
               affected_clients: int = 0, metadata: dict | None = None) -> ChangePlan:
    return ChangePlan(
        action=action,
        target=target,
        risk=risk,
        reason=reason,
        before=before,
        after=after,
        rollback=rollback,
        affected_clients=max(0, int(affected_clients)),
        requires_confirmation=(risk != ChangeRisk.SAFE or target in PROTECTED_TARGETS),
        metadata=metadata or {},
    )


def validate_plan(plan: ChangePlan, confirmed: bool = False) -> None:
    """Raise before an unsafe mutation is executed."""
    if plan.protected and plan.action.lower() in {"delete", "remove", "recreate", "reset"} and not confirmed:
        raise PermissionError("protected 3x-ui/live-client object requires explicit confirmation")
    if not plan.can_apply(confirmed):
        raise PermissionError(f"change requires explicit confirmation: {plan.action} {plan.target}")


def is_protected_target(target: str) -> bool:
    return target in PROTECTED_TARGETS


def protected_targets() -> Iterable[str]:
    return tuple(sorted(PROTECTED_TARGETS))
