"""Shared incomplete-Claim recovery projection rules."""

from collections.abc import Sequence

from backend.domain.models import (
    FollowUpRecord,
    FollowUpStatus,
    SessionRecord,
    SessionStatus,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository


def recovery_checkpoint_allowed(claim: WorkingClaim) -> bool:
    """Return whether authoritative Claim lifecycle permits recovery."""
    return (
        claim.claim_state.workflow_state is not WorkflowState.CREATED
        and claim.customer_next_step.can_resume
    )


def find_incomplete_recovery(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    sessions: Sequence[SessionRecord] | None = None,
) -> tuple[SessionRecord, FollowUpRecord] | None:
    """Resolve the newest valid incomplete recovery checkpoint."""
    if claim.active_session_id is not None:
        return None

    if not recovery_checkpoint_allowed(claim):
        return None

    available_sessions = (
        list(sessions)
        if sessions is not None
        else repository.list_sessions_for_claim(
            claim.claim_id,
            claim.customer_id,
        )
    )

    follow_ups = repository.list_follow_ups(
        claim.claim_id,
        claim.customer_id,
    )

    selected = None
    selected_key = None

    for session in available_sessions:
        recovery = session.recovery_context

        if session.status is not SessionStatus.PAUSED or recovery is None:
            continue

        matching = [
            record
            for record in follow_ups
            if record.source_session_id == session.session_id
            and record.purpose == 'resume_incomplete_claim'
            and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
        ]

        if not matching:
            continue

        follow_up = max(
            matching,
            key=lambda record: (
                record.created_at,
                record.follow_up_id,
            ),
        )

        key = (
            recovery.interrupted_at,
            session.session_id,
            follow_up.created_at,
            follow_up.follow_up_id,
        )

        if selected_key is None or key > selected_key:
            selected = (session, follow_up)
            selected_key = key

    return selected
