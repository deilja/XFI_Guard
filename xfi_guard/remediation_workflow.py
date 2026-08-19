"""Detect -> propose -> confirm -> apply -> verify -> rollback workflow.

The workflow is intentionally transport-agnostic so Telegram/web UI can call it
without receiving permission to execute arbitrary commands.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import secrets

from .remediation import approve
from .remediation_executor import execute_plan
from .safety.change_guard import ChangePlan


@dataclass(frozen=True)
class RemediationProposal:
    proposal_id: str
    plan: ChangePlan
    created_at: str
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


class RemediationWorkflow:
    """State machine for human-approved remediation."""

    def __init__(self) -> None:
        self._proposals: dict[str, RemediationProposal] = {}

    def propose(self, plan: ChangePlan, *, metadata: dict[str, Any] | None = None) -> RemediationProposal:
        proposal = RemediationProposal(
            proposal_id=secrets.token_urlsafe(12),
            plan=plan,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(metadata or {}),
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def get(self, proposal_id: str) -> RemediationProposal | None:
        return self._proposals.get(proposal_id)

    def confirm(self, proposal_id: str) -> dict[str, Any]:
        proposal = self._require(proposal_id)
        if proposal.status != "pending":
            raise ValueError(f"proposal is not pending: {proposal.status}")
        approved = approve(proposal.plan, confirmed=True)
        self._replace(proposal, status="confirmed")
        return {"proposal_id": proposal_id, "status": "confirmed", "approval": approved}

    def apply(
        self,
        proposal_id: str,
        *,
        runners: dict[str, Callable[[ChangePlan], str]] | None = None,
    ) -> dict[str, Any]:
        proposal = self._require(proposal_id)
        if proposal.status != "confirmed":
            raise PermissionError("proposal must be explicitly confirmed before apply")
        result = execute_plan(proposal.plan, confirmed=True, runners=runners)
        status = "applied" if result.get("status") == "executed" else "manual_required"
        self._replace(proposal, status=status)
        return {"proposal_id": proposal_id, **result}

    def verify(self, proposal_id: str, check: Callable[[ChangePlan], bool]) -> dict[str, Any]:
        proposal = self._require(proposal_id)
        if proposal.status != "applied":
            raise ValueError(f"proposal cannot be verified from status: {proposal.status}")
        ok = bool(check(proposal.plan))
        self._replace(proposal, status="verified" if ok else "verify_failed")
        return {"proposal_id": proposal_id, "status": "verified" if ok else "verify_failed", "ok": ok}

    def rollback(self, proposal_id: str, rollback: Callable[[ChangePlan], str]) -> dict[str, Any]:
        proposal = self._require(proposal_id)
        if proposal.status not in {"applied", "verify_failed"}:
            raise ValueError(f"proposal cannot be rolled back from status: {proposal.status}")
        output = rollback(proposal.plan)
        self._replace(proposal, status="rolled_back")
        return {"proposal_id": proposal_id, "status": "rolled_back", "output": output}

    def snapshot(self, proposal_id: str) -> dict[str, Any]:
        proposal = self._require(proposal_id)
        data = asdict(proposal)
        data["plan"] = asdict(proposal.plan)
        return data

    def _require(self, proposal_id: str) -> RemediationProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown remediation proposal: {proposal_id}")
        return proposal

    def _replace(self, proposal: RemediationProposal, *, status: str) -> None:
        self._proposals[proposal.proposal_id] = RemediationProposal(
            proposal_id=proposal.proposal_id,
            plan=proposal.plan,
            created_at=proposal.created_at,
            status=status,
            metadata=proposal.metadata,
        )
