"""Bounded persistence transition rules; no recovery scheduling or provider execution."""

import hashlib
import json

from backend.domain.audit import AuditEventEnvelope
from backend.domain.models import (
    UNSAFE_FOLLOW_UP_REASONS,
    FollowUpOperation,
    FollowUpOperationStatus,
    FollowUpRecord,
    FollowUpStatus,
    RetentionOperation,
    RetentionOperationStatus,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)


class RecoveryAuthorityError(ValueError):
    """Recovery evidence requires operator repair before a state transition."""


def require_follow_up_authority(record: FollowUpRecord) -> None:
    """Reject unsafe obligations without treating readiness as business authority.

    Args:
        record: Current persisted or compatibility-projected obligation.
    Returns:
        None.
    Raises:
        RecoveryAuthorityError: The authoritative blocking condition remains unresolved.
    """
    if record.blocked_reason in UNSAFE_FOLLOW_UP_REASONS:
        raise RecoveryAuthorityError('Follow-up requires authoritative migration repair.')


def follow_up_commit_fingerprint(
    expected: FollowUpOperation,
    operation: FollowUpOperation,
    expected_follow_up: FollowUpRecord,
    follow_up: FollowUpRecord,
    claim: WorkingClaim,
    audit_events: tuple[AuditEventEnvelope, ...],
) -> str:
    """Bind exact recovery commit inputs to the existing idempotency record.

    Args:
        expected: Reservation consumed by this commit.
        operation: Final immutable execution evidence.
        expected_follow_up: Original obligation state.
        follow_up: Resulting obligation state.
        claim: Resulting Claim revision.
        audit_events: Exact accompanying audit evidence.
    Returns:
        Deterministic SHA-256 digest for request_fingerprint.
    Raises:
        ValueError: A model cannot be serialized.
    """
    records = (expected, operation, expected_follow_up, follow_up, claim, *audit_events)
    payload = [record.model_dump(mode='json') for record in records]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_follow_up_commit(
    expected: FollowUpOperation,
    operation: FollowUpOperation,
    previous: FollowUpRecord,
    current: FollowUpRecord,
    claim: WorkingClaim,
    session: SessionRecord | None,
) -> None:
    """Check P17 commit linkage without deciding Runtime policy.

    Args:
        expected: Persisted reservation.
        operation: Final committed operation.
        previous: Expected open obligation.
        current: Proposed aggregate and scheduling state.
        claim: Current authoritative Claim.
        session: Authoritative interruption source.
    Returns:
        None.
    Raises:
        ValueError: Current authority or execution linkage is invalid.
    """
    validate_follow_up_transition(expected, operation)
    previous = FollowUpRecord.model_validate(previous.model_dump())
    current = FollowUpRecord.model_validate(current.model_dump())
    mutable = {'attempt_count', 'status', 'blocked_reason', 'due_at', 'outcome', 'updated_at'}
    if previous.model_dump(exclude=mutable) != current.model_dump(exclude=mutable):
        raise ValueError('Follow-up execution cannot rewrite obligation identity or authority.')
    if (
        operation.status is not FollowUpOperationStatus.COMMITTED
        or previous.status is not FollowUpStatus.PENDING
        or current.status not in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
        or operation.claim_id != claim.claim_id
        or operation.follow_up_id != previous.follow_up_id
        or previous.claim_id != claim.claim_id
        or operation.policy_id != previous.policy_id
        or operation.policy_version != previous.policy_version
        or operation.based_on_claim_revision != claim.revision
        or current.attempt_count != previous.attempt_count + 1
        or claim.active_session_id is not None
        or claim.terminal_disposition is not None
        or session is None
        or session.session_id != previous.source_session_id
        or session.claim_id != claim.claim_id
        or session.customer_id != claim.customer_id
        or session.status is not SessionStatus.PAUSED
        or previous.deadline_at is None
        or previous.due_at is None
        or operation.scheduled_at != previous.due_at
        or operation.committed_at is None
        or not previous.due_at <= operation.committed_at < previous.deadline_at
        or current.updated_at != operation.committed_at
        or current.updated_at < previous.updated_at
        or (current.due_at is not None and current.due_at <= operation.committed_at)
    ):
        raise ValueError('Follow-up commit requires current executable Claim/Session authority.')


def validate_follow_up_transition(previous: FollowUpOperation, current: FollowUpOperation) -> None:
    """Reject identity rewrites and transitions out of a settled operation.

    Args:
        previous: Expected persisted reservation.
        current: Requested final evidence.
    Returns:
        None.
    Raises:
        ValueError: Identity, lifecycle, or timestamp is invalid.
    """
    previous = FollowUpOperation.model_validate(previous.model_dump())
    current = FollowUpOperation.model_validate(current.model_dump())
    mutable = {'status', 'result_code', 'committed_at', 'cancelled_at', 'updated_at'}
    if previous.model_dump(exclude=mutable) != current.model_dump(exclude=mutable):
        raise ValueError('Follow-up operation identity is immutable.')
    if (
        previous.status is not FollowUpOperationStatus.RESERVED
        or current.status is FollowUpOperationStatus.RESERVED
        or current.updated_at < previous.updated_at
    ):
        raise ValueError('Only a reservation can advance to a final result.')
    settled_at = current.committed_at or current.cancelled_at
    if settled_at is None or not previous.created_at <= settled_at <= current.updated_at:
        raise ValueError('Final evidence must fall within the operation lifetime.')


def validate_retention_transition(
    previous: RetentionOperation, current: RetentionOperation
) -> None:
    """Validate monotonic progress without granting permission to perform cleanup.

    Args:
        previous: Expected persisted execution state.
        current: Proposed progress at the next operation revision.
    Returns:
        None.
    Raises:
        ValueError: Identity, revision, lifecycle, or successful evidence changes.
    """
    previous = RetentionOperation.model_validate(previous.model_dump())
    current = RetentionOperation.model_validate(current.model_dump())
    mutable = {'revision', 'status', 'hold_reason', 'step_results', 'updated_at'}
    if previous.model_dump(exclude=mutable) != current.model_dump(exclude=mutable):
        raise ValueError('Retention operation identity is immutable.')
    status = RetentionOperationStatus
    allowed = {
        status.ELIGIBLE: {status.HELD, status.EXECUTING},
        status.HELD: {status.HELD, status.EXECUTING},
        status.EXECUTING: {status.EXECUTING, status.RECONCILIATION_REQUIRED, status.COMPLETED},
        status.RECONCILIATION_REQUIRED: {status.HELD, status.EXECUTING},
        status.COMPLETED: set(),
    }
    if (
        current.status not in allowed[previous.status]
        or current.revision != previous.revision + 1
        or current.updated_at < previous.updated_at
    ):
        raise ValueError('Invalid retention state or revision advancement.')
    for target, result in previous.step_results.items():
        if target not in current.step_results or (
            result in {'deleted', 'already_absent'} and current.step_results[target] != result
        ):
            raise ValueError('Completed retention evidence cannot be removed or rewritten.')
    if previous.status is not status.EXECUTING and current.step_results != previous.step_results:
        raise ValueError('Only executing operations can record step results.')
