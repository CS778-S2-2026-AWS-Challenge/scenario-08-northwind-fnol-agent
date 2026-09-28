from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from pymongo.collection import Collection

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpOperation,
    FollowUpOperationStatus,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    RetentionOperation,
    RetentionOperationStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict
from scripts.backfill_follow_up_policy import backfill_follow_ups


def _follow_up() -> FollowUpRecord:
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    return FollowUpRecord(
        follow_up_id='fup_operation_test',
        claim_id='clm_operation_test',
        source_session_id='ses_operation_test',
        responsible_party=ResponsibleParty.SYSTEM,
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        deadline_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
    )


def _operation(
    status: FollowUpOperationStatus = FollowUpOperationStatus.RESERVED,
) -> FollowUpOperation:
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    return FollowUpOperation(
        operation_id='fop_0123456789abcdef0123',
        follow_up_id='fup_operation_test',
        claim_id='clm_operation_test',
        sequence=1,
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        based_on_claim_revision=2,
        scheduled_at=now,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_fixture_operation_identity_and_sequence_are_idempotent() -> None:
    repository = FixtureRepository()
    follow_up = _follow_up()
    repository._follow_ups[follow_up.follow_up_id] = follow_up
    operation = _operation()

    repository.save_follow_up_operation(operation)
    repository.save_follow_up_operation(operation)
    assert repository.get_follow_up_operation(operation.operation_id) == operation

    conflicting = operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'})
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(conflicting)


def test_fixture_due_and_deadline_queries_are_bounded_and_ordered() -> None:
    repository = FixtureRepository()
    first = _follow_up()
    assert first.due_at is not None
    assert first.deadline_at is not None
    second = first.model_copy(
        update={
            'follow_up_id': 'fup_operation_test_2',
            'due_at': first.due_at + timedelta(hours=1),
            'deadline_at': first.deadline_at + timedelta(hours=1),
        }
    )
    repository._follow_ups[first.follow_up_id] = first
    repository._follow_ups[second.follow_up_id] = second
    assert second.deadline_at is not None

    due = repository.list_due_follow_ups(first.due_at, limit=10)
    assert [item.follow_up_id for item in due] == [first.follow_up_id]
    expiring = repository.list_expiring_follow_ups(second.deadline_at, limit=1)
    assert [item.follow_up_id for item in expiring] == [first.follow_up_id]
    page_two = repository.list_expiring_follow_ups(
        second.deadline_at,
        limit=10,
        cursor=(first.deadline_at, first.follow_up_id),
    )
    assert [item.follow_up_id for item in page_two] == [second.follow_up_id]


def test_follow_up_policy_backfill_is_read_only_until_apply() -> None:
    collection: Collection[dict[str, Any]] = mongomock.MongoClient().db.records
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    collection.insert_many(
        [
            {
                '_id': 'session:ses_migration',
                'record_type': 'session',
                'session_id': 'ses_migration',
                'claim_id': 'clm_migration',
                'recovery_context': {'interrupted_at': now.isoformat()},
            },
            {
                '_id': 'follow_up:fup_migration',
                'record_type': 'follow_up',
                'follow_up_id': 'fup_migration',
                'claim_id': 'clm_migration',
                'source_session_id': 'ses_migration',
                'status': 'blocked',
                'contact_permission': 'not_authorised',
            },
        ]
    )
    dry_run = backfill_follow_ups(collection)
    assert dry_run['eligible'] == ['fup_migration']
    stored_before = collection.find_one({'_id': 'follow_up:fup_migration'})
    assert stored_before is not None
    assert 'deadline_at' not in stored_before
    applied = backfill_follow_ups(collection, apply=True)
    assert applied['applied'] == ['fup_migration']
    stored = collection.find_one({'_id': 'follow_up:fup_migration'})
    assert stored is not None
    assert stored['policy_id'] == 'incomplete_claim_follow_up'
    assert stored['deadline_at'] == (now + timedelta(days=7)).isoformat()
    assert stored['blocked_reason'] == 'contact_not_authorised'


def test_mongo_due_deadline_and_operation_contracts() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'recovery_test')
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    follow_up = _follow_up()
    repository._collection.insert_one(
        {
            **follow_up.model_dump(mode='json'),
            '_id': 'follow_up:fup_operation_test',
            'record_type': 'follow_up',
            'claim_id': follow_up.claim_id,
            'customer_id': 'cus_operation_test',
        }
    )
    assert repository.list_due_follow_ups(now, limit=10)[0].follow_up_id == follow_up.follow_up_id
    assert (
        repository.list_expiring_follow_ups(now + timedelta(days=7), limit=10)[0].follow_up_id
        == follow_up.follow_up_id
    )
    operation = _operation()
    repository.save_follow_up_operation(operation)
    repository.save_follow_up_operation(operation)
    assert repository.list_follow_up_operations(follow_up.follow_up_id) == [operation]
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'})
        )


def test_mongo_retention_operation_is_replay_safe() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'retention_test')
    follow_up = _follow_up()
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id=follow_up.claim_id,
        customer_id='cus_operation_test',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )
    repository._collection.insert_one(
        {
            **claim.model_dump(mode='json'),
            '_id': f'claim:{claim.claim_id}',
            'record_type': 'claim',
        }
    )
    operation = RetentionOperation(
        operation_id='rop_0123456789abcdef0123',
        claim_id=claim.claim_id,
        target_refs=['claim:clm_operation_test'],
        status=RetentionOperationStatus.ELIGIBLE,
        created_at=now,
        updated_at=now,
    )
    repository.save_retention_operation(operation)
    repository.save_retention_operation(operation)
    assert repository.get_retention_operation(operation.operation_id) == operation
