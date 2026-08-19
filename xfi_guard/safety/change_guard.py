"""Compatibility safety primitives used by remediation and tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..remediation import ChangeRisk


@dataclass(frozen=True)
class ChangePlan:
    action: str
    target: str
    reason: str
    risk: ChangeRisk
    affected_clients: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def build_plan(*, action: str, target: str, reason: str, risk: ChangeRisk = ChangeRisk.MEDIUM, affected_clients: int = 0, metadata: dict[str, Any] | None = None) -> ChangePlan:
    if not action or not target:
        raise ValueError("action and target are required")
    if affected_clients < 0:
        raise ValueError("affected_clients cannot be negative")
    return ChangePlan(action, target, reason, risk, affected_clients, dict(metadata or {}))
