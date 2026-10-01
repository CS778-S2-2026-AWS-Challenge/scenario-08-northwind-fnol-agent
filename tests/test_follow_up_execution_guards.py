"""Fail-closed snapshot guards shared by the pure P17 follow-up reducers.

Every reducer receives one authoritative snapshot. Each case below corrupts
exactly one fact of an otherwise executable snapshot and asserts that the
reducer refuses it for that reason instead of producing a transition.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from backend.domain.follow_up_execution import (
    FollowUpContactWithdrawalRejected,
    FollowUpDueExecutionRejected,
    FollowUpExpiryExecutionRejected,
    FollowUpStaffAbandonmentRejected,
    reduce_due_follow_up,
    reduce_expired_follow_up,
    reduce_follow_up_contact_withdrawal,
    reduce_follow_up_staff_abandonment,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimState,
    ClaimTerminalDisposition,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpOperation,
    FollowUpOperationResult,
    FollowUpOperationStatus,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.domain.recovery_policy_registry import (
    INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE,
    INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL,
)

INTERRUPTED_AT = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
DEADLINE_AT = INTERRUPTED_AT + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
STAFF = ActorReference(actor_type=ActorType.STAFF, actor_id='stf_guard')


@dataclass(frozen=True)
class Snapshot:
    claim: WorkingClaim
    session: SessionRecord
    follow_up: FollowUpRecord
    operations: Sequence[FollowUpOperation]


def _snapshot() -> Snapshot:
    claim = WorkingClaim(
        claim_id='clm_guard',
        customer_id='cus_guard',
        revision=2,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=None,
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=INTERRUPTED_AT,
        updated_at=INTERRUPTED_AT,
    )
    session = SessionRecord(
        session_id='ses_guard',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.PAUSED,
        context_revision=1,
        started_at=INTERRUPTED_AT,
        last_active_at=INTERRUPTED_AT,
        recovery_context=SessionRecoveryContext(
            interrupted_at=INTERRUPTED_AT,
            last_meaningful_activity_at=INTERRUPTED_AT,
            last_meaningful_activity_source_ref='claim:clm_guard:revision:1',
            resume_point='Continue describing the incident.',
        ),
    )
    follow_up = FollowUpRecord(
        follow_up_id='fup_guard',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        deadline_at=DEADLINE_AT,
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=['claim:clm_guard:revision:2', 'session:ses_guard'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        attempt_count=0,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=INTERRUPTED_AT,
        created_at=INTERRUPTED_AT,
        updated_at=INTERRUPTED_AT,
    )
    return Snapshot(claim, session, follow_up, [])


def _scheduled_operation(snapshot: Snapshot) -> FollowUpOperation:
    """A genuine reserved operation produced by the due reducer itself."""

    return reduce_due_follow_up(
        snapshot.claim,
        snapshot.session,
        snapshot.follow_up,
        [],
        INTERRUPTED_AT,
    ).operation


def _with(snapshot: Snapshot, part: str, **update: Any) -> Snapshot:
    return replace(snapshot, **{part: getattr(snapshot, part).model_copy(update=update)})


Mutation = Callable[[Snapshot], Snapshot]


def _terminal(snapshot: Snapshot) -> Snapshot:
    return _with(
        snapshot,
        'claim',
        terminal_disposition=ClaimTerminalDisposition(
            value=TerminalDispositionValue.ABANDONED,
            reason_code=TerminalDispositionReasonCode.RECOVERY_EXPIRED,
            source_refs=['follow-up:fup_guard'],
            recorded_by=ActorReference(actor_type=ActorType.SYSTEM, actor_id='p17'),
            recorded_at=INTERRUPTED_AT,
            recorded_revision=2,
        ),
    )


def _duplicate_sequence(snapshot: Snapshot) -> Snapshot:
    operation = _scheduled_operation(snapshot)
    duplicate = operation.model_copy(update={'operation_id': f'{operation.operation_id}_dup'})
    return replace(snapshot, operations=[operation, duplicate])


def _foreign_history(snapshot: Snapshot) -> Snapshot:
    operation = _scheduled_operation(snapshot)
    return replace(
        snapshot, operations=[operation.model_copy(update={'follow_up_id': 'fup_other'})]
    )


def _two_open_operations(snapshot: Snapshot) -> Snapshot:
    operation = _scheduled_operation(snapshot)
    later = operation.model_copy(
        update={
            'operation_id': f'{operation.operation_id}_next',
            'sequence': operation.sequence + 1,
        }
    )
    operations = [operation, later]
    # Keep the attempt aggregate truthful so only the open-operation guard fires.
    committed = sum(item.committed_at is not None for item in operations)
    return replace(
        _with(snapshot, 'follow_up', attempt_count=committed),
        operations=operations,
    )


COMMON: list[tuple[str, Mutation, str]] = [
    (
        'claim-ownership',
        lambda s: _with(s, 'follow_up', claim_id='clm_other'),
        'ownership is inconsistent',
    ),
    ('terminal-claim', _terminal, '[Tt]erminal'),
    (
        'session-not-paused',
        lambda s: _with(s, 'session', status=SessionStatus.ACTIVE),
        'source Session',
    ),
    (
        'session-for-other-customer',
        lambda s: _with(s, 'session', customer_id='cus_other'),
        'source Session',
    ),
    (
        'session-without-recovery',
        lambda s: _with(s, 'session', recovery_context=None),
        'Session',
    ),
    (
        'other-policy-version',
        lambda s: _with(s, 'follow_up', policy_version=2),
        'published P17',
    ),
    (
        'deadline-drift',
        lambda s: _with(s, 'follow_up', deadline_at=DEADLINE_AT + timedelta(hours=1)),
        'published P17',
    ),
    ('duplicate-sequence', _duplicate_sequence, 'sequence is inconsistent'),
    ('foreign-history', _foreign_history, 'does not match the obligation'),
    (
        'attempt-aggregate',
        lambda s: _with(s, 'follow_up', attempt_count=1),
        'aggregate disagrees',
    ),
]

ACTIVE_SESSION: tuple[str, Mutation, str] = (
    'active-session',
    lambda s: _with(s, 'claim', active_session_id='ses_new'),
    'active claimant Session',
)
CLOSED_OBLIGATION: tuple[str, Mutation, str] = (
    'closed-obligation',
    lambda s: _with(s, 'follow_up', status=FollowUpStatus.RESOLVED),
    'open recovery obligation',
)
TWO_OPEN: tuple[str, Mutation, str] = (
    'two-open-operations',
    _two_open_operations,
    'remain open|already requires reconciliation|awaiting settlement',
)


@dataclass(frozen=True)
class Reducer:
    name: str
    rejected: type[ValueError]
    valid_now: datetime
    run: Callable[[Snapshot, datetime], object]


REDUCERS = {
    'due': Reducer(
        'due',
        FollowUpDueExecutionRejected,
        INTERRUPTED_AT + timedelta(minutes=1),
        lambda s, now: reduce_due_follow_up(s.claim, s.session, s.follow_up, s.operations, now),
    ),
    'withdrawal': Reducer(
        'withdrawal',
        FollowUpContactWithdrawalRejected,
        INTERRUPTED_AT + timedelta(minutes=1),
        lambda s, now: reduce_follow_up_contact_withdrawal(
            s.claim, s.session, s.follow_up, s.operations, now
        ),
    ),
    'expiry': Reducer(
        'expiry',
        FollowUpExpiryExecutionRejected,
        DEADLINE_AT,
        lambda s, now: reduce_expired_follow_up(s.claim, s.session, s.follow_up, s.operations, now),
    ),
    'abandonment': Reducer(
        'abandonment',
        FollowUpStaffAbandonmentRejected,
        INTERRUPTED_AT + timedelta(minutes=1),
        lambda s, now: reduce_follow_up_staff_abandonment(
            s.claim, s.session, s.follow_up, s.operations, now, STAFF
        ),
    ),
}

DUE_ONLY: list[tuple[str, Mutation, str]] = [
    (
        'reserved-operation',
        lambda s: replace(
            s,
            operations=[
                _scheduled_operation(s).model_copy(
                    update={'status': FollowUpOperationStatus.SCHEDULED, 'committed_at': None}
                )
            ],
        ),
        'already requires reconciliation',
    ),
    (
        'blocked-obligation',
        lambda s: _with(s, 'follow_up', status=FollowUpStatus.BLOCKED),
        'Only a pending Follow-up',
    ),
    (
        'contact-not-authorised',
        lambda s: _with(
            s, 'follow_up', contact_permission=FollowUpContactPermission.NOT_AUTHORISED
        ),
        'not authorised',
    ),
    (
        'email-channel',
        lambda s: _with(s, 'follow_up', channel=PreferredChannel.EMAIL),
        'not authorised',
    ),
    (
        'missing-due-time',
        lambda s: _with(s, 'follow_up', due_at=None),
        'both due and deadline',
    ),
    (
        'off-cadence-due-time',
        lambda s: _with(s, 'follow_up', due_at=INTERRUPTED_AT - timedelta(minutes=1)),
        'immutable v1 cadence',
    ),
]

# Lifecycle guards apply to the reducers whose transition they would corrupt.
LIFECYCLE: list[tuple[tuple[str, Mutation, str], tuple[str, ...]]] = [
    (ACTIVE_SESSION, ('due', 'expiry', 'abandonment')),
    (CLOSED_OBLIGATION, ('withdrawal', 'expiry', 'abandonment')),
    (TWO_OPEN, ('withdrawal', 'expiry', 'abandonment')),
]


def test_every_reducer_accepts_the_unmodified_snapshot() -> None:
    for reducer in REDUCERS.values():
        assert reducer.run(_snapshot(), reducer.valid_now) is not None


@pytest.mark.parametrize(('case', 'mutate', 'reason'), COMMON, ids=[case for case, _, _ in COMMON])
def test_every_reducer_refuses_a_corrupted_shared_fact(
    case: str,
    mutate: Mutation,
    reason: str,
) -> None:
    """Ownership, Session, policy and history facts fail closed in all four reducers."""

    for reducer in REDUCERS.values():
        with pytest.raises(reducer.rejected, match=reason):
            reducer.run(mutate(_snapshot()), reducer.valid_now)


@pytest.mark.parametrize(
    ('guard', 'reducer_names'), LIFECYCLE, ids=[guard[0] for guard, _ in LIFECYCLE]
)
def test_lifecycle_state_blocks_the_transitions_it_would_corrupt(
    guard: tuple[str, Mutation, str],
    reducer_names: tuple[str, ...],
) -> None:
    _, mutate, reason = guard
    for name in reducer_names:
        reducer = REDUCERS[name]
        with pytest.raises(reducer.rejected, match=reason):
            reducer.run(mutate(_snapshot()), reducer.valid_now)


@pytest.mark.parametrize(
    ('case', 'mutate', 'reason'), DUE_ONLY, ids=[case for case, _, _ in DUE_ONLY]
)
def test_due_contact_requires_authorised_in_app_cadence(
    case: str,
    mutate: Mutation,
    reason: str,
) -> None:
    reducer = REDUCERS['due']

    with pytest.raises(reducer.rejected, match=reason):
        reducer.run(mutate(_snapshot()), reducer.valid_now)


def test_contact_withdrawal_is_refused_once_contact_is_already_withdrawn() -> None:
    snapshot = _with(
        _snapshot(), 'follow_up', contact_permission=FollowUpContactPermission.NOT_AUTHORISED
    )
    reducer = REDUCERS['withdrawal']

    with pytest.raises(reducer.rejected, match='already not authorised'):
        reducer.run(snapshot, reducer.valid_now)


@pytest.mark.parametrize('reducer_name', list(REDUCERS))
def test_reducer_refuses_naive_execution_time(reducer_name: str) -> None:
    reducer = REDUCERS[reducer_name]

    with pytest.raises(reducer.rejected, match='timezone-aware'):
        reducer.run(_snapshot(), reducer.valid_now.replace(tzinfo=None))


@pytest.mark.parametrize(
    ('reducer_name', 'now', 'reason'),
    [
        ('due', INTERRUPTED_AT - timedelta(seconds=1), 'not due yet'),
        ('due', DEADLINE_AT, 'precedence'),
        ('withdrawal', DEADLINE_AT, 'precedence'),
        ('expiry', DEADLINE_AT - timedelta(seconds=1), 'not been reached'),
        ('abandonment', DEADLINE_AT, 'precedence'),
    ],
)
def test_reducer_enforces_the_deadline_boundary(
    reducer_name: str,
    now: datetime,
    reason: str,
) -> None:
    reducer = REDUCERS[reducer_name]

    with pytest.raises(reducer.rejected, match=reason):
        reducer.run(_snapshot(), now)


def test_staff_abandonment_requires_a_staff_actor() -> None:
    snapshot = _snapshot()

    with pytest.raises(FollowUpStaffAbandonmentRejected, match='staff actor'):
        reduce_follow_up_staff_abandonment(
            snapshot.claim,
            snapshot.session,
            snapshot.follow_up,
            snapshot.operations,
            INTERRUPTED_AT + timedelta(minutes=1),
            ActorReference(actor_type=ActorType.SYSTEM, actor_id='p17'),
        )


def test_due_attempt_refuses_two_unsettled_committed_deliveries() -> None:
    snapshot = _two_open_operations(_snapshot())
    due_at = INTERRUPTED_AT + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL * 2
    snapshot = _with(snapshot, 'follow_up', due_at=due_at)

    with pytest.raises(FollowUpDueExecutionRejected, match='awaiting settlement'):
        reduce_due_follow_up(
            snapshot.claim,
            snapshot.session,
            snapshot.follow_up,
            snapshot.operations,
            due_at,
        )


def _committed_payload() -> dict[str, Any]:
    operation = _scheduled_operation(_snapshot())
    assert operation.status is FollowUpOperationStatus.COMMITTED
    return operation.model_dump(mode='python')


LATER = INTERRUPTED_AT + timedelta(hours=1)
EARLIER = INTERRUPTED_AT - timedelta(hours=1)


@pytest.mark.parametrize(
    ('update', 'reason'),
    [
        ({'committed_at': INTERRUPTED_AT.replace(tzinfo=None)}, 'timezone-aware'),
        ({'source_refs': ['follow-up:fup_guard', 'follow-up:fup_guard']}, 'must be unique'),
        ({'committed_at': EARLIER}, 'commit cannot precede its schedule'),
        ({'committed_at': None, 'settled_at': LATER}, 'settlement requires a prior commit'),
        ({'cancelled_at': EARLIER}, 'cancellation cannot precede its schedule'),
        ({'status': FollowUpOperationStatus.SCHEDULED}, 'cannot carry execution evidence'),
        (
            {'result_code': FollowUpOperationResult.NO_RESPONSE},
            'may only record in-app delivery',
        ),
        (
            {'status': FollowUpOperationStatus.SETTLED, 'settled_at': LATER, 'result_code': None},
            'requires commit, settlement and result',
        ),
        (
            {'result': 'delivered_in_app', 'result_code': FollowUpOperationResult.NO_RESPONSE},
            'Conflicting Follow-up operation result',
        ),
    ],
    ids=lambda value: str(value)[:40] if isinstance(value, dict) else value,
)
def test_follow_up_operation_rejects_inconsistent_evidence(
    update: dict[str, Any],
    reason: str,
) -> None:
    payload = _committed_payload()
    payload.update(update)

    with pytest.raises(ValidationError, match=reason):
        FollowUpOperation.model_validate(payload)
