import pytest

from xfi_guard.remediation import xui_plan
from xfi_guard.remediation_workflow import RemediationWorkflow


def test_workflow_requires_confirmation_before_apply():
    workflow = RemediationWorkflow()
    proposal = workflow.propose(xui_plan("restart", "x-ui", "service unhealthy"))

    with pytest.raises(PermissionError):
        workflow.apply(proposal.proposal_id)

    workflow.confirm(proposal.proposal_id)
    result = workflow.apply(
        proposal.proposal_id,
        runners={"restart": lambda plan: "restarted"},
    )
    assert result["status"] == "applied"


def test_workflow_verify_failure_can_rollback():
    workflow = RemediationWorkflow()
    proposal = workflow.propose(xui_plan("restart", "x-ui", "service unhealthy"))
    workflow.confirm(proposal.proposal_id)
    workflow.apply(proposal.proposal_id, runners={"restart": lambda plan: "restarted"})

    result = workflow.verify(proposal.proposal_id, lambda plan: False)
    assert result["status"] == "verify_failed"

    rollback = workflow.rollback(proposal.proposal_id, lambda plan: "restored")
    assert rollback["status"] == "rolled_back"
    assert rollback["output"] == "restored"


def test_destructive_plan_never_reaches_generic_apply():
    workflow = RemediationWorkflow()
    proposal = workflow.propose(xui_plan("delete", "3x-ui.inbound", "invalid inbound", affected_clients=2))
    workflow.confirm(proposal.proposal_id)
    result = workflow.apply(proposal.proposal_id)
    assert result["status"] == "manual_required"
