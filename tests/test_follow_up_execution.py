from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditSubject,
    AuditSubjectType,
)
from backend.domain.follow_up_execution import reduce_due_follow_up
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpOperationResult,
    FollowUpOperationStatus,
    FollowUpReasonCode,
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
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord, PersistenceRepository
from backend.services.follow_up_recovery import (
    process_due_follow_up,
    process_expiring_follow_up,
    process_follow_up_contact_withdrawal,
)


def _repository(kind: str) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'p17_execution_{kind}',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _checkpoint(
    repository: PersistenceRepository,
) -> tuple[WorkingClaim, SessionRecord, FollowUpRecord, datetime]:
    interrupted_at = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)

    claim = WorkingClaim(
        claim_id='clm_p17_execution',
        customer_id='cus_p17_execution',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_p17_execution',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=interrupted_at,
        updated_at=interrupted_at,
    )
    session = SessionRecord(
        session_id='ses_p17_execution',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=interrupted_at,
        last_active_at=interrupted_at,
    )
    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=interrupted_at,
        last_meaningful_activity_at=interrupted_at,
        last_meaningful_activity_source_ref=(
            f'claim:{claim.claim_id}:revision:{claim.revision}'
        ),
        resume_point='Continue describing the incident.',
    )

    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'context_revision': claim.revision,
            'recovery_context': recovery,
        }
    )
    paused_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'active_session_id': None,
            'updated_at': interrupted_at,
        }
    )

    follow_up = FollowUpRecord(
        follow_up_id='fup_p17_execution',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        policy_id='incomplete_claim_follow_up',
        policy_version='v1',
        deadline_at=(
            interrupted_at
            + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
        ),
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[
            f'claim:{claim.claim_id}:revision:{paused_claim.revision}',
            f'session:{session.session_id}',
        ],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        attempt_count=0,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=interrupted_at,
        created_at=interrupted_at,
        updated_at=interrupted_at,
    )

    repository.save_incomplete_checkpoint(
        paused_claim,
        expected_revision=claim.revision,
        session=paused_session,
        follow_up=follow_up,
        idempotency=IdempotencyRecord(
            actor_id=claim.customer_id,
            route=(
                f'/api/v1/claims/{claim.claim_id}/'
                f'sessions/{session.session_id}/pause'
            ),
            key='p17-execution-pause',
            request_fingerprint='p17-execution-pause-fingerprint',
            claim_id=claim.claim_id,
            session_id=session.session_id,
            follow_up_id=follow_up.follow_up_id,
        ),
    )

    return paused_claim, paused_session, follow_up, interrupted_at


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_due_attempts_reschedule_settle_no_response_and_exhaust(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    first = process_due_follow_up(
        repository,
        follow_up,
        interrupted_at,
    )
    assert first is not None
    assert first.operation.sequence == 1
    assert first.operation.status is FollowUpOperationStatus.COMMITTED
    assert first.operation.result is FollowUpOperationResult.DELIVERED_IN_APP

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.attempt_count == 1
    assert stored.status is FollowUpStatus.PENDING
    assert stored.reason_code is None
    assert stored.due_at == interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL

    second_at = interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL
    second = process_due_follow_up(
        repository,
        stored,
        second_at,
    )
    assert second is not None
    assert second.operation.sequence == 2
    assert second.settled_previous_operation is not None
    assert (
        second.settled_previous_operation.status
        is FollowUpOperationStatus.SETTLED
    )
    assert (
        second.settled_previous_operation.result
        is FollowUpOperationResult.NO_RESPONSE
    )

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.attempt_count == 2
    assert stored.status is FollowUpStatus.PENDING
    assert stored.due_at == (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL * 2
    )

    third_at = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL * 2
    )
    third = process_due_follow_up(
        repository,
        stored,
        third_at,
    )
    assert third is not None
    assert third.operation.sequence == 3

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.attempt_count == 3
    assert stored.status is FollowUpStatus.BLOCKED
    assert stored.reason_code is FollowUpReasonCode.ATTEMPT_LIMIT_REACHED
    assert stored.due_at is None

    stored_claim = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored_claim is not None
    assert stored_claim.terminal_disposition is None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert [operation.sequence for operation in operations] == [1, 2, 3]
    assert operations[0].status is FollowUpOperationStatus.SETTLED
    assert operations[0].result is FollowUpOperationResult.NO_RESPONSE
    assert operations[1].status is FollowUpOperationStatus.SETTLED
    assert operations[1].result is FollowUpOperationResult.NO_RESPONSE
    assert operations[2].status is FollowUpOperationStatus.COMMITTED
    assert operations[2].result is FollowUpOperationResult.DELIVERED_IN_APP


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_deadline_tie_prevents_due_attempt_without_partial_write(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    transition = process_due_follow_up(
        repository,
        follow_up,
        interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE,
    )
    assert transition is None

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored == follow_up
    assert (
        repository.list_follow_up_operations(
            claim.claim_id,
            follow_up.follow_up_id,
            claim.customer_id,
        )
        == []
    )


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_due_attempt_exact_repository_replay_does_not_double_count(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, session, follow_up, interrupted_at = _checkpoint(repository)

    transition = reduce_due_follow_up(
        claim,
        session,
        follow_up,
        [],
        interrupted_at,
    )

    audit_event = AuditEventEnvelope(
        event_id=f'aud_test_due_{transition.operation.operation_id}',
        event_type='action.completed',
        outcome='succeeded',
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        ),
        actor=AuditActor(
            actor_type='system',
            actor_id='p17-repository-contract-test',
            auth_source='test',
        ),
        reason='Repository contract test committed one P17 due attempt.',
        source_refs=[
            *transition.operation.source_refs,
            transition.operation.operation_id,
        ],
        visibility='internal_only',
        correlation_id=transition.operation.operation_id,
        claim_revision=claim.revision,
        created_at=interrupted_at,
    )

    repository.commit_due_follow_up_attempt(
        follow_up,
        transition.follow_up,
        transition.operation,
        transition.settled_previous_operation,
        claim.customer_id,
        audit_event,
    )
    repository.commit_due_follow_up_attempt(
        follow_up,
        transition.follow_up,
        transition.operation,
        transition.settled_previous_operation,
        claim.customer_id,
        audit_event,
    )

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.attempt_count == 1

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert len(operations) == 1
    assert operations[0] == transition.operation



@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_expiry_terminalises_recovery_and_settles_committed_attempt(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    first = process_due_follow_up(
        repository,
        follow_up,
        interrupted_at,
    )
    assert first is not None

    current = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert current is not None

    expiry_at = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )
    expired = process_expiring_follow_up(
        repository,
        current,
        expiry_at,
    )
    assert expired is not None

    stored_claim = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored_claim is not None
    assert stored_claim.revision == claim.revision + 1
    assert stored_claim.terminal_disposition is not None
    assert (
        stored_claim.terminal_disposition.value
        is TerminalDispositionValue.ABANDONED
    )
    assert (
        stored_claim.terminal_disposition.reason_code
        is TerminalDispositionReasonCode.RECOVERY_EXPIRED
    )
    assert stored_claim.customer_next_step.can_resume is False

    stored_follow_up = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored_follow_up is not None
    assert stored_follow_up.status is FollowUpStatus.RESOLVED
    assert stored_follow_up.reason_code is FollowUpReasonCode.RECOVERY_EXPIRED
    assert stored_follow_up.due_at is None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert len(operations) == 1
    assert operations[0].status is FollowUpOperationStatus.SETTLED
    assert operations[0].result is FollowUpOperationResult.NO_RESPONSE


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_deadline_boundary_expiry_wins_over_due_attempt(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    deadline = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )

    due_result = process_due_follow_up(
        repository,
        follow_up,
        deadline,
    )
    assert due_result is None

    expired = process_expiring_follow_up(
        repository,
        follow_up,
        deadline,
    )
    assert expired is not None

    stored_claim = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored_claim is not None
    assert stored_claim.terminal_disposition is not None
    assert (
        stored_claim.terminal_disposition.reason_code
        is TerminalDispositionReasonCode.RECOVERY_EXPIRED
    )

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    ) == []


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_duplicate_expiry_worker_is_idempotent_by_authoritative_state(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    deadline = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )

    first = process_expiring_follow_up(
        repository,
        follow_up,
        deadline,
    )
    assert first is not None

    second = process_expiring_follow_up(
        repository,
        follow_up,
        deadline,
    )
    assert second is None

    stored_claim = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored_claim is not None
    assert stored_claim.revision == claim.revision + 1

    stored_follow_up = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored_follow_up is not None
    assert stored_follow_up.status is FollowUpStatus.RESOLVED


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_attempt_before_deadline_can_commit_then_expiry_wins_later(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    attempt_at = interrupted_at
    attempt = process_due_follow_up(
        repository,
        follow_up,
        attempt_at,
    )
    assert attempt is not None

    current = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert current is not None

    deadline = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )
    expired = process_expiring_follow_up(
        repository,
        current,
        deadline,
    )
    assert expired is not None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert len(operations) == 1
    assert operations[0].status is FollowUpOperationStatus.SETTLED
    assert operations[0].result is FollowUpOperationResult.NO_RESPONSE



