"""Eligibility for acquiring ownership after FNOL creation."""

from collections.abc import Sequence

from backend.domain.models import (
    ClaimCreationStatus,
    HandoffRecord,
    HandoffStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkflowState,
    WorkingClaim,
)


def completed_fnol(claim: WorkingClaim) -> bool:
    """Return whether the authoritative creation boundary completed successfully."""
    terminal = claim.terminal_disposition
    return bool(
        claim.claim_state.workflow_state is WorkflowState.CREATED
        and claim.external_claim is not None
        and claim.external_claim.creation_status is ClaimCreationStatus.CREATED
        and terminal is not None
        and terminal.value is TerminalDispositionValue.COMPLETED
        and terminal.reason_code is TerminalDispositionReasonCode.CLAIM_CREATED
    )


def has_claim_owner(claim: WorkingClaim, handoffs: Sequence[HandoffRecord]) -> bool:
    """Include active handoff ownership when deciding whether acquisition is safe."""
    return claim.assignee_id is not None or any(
        item.assigned_to is not None
        and item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
        for item in handoffs
    )


def claim_acceptance_eligible(claim: WorkingClaim, handoffs: Sequence[HandoffRecord]) -> bool:
    """Return Claim eligibility independently of the viewing staff member's presence."""
    return (
        completed_fnol(claim)
        and claim.claim_decision_id is None
        and not has_claim_owner(claim, handoffs)
    )
