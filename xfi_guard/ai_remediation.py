"""Read-only AI remediation planning.

The AI layer can suggest a structured plan, but it cannot approve or execute it.
"""
from __future__ import annotations

from typing import Any

from .remediation import xui_plan


def build_ai_remediation(
    *,
    action: str,
    target: str,
    reason: str,
    affected_clients: int = 0,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = xui_plan(
        action,
        target,
        reason,
        affected_clients=affected_clients,
    )
    return {
        "mode": "proposal",
        "executable": False,
        "approved": False,
        "plan": plan,
        "risk": plan.risk.value,
        "evidence": dict(evidence or {}),
        "requires_confirmation": plan.risk.value == "destructive",
    }
