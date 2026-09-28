"""Pure deterministic execution rules for P17 incomplete-Claim follow-up."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from backend.domain.ids import stable_operation_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    ClaimTerminalDisposition,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpOperation,
    FollowUpOperationResult,
    FollowUpOperationStatus,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
    assert_follow_up_operation_transition,
)
from backend.domain.recovery import reduce_owned_recovery
from backend.domain.recovery_policy_registry import (
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID,
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE,
    INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL,
    RecoveryTrigger,
)


class FollowUpDueExecutionRejected(ValueError):
    """The authoritative snapshot does not permit this due execution."""


@dataclass(frozen=True, slots=True)
class FollowUpDueTransition:
    """One deterministic P17 in-app due-attempt transition."""

    follow_up: FollowUpRecord
    operation: FollowUpOperation
    settled_previous_operation: FollowUpOperation | None


def _reject(reason: str) -> NoReturn:
    raise FollowUpDueExecutionRejected(reason)


def _operation_id(
    follow_up: FollowUpRecord,
    sequence: int,
) -> str:
    return stable_operation_id(
        'fuo',
        f'{follow_up.follow_up_id}:{follow_up.policy_id}:{follow_up.policy_version}:{sequence}',
    )


def _countable_attempts(
    operations: Sequence[FollowUpOperation],
) -> int:
    """Committed delivery evidence is the sole attempt aggregate authority."""
    return sum(operation.committed_at is not None for operation in operations)


class FollowUpExpiryExecutionRejected(ValueError):
    """The authoritative snapshot does not permit recovery expiry."""


@dataclass(frozen=True, slots=True)
class FollowUpExpiryTransition:
    """Deterministic terminal transition produced by a P17 deadline."""

    claim: WorkingClaim
    follow_up: FollowUpRecord
    reconciled_operation: FollowUpOperation | None


def reduce_due_follow_up(
    claim: WorkingClaim,
    source_session: SessionRecord,
    follow_up: FollowUpRecord,
    operations: Sequence[FollowUpOperation],
    now: datetime,
) -> FollowUpDueTransition:
    """Reduce one authoritative due snapshot into a deterministic transition.

    The function has no repository access and no clock access. ``now`` and every
    authoritative record are supplied by the caller.
    """

    if now.tzinfo is None:
        _reject('Execution time must be timezone-aware.')

    if claim.claim_id != follow_up.claim_id:
        _reject('Follow-up Claim ownership is inconsistent.')

    if claim.terminal_disposition is not None:
        _reject('A terminal Claim cannot execute automatic recovery contact.')

    if claim.active_session_id is not None:
        _reject('An active claimant Session supersedes automatic recovery contact.')

    if (
        source_session.claim_id != claim.claim_id
        or source_session.customer_id != claim.customer_id
        or source_session.session_id != follow_up.source_session_id
        or source_session.status is not SessionStatus.PAUSED
    ):
        _reject('The source Session is not an authoritative paused recovery checkpoint.')

    recovery = source_session.recovery_context
    if recovery is None:
        _reject('The source Session has no recovery context.')

    if follow_up.status is not FollowUpStatus.PENDING:
        _reject('Only a pending Follow-up can execute automatic contact.')

    if (
        follow_up.contact_permission is not FollowUpContactPermission.AUTHORISED
        or follow_up.channel is not PreferredChannel.IN_APP
    ):
        _reject('The v1 automatic recovery channel is not authorised.')

    due_at = follow_up.due_at
    deadline_at = follow_up.deadline_at

    if due_at is None or deadline_at is None:
        _reject('Executable recovery requires both due and deadline timestamps.')

    if (
        follow_up.policy_id != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID
        or follow_up.policy_version != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION
        or deadline_at != recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    ):
        _reject('The Follow-up is not bound to the published P17 policy.')

    if now < due_at:
        _reject('The Follow-up is not due yet.')

    # Deadline always wins a tie.
    if now >= deadline_at:
        _reject('Recovery expiry has precedence over a due attempt.')

    ordered = sorted(
        operations,
        key=lambda operation: (
            operation.sequence,
            operation.operation_id,
        ),
    )

    if len({operation.sequence for operation in ordered}) != len(ordered):
        _reject('Follow-up operation sequence is inconsistent.')

    if any(
        operation.follow_up_id != follow_up.follow_up_id
        or operation.claim_id != claim.claim_id
        or operation.policy_id != follow_up.policy_id
        or operation.policy_version != follow_up.policy_version
        for operation in ordered
    ):
        _reject('Follow-up execution history does not match the obligation.')

    if any(operation.status is FollowUpOperationStatus.SCHEDULED for operation in ordered):
        _reject('A reserved Follow-up operation already requires reconciliation.')

    countable_attempts = _countable_attempts(ordered)

    if follow_up.attempt_count != countable_attempts:
        _reject('Follow-up attempt aggregate disagrees with committed operation history.')

    policy_plan = reduce_owned_recovery(
        RecoveryTrigger(source='timer', outcome_code='follow_up_due'),
        claim.claim_id,
        claim.revision,
        follow_up.follow_up_id,
        now,
        follow_up.source_refs,
    )
    if countable_attempts >= policy_plan.max_auto_retry:
        _reject('The automatic Follow-up attempt limit is already exhausted.')

    expected_due = (
        recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL * countable_attempts
    )
    if due_at != expected_due:
        _reject('Follow-up due time does not match the immutable v1 cadence.')

    outstanding = [
        operation for operation in ordered if operation.status is FollowUpOperationStatus.COMMITTED
    ]

    if len(outstanding) > 1:
        _reject('More than one committed Follow-up operation is awaiting settlement.')

    settled_previous: FollowUpOperation | None = None

    if outstanding:
        previous = outstanding[0]

        if (
            previous.sequence != max(operation.sequence for operation in ordered)
            or previous.committed_at is None
            or previous.result is not FollowUpOperationResult.DELIVERED_IN_APP
        ):
            _reject('Outstanding Follow-up delivery evidence is inconsistent.')

        settled_previous = previous.model_copy(
            update={
                'status': FollowUpOperationStatus.SETTLED,
                'result': FollowUpOperationResult.NO_RESPONSE,
                'settled_at': now,
            }
        )
        assert_follow_up_operation_transition(
            previous,
            settled_previous,
        )

    next_sequence = (
        max(
            (operation.sequence for operation in ordered),
            default=0,
        )
        + 1
    )

    scheduled = FollowUpOperation(
        operation_id=_operation_id(follow_up, next_sequence),
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=next_sequence,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=due_at,
        created_at=now,
        updated_at=now,
        status=FollowUpOperationStatus.SCHEDULED,
        source_refs=[
            f'follow-up:{follow_up.follow_up_id}',
            f'claim:{claim.claim_id}:revision:{claim.revision}',
            f'session:{source_session.session_id}',
        ],
    )

    committed = scheduled.model_copy(
        update={
            'status': FollowUpOperationStatus.COMMITTED,
            'result': FollowUpOperationResult.DELIVERED_IN_APP,
            'committed_at': now,
        }
    )
    assert_follow_up_operation_transition(scheduled, committed)

    next_attempt_count = countable_attempts + 1

    if next_attempt_count >= policy_plan.max_auto_retry:
        exhaustion_plan = reduce_owned_recovery(
            RecoveryTrigger(source='timer', outcome_code='attempt_limit_reached'),
            claim.claim_id,
            claim.revision,
            follow_up.follow_up_id,
            now,
            follow_up.source_refs,
        )
        if exhaustion_plan.decision_code != 'block_follow_up':
            _reject('Published policy does not permit attempt exhaustion.')
        updated_follow_up = follow_up.model_copy(
            update={
                'attempt_count': next_attempt_count,
                'active_operation_id': committed.operation_id,
                'status': FollowUpStatus.BLOCKED,
                'reason_code': FollowUpReasonCode.ATTEMPT_LIMIT_REACHED,
                'due_at': None,
                'updated_at': now,
            }
        )
    else:
        next_due = (
            recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL * next_attempt_count
        )

        if next_due >= deadline_at:
            _reject('The next automatic attempt would not precede recovery expiry.')

        updated_follow_up = follow_up.model_copy(
            update={
                'attempt_count': next_attempt_count,
                'active_operation_id': committed.operation_id,
                'status': FollowUpStatus.PENDING,
                'reason_code': None,
                'due_at': next_due,
                'updated_at': now,
            }
        )

    return FollowUpDueTransition(
        follow_up=updated_follow_up,
        operation=committed,
        settled_previous_operation=settled_previous,
    )


class FollowUpContactWithdrawalRejected(ValueError):
    """The current P17 recovery state cannot accept contact withdrawal."""


@dataclass(frozen=True, slots=True)
class FollowUpContactWithdrawalTransition:
    """Deterministic result of removing automatic follow-up authority."""

    follow_up: FollowUpRecord
    reconciled_operation: FollowUpOperation | None


def reduce_follow_up_contact_withdrawal(
    claim: WorkingClaim,
    source_session: SessionRecord,
    follow_up: FollowUpRecord,
    operations: Sequence[FollowUpOperation],
    now: datetime,
) -> FollowUpContactWithdrawalTransition:
    """Block automatic recovery contact without terminating the Claim."""

    if now.tzinfo is None:
        raise FollowUpContactWithdrawalRejected('Contact withdrawal time must be timezone-aware.')

    if claim.claim_id != follow_up.claim_id:
        raise FollowUpContactWithdrawalRejected('Follow-up Claim ownership is inconsistent.')

    if claim.terminal_disposition is not None:
        raise FollowUpContactWithdrawalRejected(
            'A terminal Claim has no open automatic recovery contact.'
        )

    if follow_up.status not in {
        FollowUpStatus.PENDING,
        FollowUpStatus.BLOCKED,
    }:
        raise FollowUpContactWithdrawalRejected(
            'Only an open recovery obligation may withdraw contact authority.'
        )

    recovery = source_session.recovery_context

    if (
        source_session.claim_id != claim.claim_id
        or source_session.customer_id != claim.customer_id
        or source_session.session_id != follow_up.source_session_id
        or source_session.status is not SessionStatus.PAUSED
        or recovery is None
    ):
        raise FollowUpContactWithdrawalRejected(
            'The source Session is not the authoritative paused checkpoint.'
        )

    deadline_at = follow_up.deadline_at

    if (
        follow_up.policy_id != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID
        or follow_up.policy_version != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION
        or deadline_at is None
        or deadline_at != recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    ):
        raise FollowUpContactWithdrawalRejected(
            'The Follow-up is not bound to the published P17 policy.'
        )

    if now >= deadline_at:
        raise FollowUpContactWithdrawalRejected(
            'Recovery expiry has precedence over contact withdrawal.'
        )

    if follow_up.contact_permission is FollowUpContactPermission.NOT_AUTHORISED:
        raise FollowUpContactWithdrawalRejected(
            'Automatic recovery contact is already not authorised.'
        )

    ordered = sorted(
        operations,
        key=lambda operation: (
            operation.sequence,
            operation.operation_id,
        ),
    )

    if len({operation.sequence for operation in ordered}) != len(ordered):
        raise FollowUpContactWithdrawalRejected('Follow-up operation sequence is inconsistent.')

    if any(
        operation.follow_up_id != follow_up.follow_up_id
        or operation.claim_id != claim.claim_id
        or operation.policy_id != follow_up.policy_id
        or operation.policy_version != follow_up.policy_version
        for operation in ordered
    ):
        raise FollowUpContactWithdrawalRejected(
            'Follow-up execution history does not match the obligation.'
        )

    committed_attempts = sum(operation.committed_at is not None for operation in ordered)

    if follow_up.attempt_count != committed_attempts:
        raise FollowUpContactWithdrawalRejected(
            'Follow-up attempt aggregate disagrees with operation history.'
        )

    open_operations = [
        operation
        for operation in ordered
        if operation.status
        in {
            FollowUpOperationStatus.SCHEDULED,
            FollowUpOperationStatus.COMMITTED,
        }
    ]

    if len(open_operations) > 1:
        raise FollowUpContactWithdrawalRejected(
            'Multiple logical Follow-up operations remain open.'
        )

    reconciled: FollowUpOperation | None = None

    if open_operations:
        current_operation = open_operations[0]

        if current_operation.status is FollowUpOperationStatus.SCHEDULED:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.CANCELLED,
                    'result': FollowUpOperationResult.AUTHORITY_WITHDRAWN,
                    'cancelled_at': now,
                }
            )
        else:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.SETTLED,
                    'result': FollowUpOperationResult.AUTHORITY_WITHDRAWN,
                    'settled_at': now,
                }
            )

        assert_follow_up_operation_transition(
            current_operation,
            reconciled,
        )

    updated_follow_up = follow_up.model_copy(
        update={
            'contact_permission': (FollowUpContactPermission.NOT_AUTHORISED),
            'channel': None,
            'status': FollowUpStatus.BLOCKED,
            'reason_code': FollowUpReasonCode.CONTACT_NOT_AUTHORISED,
            'active_operation_id': None,
            'due_at': None,
            'updated_at': now,
        }
    )

    policy_plan = reduce_owned_recovery(
        RecoveryTrigger(source='human', outcome_code='contact_authority_withdrawn'),
        claim.claim_id,
        claim.revision,
        follow_up.follow_up_id,
        now,
        follow_up.source_refs,
    )
    if policy_plan.decision_code != 'block_follow_up':
        raise FollowUpContactWithdrawalRejected(
            'Published policy does not permit contact blocking.'
        )
    return FollowUpContactWithdrawalTransition(
        follow_up=updated_follow_up,
        reconciled_operation=reconciled,
    )


def reduce_expired_follow_up(
    claim: WorkingClaim,
    source_session: SessionRecord,
    follow_up: FollowUpRecord,
    operations: Sequence[FollowUpOperation],
    now: datetime,
) -> FollowUpExpiryTransition:
    """Resolve an open P17 recovery obligation at its absolute deadline."""

    if now.tzinfo is None:
        raise FollowUpExpiryExecutionRejected('Expiry time must be timezone-aware.')

    if claim.claim_id != follow_up.claim_id:
        raise FollowUpExpiryExecutionRejected('Follow-up Claim ownership is inconsistent.')

    if claim.terminal_disposition is not None:
        raise FollowUpExpiryExecutionRejected('The Claim is already terminal.')

    if claim.active_session_id is not None:
        raise FollowUpExpiryExecutionRejected(
            'An active claimant Session prevents expiry of this checkpoint.'
        )

    if follow_up.status not in {
        FollowUpStatus.PENDING,
        FollowUpStatus.BLOCKED,
    }:
        raise FollowUpExpiryExecutionRejected('Only an open recovery obligation may expire.')

    recovery = source_session.recovery_context

    if (
        source_session.claim_id != claim.claim_id
        or source_session.customer_id != claim.customer_id
        or source_session.session_id != follow_up.source_session_id
        or source_session.status is not SessionStatus.PAUSED
        or recovery is None
    ):
        raise FollowUpExpiryExecutionRejected(
            'The source Session is not the authoritative paused checkpoint.'
        )

    deadline_at = follow_up.deadline_at

    if (
        follow_up.policy_id != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID
        or follow_up.policy_version != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION
        or deadline_at is None
        or deadline_at != recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    ):
        raise FollowUpExpiryExecutionRejected(
            'The Follow-up is not bound to the published P17 deadline.'
        )

    if now < deadline_at:
        raise FollowUpExpiryExecutionRejected('The recovery deadline has not been reached.')

    ordered = sorted(
        operations,
        key=lambda operation: (
            operation.sequence,
            operation.operation_id,
        ),
    )

    if len({operation.sequence for operation in ordered}) != len(ordered):
        raise FollowUpExpiryExecutionRejected('Follow-up operation sequence is inconsistent.')

    if any(
        operation.follow_up_id != follow_up.follow_up_id
        or operation.claim_id != claim.claim_id
        or operation.policy_id != follow_up.policy_id
        or operation.policy_version != follow_up.policy_version
        for operation in ordered
    ):
        raise FollowUpExpiryExecutionRejected(
            'Follow-up execution history does not match the obligation.'
        )

    committed_attempts = sum(operation.committed_at is not None for operation in ordered)

    if follow_up.attempt_count != committed_attempts:
        raise FollowUpExpiryExecutionRejected(
            'Follow-up attempt aggregate disagrees with operation history.'
        )

    open_operations = [
        operation
        for operation in ordered
        if operation.status
        in {
            FollowUpOperationStatus.SCHEDULED,
            FollowUpOperationStatus.COMMITTED,
        }
    ]

    if len(open_operations) > 1:
        raise FollowUpExpiryExecutionRejected('Multiple logical Follow-up operations remain open.')

    reconciled: FollowUpOperation | None = None

    if open_operations:
        current_operation = open_operations[0]

        if current_operation.status is FollowUpOperationStatus.SCHEDULED:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.CANCELLED,
                    'result': (FollowUpOperationResult.EXPIRED_BEFORE_EXECUTION),
                    'cancelled_at': now,
                }
            )
        else:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.SETTLED,
                    'result': FollowUpOperationResult.NO_RESPONSE,
                    'settled_at': now,
                }
            )

        assert_follow_up_operation_transition(
            current_operation,
            reconciled,
        )

    updated_follow_up = follow_up.model_copy(
        update={
            'status': FollowUpStatus.RESOLVED,
            'reason_code': FollowUpReasonCode.RECOVERY_EXPIRED,
            'active_operation_id': None,
            'outcome': 'recovery_expired',
            'due_at': None,
            'updated_at': now,
        }
    )

    terminal = ClaimTerminalDisposition(
        value=TerminalDispositionValue.ABANDONED,
        reason_code=TerminalDispositionReasonCode.RECOVERY_EXPIRED,
        source_refs=list(
            dict.fromkeys(
                [
                    *follow_up.source_refs,
                    f'follow-up:{follow_up.follow_up_id}',
                ]
            )
        ),
        recorded_by=ActorReference(
            actor_type=ActorType.SYSTEM,
            actor_id='p17-recovery-expiry',
        ),
        recorded_at=now,
        recorded_revision=claim.revision + 1,
    )

    updated_claim = claim.model_copy(
        update={
            'terminal_disposition': terminal,
            'customer_next_step': CustomerNextStep(
                status='abandoned',
                summary=('The recovery window for this incomplete Claim has expired.'),
                responsible_party=ResponsibleParty.SYSTEM,
                can_resume=False,
            ),
            'revision': claim.revision + 1,
            'updated_at': now,
        }
    )

    policy_plan = reduce_owned_recovery(
        RecoveryTrigger(source='timer', outcome_code='recovery_expired'),
        claim.claim_id,
        claim.revision,
        follow_up.follow_up_id,
        now,
        follow_up.source_refs,
    )
    if policy_plan.decision_code != 'expire_recovery':
        raise FollowUpExpiryExecutionRejected('Published policy does not permit recovery expiry.')
    return FollowUpExpiryTransition(
        claim=updated_claim,
        follow_up=updated_follow_up,
        reconciled_operation=reconciled,
    )


class FollowUpStaffAbandonmentRejected(ValueError):
    """The authoritative recovery snapshot cannot be staff-abandoned."""


@dataclass(frozen=True, slots=True)
class FollowUpStaffAbandonmentTransition:
    """Deterministic staff-authorised terminal recovery transition."""

    claim: WorkingClaim
    follow_up: FollowUpRecord
    reconciled_operation: FollowUpOperation | None


def reduce_follow_up_staff_abandonment(
    claim: WorkingClaim,
    source_session: SessionRecord,
    follow_up: FollowUpRecord,
    operations: Sequence[FollowUpOperation],
    now: datetime,
    recorded_by: ActorReference,
) -> FollowUpStaffAbandonmentTransition:
    """Abandon one incomplete Claim without confusing it with attempt exhaustion."""

    if now.tzinfo is None:
        raise FollowUpStaffAbandonmentRejected('Staff abandonment time must be timezone-aware.')

    if recorded_by.actor_type is not ActorType.STAFF:
        raise FollowUpStaffAbandonmentRejected(
            'Staff abandonment requires an authorised staff actor.'
        )

    if claim.claim_id != follow_up.claim_id:
        raise FollowUpStaffAbandonmentRejected('Follow-up Claim ownership is inconsistent.')

    if claim.terminal_disposition is not None:
        raise FollowUpStaffAbandonmentRejected('The Claim is already terminal.')

    if claim.active_session_id is not None:
        raise FollowUpStaffAbandonmentRejected(
            'An active claimant Session prevents staff abandonment of this checkpoint.'
        )

    if follow_up.status not in {
        FollowUpStatus.PENDING,
        FollowUpStatus.BLOCKED,
    }:
        raise FollowUpStaffAbandonmentRejected(
            'Only an open recovery obligation may be staff-abandoned.'
        )

    recovery = source_session.recovery_context

    if (
        source_session.claim_id != claim.claim_id
        or source_session.customer_id != claim.customer_id
        or source_session.session_id != follow_up.source_session_id
        or source_session.status is not SessionStatus.PAUSED
        or recovery is None
    ):
        raise FollowUpStaffAbandonmentRejected(
            'The source Session is not the authoritative paused checkpoint.'
        )

    deadline_at = follow_up.deadline_at

    if (
        follow_up.policy_id != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID
        or follow_up.policy_version != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION
        or deadline_at is None
        or deadline_at != recovery.interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    ):
        raise FollowUpStaffAbandonmentRejected(
            'The Follow-up is not bound to the published P17 policy.'
        )

    # At or after the deadline, expiry owns the terminal result.
    if now >= deadline_at:
        raise FollowUpStaffAbandonmentRejected(
            'Recovery expiry has precedence over staff abandonment.'
        )

    ordered = sorted(
        operations,
        key=lambda operation: (
            operation.sequence,
            operation.operation_id,
        ),
    )

    if len({operation.sequence for operation in ordered}) != len(ordered):
        raise FollowUpStaffAbandonmentRejected('Follow-up operation sequence is inconsistent.')

    if any(
        operation.follow_up_id != follow_up.follow_up_id
        or operation.claim_id != claim.claim_id
        or operation.policy_id != follow_up.policy_id
        or operation.policy_version != follow_up.policy_version
        for operation in ordered
    ):
        raise FollowUpStaffAbandonmentRejected(
            'Follow-up execution history does not match the obligation.'
        )

    committed_attempts = sum(operation.committed_at is not None for operation in ordered)

    if follow_up.attempt_count != committed_attempts:
        raise FollowUpStaffAbandonmentRejected(
            'Follow-up attempt aggregate disagrees with operation history.'
        )

    open_operations = [
        operation
        for operation in ordered
        if operation.status
        in {
            FollowUpOperationStatus.SCHEDULED,
            FollowUpOperationStatus.COMMITTED,
        }
    ]

    if len(open_operations) > 1:
        raise FollowUpStaffAbandonmentRejected('Multiple logical Follow-up operations remain open.')

    reconciled: FollowUpOperation | None = None

    if open_operations:
        current_operation = open_operations[0]

        if current_operation.status is FollowUpOperationStatus.SCHEDULED:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.CANCELLED,
                    'result': FollowUpOperationResult.AUTHORITY_WITHDRAWN,
                    'cancelled_at': now,
                }
            )
        else:
            reconciled = current_operation.model_copy(
                update={
                    'status': FollowUpOperationStatus.SETTLED,
                    'result': FollowUpOperationResult.AUTHORITY_WITHDRAWN,
                    'settled_at': now,
                }
            )

        assert_follow_up_operation_transition(
            current_operation,
            reconciled,
        )

    source_refs = list(
        dict.fromkeys(
            [
                *follow_up.source_refs,
                f'follow-up:{follow_up.follow_up_id}',
            ]
        )
    )

    updated_follow_up = follow_up.model_copy(
        update={
            'status': FollowUpStatus.RESOLVED,
            'reason_code': FollowUpReasonCode.STAFF_ABANDONED,
            'active_operation_id': None,
            'outcome': 'staff_abandoned',
            'due_at': None,
            'updated_at': now,
        }
    )

    updated_claim = claim.model_copy(
        update={
            'terminal_disposition': ClaimTerminalDisposition(
                value=TerminalDispositionValue.ABANDONED,
                reason_code=(TerminalDispositionReasonCode.AUTHORISED_STAFF_ABANDONMENT),
                source_refs=source_refs,
                recorded_by=recorded_by,
                recorded_at=now,
                recorded_revision=claim.revision + 1,
            ),
            'revision': claim.revision + 1,
            'updated_at': now,
        }
    )

    return FollowUpStaffAbandonmentTransition(
        claim=updated_claim,
        follow_up=updated_follow_up,
        reconciled_operation=reconciled,
    )
