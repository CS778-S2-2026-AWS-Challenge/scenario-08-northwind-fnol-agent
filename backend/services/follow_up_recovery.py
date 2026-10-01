"""Bounded P17 automatic follow-up execution service."""

from datetime import datetime

from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.follow_up_execution import (
    FollowUpContactWithdrawalRejected,
    FollowUpContactWithdrawalTransition,
    FollowUpDueExecutionRejected,
    FollowUpDueTransition,
    FollowUpExpiryExecutionRejected,
    FollowUpExpiryTransition,
    reduce_due_follow_up,
    reduce_expired_follow_up,
    reduce_follow_up_contact_withdrawal,
)
from backend.domain.ids import stable_digest
from backend.domain.models import (
    ActorType,
    FollowUpRecord,
    MessageRecord,
    MessageVisibility,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    PersistenceRepository,
    RevisionConflict,
)


def _recovery_audit(
    *,
    suffix: str,
    event_type: AuditEventType,
    claim_id: str,
    claim_revision: int,
    actor_id: str,
    auth_source: str,
    reason: str,
    source_refs: list[str],
    created_at: datetime,
    permission: AuditPermission | None = None,
) -> AuditEventEnvelope:
    identity = stable_digest(f'{suffix}:{claim_id}')

    return AuditEventEnvelope(
        event_id=f'aud_recovery_{identity}',
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.SYSTEM,
            actor_id=actor_id,
            auth_source=auth_source,
        ),
        reason=reason,
        source_refs=list(dict.fromkeys(source_refs)),
        permission=permission,
        visibility=AuditVisibility.INTERNAL_ONLY,
        correlation_id=suffix[:100],
        claim_revision=claim_revision,
        created_at=created_at,
    )


def _in_app_follow_up_message(
    follow_up: FollowUpRecord,
    operation_id: str,
    policy_id: str,
    policy_version: int,
    *,
    created_at: datetime,
) -> MessageRecord:
    """Build the durable claimant-visible result of one committed in-app attempt."""

    identity = stable_digest(operation_id)
    return MessageRecord(
        message_id=f'msg_recovery_{identity}',
        claim_id=follow_up.claim_id,
        session_id=follow_up.source_session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={
            'type': 'text',
            'text': (
                'Your claim is still saved. You can return to continue '
                'where you left off when you are ready.'
            ),
        },
        recovery_rule_id=f'{policy_id}.v{policy_version}',
        created_at=created_at,
    )


def process_due_follow_up(
    repository: PersistenceRepository,
    candidate: FollowUpRecord,
    now: datetime,
) -> FollowUpDueTransition | None:
    """Reload and atomically execute one due candidate.

    Discovery records are hints only. Every authoritative predicate is reloaded
    and then checked again by the repository transaction.
    """

    claim = repository.get_claim_internal(candidate.claim_id)
    if claim is None:
        return None

    current = repository.get_follow_up(
        candidate.claim_id,
        candidate.follow_up_id,
        claim.customer_id,
    )
    if current is None:
        return None

    source_session = repository.get_session(
        claim.claim_id,
        current.source_session_id,
        claim.customer_id,
    )
    if source_session is None:
        return None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        current.follow_up_id,
        claim.customer_id,
    )

    try:
        transition = reduce_due_follow_up(
            claim,
            source_session,
            current,
            operations,
            now,
        )
    except FollowUpDueExecutionRejected:
        return None

    try:
        audit_event = _recovery_audit(
            suffix=f'due:{transition.operation.operation_id}',
            event_type=AuditEventType.ACTION_COMPLETED,
            claim_id=claim.claim_id,
            claim_revision=claim.revision,
            actor_id='p17-recovery-worker',
            auth_source='internal:recovery-worker',
            reason='Committed one authorised incomplete-Claim in-app follow-up.',
            source_refs=[
                *transition.operation.source_refs,
                transition.operation.operation_id,
            ],
            created_at=now,
        )

        in_app_message = _in_app_follow_up_message(
            current,
            transition.operation.operation_id,
            transition.operation.policy_id,
            transition.operation.policy_version,
            created_at=now,
        )

        repository.commit_due_follow_up_attempt(
            current,
            transition.follow_up,
            transition.operation,
            transition.settled_previous_operation,
            in_app_message,
            claim.customer_id,
            audit_event,
        )
    except (IdempotencyConflict, KeyError):
        return None

    return transition


