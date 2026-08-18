"""Guarded execution boundary for AI remediation plans.

The executor intentionally supports only narrowly defined, reversible actions.
AI-generated shell commands are never executed.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict
from typing import Callable

from .remediation import approve
from .safety.change_guard import ChangePlan, ChangeRisk


class RemediationExecutionError(RuntimeError):
    pass


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


def _run_checked(command: list[str], timeout: int = 30) -> str:
    """Run a fixed command list; never accepts a shell string."""
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
    plan: ChangePlan,
    *,
    confirmed: bool = False,
    runners: dict[str, Callable[[ChangePlan], str]] | None = None,
) -> dict:
    """Execute only approved, allow-listed actions.

    Dangerous/destructive plans are never executed by this generic executor;
    they must be handled by a dedicated reviewed adapter with its own rollback.
    """
    approval = approve(plan, confirmed=confirmed)
    action = plan.action.lower()

    if action in MANUAL_ACTIONS and plan.risk in {ChangeRisk.DANGEROUS, ChangeRisk.DESTRUCTIVE}:
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
        # Only fixed service names are accepted by reviewed callers.
        target = plan.target
        allowed = {"x-ui", "xray", "nginx", "yadreno-vpn"}
        if target not in allowed:
            raise RemediationExecutionError("restart target is not allow-listed")
        output = _run_checked(["systemctl", "restart", target])
    else:
        raise RemediationExecutionError("no execution adapter")

    return {"status": "executed", "output": output, "plan": asdict(plan)}
