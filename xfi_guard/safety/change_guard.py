"""Safety classification and approval gates for remediation plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeRisk(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ChangePlan:
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
    risk: ChangeRisk = ChangeRisk.WARNING,
    affected_clients: int = 0,
    metadata: dict[str, Any] | None = None,
) -> ChangePlan:
    if not action or not target:
        raise ValueError("action and target are required")
    if affected_clients < 0:
        raise ValueError("affected_clients cannot be negative")
    return ChangePlan(
        action=action,
        target=target,
        reason=reason,
        risk=risk,
        affected_clients=affected_clients,
        metadata=dict(metadata or {}),
    )