def process_expiring_follow_up(
    repository: PersistenceRepository,
    candidate: FollowUpRecord,
    now: datetime,
) -> FollowUpExpiryTransition | None:
    """Reload and atomically expire one open P17 recovery obligation."""

    claim = repository.get_claim_internal(candidate.claim_id)
    if claim is None:
        return None

    current = repository.get_follow_up(
        candidate.claim_id,
        candidate.follow_up_id,
        claim.customer_id,
    )
    if current is None:
        return None

    source_session = repository.get_session(
        claim.claim_id,
        current.source_session_id,
        claim.customer_id,
    )
    if source_session is None:
        return None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        current.follow_up_id,
        claim.customer_id,
    )

    try:
        transition = reduce_expired_follow_up(
            claim,
            source_session,
            current,
            operations,
            now,
        )
    except FollowUpExpiryExecutionRejected:
        return None

    try:
        audit_event = _recovery_audit(
            suffix=f'expiry:{current.follow_up_id}',
            event_type=AuditEventType.ACTION_COMPLETED,
            claim_id=claim.claim_id,
            claim_revision=transition.claim.revision,
            actor_id='p17-recovery-expiry',
            auth_source='internal:recovery-worker',
            reason='The incomplete-Claim recovery deadline expired.',
            source_refs=[
                *current.source_refs,
                f'follow-up:{current.follow_up_id}',
            ],
            created_at=now,
        )

        repository.commit_recovery_expiry(
            claim.revision,
            current,
            transition.claim,
            transition.follow_up,
            transition.reconciled_operation,
            claim.customer_id,
            audit_event,
        )
    except (IdempotencyConflict, RevisionConflict, KeyError):
        return None

    return transition


def process_follow_up_contact_withdrawal(
    repository: PersistenceRepository,
    candidate: FollowUpRecord,
    now: datetime,
) -> FollowUpContactWithdrawalTransition | None:
    """Withdraw automatic P17 contact authority without terminalising the Claim."""

    claim = repository.get_claim_internal(candidate.claim_id)
    if claim is None:
        return None

    current = repository.get_follow_up(
        candidate.claim_id,
        candidate.follow_up_id,
        claim.customer_id,
    )
    if current is None:
        return None

    source_session = repository.get_session(
        claim.claim_id,
        current.source_session_id,
        claim.customer_id,
    )
    if source_session is None:
        return None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        current.follow_up_id,
        claim.customer_id,
    )

    try:
        transition = reduce_follow_up_contact_withdrawal(
            claim,
            source_session,
            current,
            operations,
            now,
        )
    except FollowUpContactWithdrawalRejected:
        return None

    audit_event = _recovery_audit(
        suffix=f'contact-withdrawal:{current.follow_up_id}',
        event_type=AuditEventType.PERMISSION_REJECTED,
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        actor_id='p17-contact-authority',
        auth_source='internal:contact-authority',
        reason='Automatic incomplete-Claim recovery contact authority was withdrawn.',
        source_refs=[
            *current.source_refs,
            f'follow-up:{current.follow_up_id}',
        ],
        created_at=now,
        permission=AuditPermission(
            required_permission='p17.follow_up.contact',
            outcome=AuditPermissionOutcome.REJECTED,
        ),
    )

    try:
        repository.commit_follow_up_contact_withdrawal(
            claim.revision,
            current,
            transition.follow_up,
            transition.reconciled_operation,
            claim.customer_id,
            audit_event,
        )
    except (IdempotencyConflict, RevisionConflict, KeyError):
        return None

    return transition