@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_contact_withdrawal_blocks_contact_without_abandoning_claim(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    first = process_due_follow_up(
        repository,
        follow_up,
        interrupted_at,
    )
    assert first is not None

    current = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert current is not None

    withdrawn_at = interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL / 2

    withdrawn = process_follow_up_contact_withdrawal(
        repository,
        current,
        withdrawn_at,
    )
    assert withdrawn is not None

    stored = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.status is FollowUpStatus.BLOCKED
    assert (
        stored.reason_code
        is FollowUpReasonCode.CONTACT_NOT_AUTHORISED
    )
    assert (
        stored.contact_permission
        is FollowUpContactPermission.NOT_AUTHORISED
    )
    assert stored.channel is None
    assert stored.due_at is None
    assert stored.attempt_count == 1

    stored_claim = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored_claim is not None
    assert stored_claim.terminal_disposition is None

    operations = repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert len(operations) == 1
    assert operations[0].status is FollowUpOperationStatus.SETTLED
    assert (
        operations[0].result
        is FollowUpOperationResult.AUTHORITY_WITHDRAWN
    )


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_due_and_contact_withdrawal_append_recovery_audit(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    due = process_due_follow_up(
        repository,
        follow_up,
        interrupted_at,
    )
    assert due is not None

    current = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert current is not None

    withdrawn = process_follow_up_contact_withdrawal(
        repository,
        current,
        interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL / 2,
    )
    assert withdrawn is not None

    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )

    recovery_events = [
        event
        for event in events
        if event.actor.actor_id
        in {
            'p17-recovery-worker',
            'p17-contact-authority',
        }
    ]

    assert len(recovery_events) == 2
    assert recovery_events[0].event_type is AuditEventType.ACTION_COMPLETED
    assert recovery_events[1].event_type is AuditEventType.PERMISSION_REJECTED


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_expiry_appends_terminal_recovery_audit(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, _, follow_up, interrupted_at = _checkpoint(repository)

    deadline = (
        interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )

    result = process_expiring_follow_up(
        repository,
        follow_up,
        deadline,
    )
    assert result is not None

    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )

    expiry_events = [
        event
        for event in events
        if event.actor.actor_id == 'p17-recovery-expiry'
    ]

    assert len(expiry_events) == 1
    assert expiry_events[0].event_type is AuditEventType.ACTION_COMPLETED
    assert expiry_events[0].claim_revision == result.claim.revision
