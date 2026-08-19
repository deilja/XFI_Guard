"""AI remediation planner: recommendations only, never executes changes."""
from __future__ import annotations

from typing import Any

from .remediation import RemediationPlan, ChangeRisk, safety_policy


def build_ai_remediation(analysis: dict[str, Any] | None = None, *, target: str = "system") -> RemediationPlan:
    """Convert an AI finding into a safe, inspectable remediation plan.

    The returned plan is never executed automatically.  Destructive actions
    are deliberately downgraded to an explicit confirmation workflow.
    """
    analysis = analysis or {}
    recommendation = str(analysis.get("recommendation") or analysis.get("action") or "inspect")
    reason = str(analysis.get("reason") or analysis.get("summary") or "AI security analysis")
    risk_name = str(analysis.get("risk") or analysis.get("threat_level") or "low").lower()
    risk = {
        "safe": ChangeRisk.SAFE,
        "low": ChangeRisk.LOW,
        "medium": ChangeRisk.MEDIUM,
        "high": ChangeRisk.HIGH,
        "critical": ChangeRisk.HIGH,
    }.get(risk_name, ChangeRisk.MEDIUM)
    if recommendation.lower() in {"delete", "remove", "uninstall", "drop", "reset"}:
        risk = ChangeRisk.DESTRUCTIVE
    return RemediationPlan(
        action=recommendation,
        target=target,
        reason=reason,
        risk=risk,
        metadata={"policy": safety_policy(), "ai_generated": True},
    )
