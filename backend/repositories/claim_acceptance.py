"""Validate the bounded audit-only staff ownership mutation inside persistence."""

from collections.abc import Sequence

from backend.domain.audit import AuditEventEnvelope, AuditEventType, AuditOutcome
from backend.domain.claim_ownership import claim_acceptance_eligible
from backend.domain.models import HandoffRecord, WorkingClaim
from backend.repositories.protocols import IdempotencyRecord


def validate_claim_acceptance(
    stored: WorkingClaim,
    claim: WorkingClaim,
    handoffs: Sequence[HandoffRecord],
    idempotency: IdempotencyRecord,
    audit: AuditEventEnvelope | None,
    staff_id: str | None,
    staff_revision: int | None,
) -> None:
    """Reject ownership acquisition without its original state, lease, and audit.

    Args:
        stored: Current Claim read inside the mutation lock or transaction.
        claim: Proposed Claim with only owner, revision, and timestamp changed.
        handoffs: Current Claim handoffs from the same persistence boundary.
        idempotency: Actor-scoped replay record.
        audit: Required immutable success fact.
        staff_id: Presence lease identity guarded by the mutation.
        staff_revision: Required observed lease revision.

    Raises:
        KeyError: Any authority, eligibility, mutation, or audit link is invalid.
    """
    if (
        not claim_acceptance_eligible(stored, handoffs)
        or staff_id != idempotency.actor_id
        or staff_revision is None
        or claim.assignee_id != staff_id
        or claim.revision != stored.revision + 1
        or claim.model_dump(exclude={'assignee_id', 'revision', 'updated_at'})
        != stored.model_dump(exclude={'assignee_id', 'revision', 'updated_at'})
        or idempotency.route != f'/api/v1/workbench/claims/{claim.claim_id}/accept'
        or idempotency.target_ref != claim.claim_id
        or idempotency.claim_id != claim.claim_id
        or audit is None
        or audit.event_type is not AuditEventType.ACTION_COMPLETED
        or audit.outcome is not AuditOutcome.SUCCEEDED
        or audit.actor.actor_type.value != 'staff'
        or audit.actor.actor_id != staff_id
        or audit.subject.subject_type.value != 'claim'
        or audit.subject.subject_id != claim.claim_id
        or audit.subject.claim_id != claim.claim_id
        or audit.claim_revision != claim.revision
        or audit.idempotency_key != idempotency.key
        or audit.permission is None
        or audit.permission.required_permission != 'ownership.accept_claim'
        or audit.permission.outcome.value != 'authorised'
        or audit.visibility.value != 'internal_only'
    ):
        raise KeyError(claim.claim_id)
