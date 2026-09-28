from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    ClaimState,
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
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
)


def _repository(kind: str):
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        'follow_up_operation_test',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_recovery(repository):
    now = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)

    claim = WorkingClaim(
        claim_id='clm_follow_up_operation',
        customer_id='cus_follow_up_operation',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(),
        active_session_id='ses_follow_up_operation',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )

    session = SessionRecord(
        session_id='ses_follow_up_operation',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=now,
        last_active_at=now,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=now,
        last_meaningful_activity_at=now,
        last_meaningful_activity_source_ref=(
            f'claim:{claim.claim_id}:revision:{claim.revision}'
        ),
        resume_point='Continue describing the incident.',
    )

    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'recovery_context': recovery,
        }
    )

    paused_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': None,
            'updated_at': now,
        }
    )

    follow_up = FollowUpRecord(
        follow_up_id='fup_follow_up_operation',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        policy_id='incomplete_claim_follow_up',
        policy_version='v1',
        deadline_at=now + timedelta(days=7),
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[f'session:{session.session_id}'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        created_at=now,
        updated_at=now,
    )

    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/test/follow-up-operation/pause',
        key='follow-up-operation-pause',
        request_fingerprint='follow-up-operation-pause',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        follow_up_id=follow_up.follow_up_id,
    )

    repository.save_incomplete_checkpoint(
        paused_claim,
        expected_revision=1,
        session=paused_session,
        follow_up=follow_up,
        idempotency=idempotency,
    )

    return paused_claim, follow_up, now


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_operation_lifecycle_identity_and_owner_parity(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, now = _seed_recovery(repository)

    scheduled = FollowUpOperation(
        operation_id='fop_1',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=1,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=1),
        source_refs=[
            f'follow-up:{follow_up.follow_up_id}',
            f'claim:{claim.claim_id}:revision:{claim.revision}',
        ],
    )

    repository.save_follow_up_operation(
        scheduled,
        claim.customer_id,
    )

    repository.save_follow_up_operation(
        scheduled,
        claim.customer_id,
    )

    committed_at = now + timedelta(hours=1, minutes=1)

    committed = scheduled.model_copy(
        update={
            'status': FollowUpOperationStatus.COMMITTED,
            'result': FollowUpOperationResult.DELIVERED_IN_APP,
            'committed_at': committed_at,
        }
    )

    repository.save_follow_up_operation(
        committed,
        claim.customer_id,
    )

    settled = committed.model_copy(
        update={
            'status': FollowUpOperationStatus.SETTLED,
            'result': FollowUpOperationResult.NO_RESPONSE,
            'settled_at': committed_at + timedelta(minutes=1),
        }
    )

    repository.save_follow_up_operation(
        settled,
        claim.customer_id,
    )

    assert repository.get_follow_up_operation(
        claim.claim_id,
        scheduled.operation_id,
        claim.customer_id,
    ) == settled

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    ) == [settled]

    assert repository.get_follow_up_operation(
        claim.claim_id,
        scheduled.operation_id,
        'cus_other',
    ) is None

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        'cus_other',
    ) == []

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            scheduled,
            claim.customer_id,
        )


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_operation_sequence_policy_revision_and_deadline_parity(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, now = _seed_recovery(repository)

    first = FollowUpOperation(
        operation_id='fop_first',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=1,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=1),
    )

    repository.save_follow_up_operation(
        first,
        claim.customer_id,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            first.model_copy(
                update={
                    'operation_id': 'fop_duplicate_sequence',
                }
            ),
            claim.customer_id,
        )

    with pytest.raises(KeyError):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_wrong_policy',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version='wrong-version',
                based_on_claim_revision=claim.revision,
                scheduled_at=now + timedelta(hours=2),
            ),
            claim.customer_id,
        )

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_wrong_revision',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version=follow_up.policy_version,
                based_on_claim_revision=claim.revision - 1,
                scheduled_at=now + timedelta(hours=2),
            ),
            claim.customer_id,
        )

    with pytest.raises(KeyError):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_deadline_tie',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version=follow_up.policy_version,
                based_on_claim_revision=claim.revision,
                scheduled_at=follow_up.deadline_at,
            ),
            claim.customer_id,
        )

    second = FollowUpOperation(
        operation_id='fop_second',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=2,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=2),
    )

    repository.save_follow_up_operation(
        second,
        claim.customer_id,
    )

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    ) == [first, second]
