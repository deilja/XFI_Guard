"""AI-to-remediation bridge with mandatory safety boundaries.

The AI may recommend a change, but it never executes destructive actions.
Execution must go through xfi_guard.remediation after explicit confirmation.
"""
from __future__ import annotations

import json
from typing import Any

from .ai import AIAnalyzer
from .remediation import firewall_plan, network_plan, xui_plan


def _prompt(event: dict[str, Any]) -> str:
    return (
        "Верни ТОЛЬКО JSON без markdown. "
        "Поля: action, target, reason, before, after, affected_clients. "
        "action должен быть одним из: inspect, restart, apply-network-change, "
        "apply-firewall-change, update-xui, delete, uninstall. "
        "Не предлагай удаление живых 3x-ui клиентов/inbounds/nodes без явной необходимости. "
        "Факты бери только из события.\n" + json.dumps(event, ensure_ascii=False)
    )


def build_ai_remediation(event: dict[str, Any]) -> dict[str, Any]:
    """Return an inspectable plan; never execute the plan."""
    ai = AIAnalyzer()
    consensus = ai.analyze_consensus(event)
    if not consensus.get("consensus"):
        return {
            "status": "needs_review",
            "reason": "AI consensus is insufficient",
            "consensus": consensus,
        }

    raw = ai._chat_model(
        consensus["verdicts"][0]["provider"],
        consensus["verdicts"][0]["model"],
        _prompt(event),
        True,
        force=False,
    )
    try:
        proposal = json.loads(raw or "{}")
    except (TypeError, ValueError):
        proposal = {}

    action = str(proposal.get("action", "inspect"))
    target = str(proposal.get("target", "unknown"))
    reason = str(proposal.get("reason", "AI remediation proposal"))
    before = str(proposal.get("before", ""))
    after = str(proposal.get("after", ""))
    affected = int(proposal.get("affected_clients", 0) or 0)

    if target.startswith("3x-ui") or "xui" in target.lower():
        plan = xui_plan(action, target, reason, before=before, after=after, affected_clients=affected)
    elif target == "firewall":
        plan = firewall_plan(reason, before=before, after=after)
    elif target.startswith("network") or "routing" in target:
        plan = network_plan(reason, before=before, after=after)
    else:
        plan = xui_plan("inspect", target, reason, before=before, after=after)

    return {
        "status": "proposal",
        "plan": plan,
        "consensus": consensus,
        "execution_required": True,
        "confirmation_required": True,
    }
