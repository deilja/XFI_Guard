"""Guarded execution boundary for approved remediation plans.

Only narrowly allow-listed, reversible actions may execute here. AI-generated
shell commands are never executed, and dangerous/destructive changes remain
manual even after an approval record is created.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict
from typing import Callable

from .remediation import ChangeRisk, RemediationPlan, approve


class RemediationExecutionError(RuntimeError):
    """Raised when an execution request violates the safety boundary."""


SAFE_ACTIONS = {"inspect", "restart"}
MANUAL_ACTIONS = {
    "apply-network-change",
    "apply-firewall-change",
    "update-xui",
    "delete",
    "remove",
    "recreate",
    "reset",
    "uninstall",
}
ALLOWED_RESTART_TARGETS = {"x-ui", "xray", "nginx", "yadreno-vpn"}


def _run_checked(command: list[str], timeout: int = 30) -> str:
    """Run a fixed argv list without shell interpretation."""
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RemediationExecutionError(result.stderr.strip() or "command failed")
    return result.stdout.strip()


def execute_plan(
    plan: RemediationPlan,
    *,
    confirmed: bool = False,
    runners: dict[str, Callable[[RemediationPlan], str]] | None = None,
) -> dict:
    """Execute only explicitly approved and allow-listed actions."""
    action = plan.action.strip().lower()

    # Mutating service restarts require explicit confirmation even though they
    # are reversible; dangerous/destructive changes are always manual.
    if action == "restart" and not confirmed:
        raise PermissionError("Service restart requires explicit confirmation")

    approval = approve(plan, confirmed=confirmed)

    if action in MANUAL_ACTIONS:
        return {
            "status": "manual_required",
            "reason": "dangerous remediation requires a reviewed adapter and rollback gate",
            "plan": approval,
        }

    if action not in SAFE_ACTIONS:
        raise RemediationExecutionError(f"action is not allow-listed: {plan.action}")

    if runners and action in runners:
        output = runners[action](plan)
    elif action == "inspect":
        output = "plan inspection only"
    elif action == "restart":
        if plan.target not in ALLOWED_RESTART_TARGETS:
            raise RemediationExecutionError("restart target is not allow-listed")
        output = _run_checked(["systemctl", "restart", plan.target])
    else:
        raise RemediationExecutionError("no execution adapter")

    return {"status": "executed", "output": output, "plan": asdict(plan)}
