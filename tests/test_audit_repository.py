from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict


def _audit_event(
    event_id: str,
    created_at: datetime,
    *,
    claim_id: str = 'clm_audit_001',
) -> AuditEventEnvelope:
    return AuditEventEnvelope(
        event_id=event_id,
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        ),
        actor=AuditActor(
            actor_type='staff',
            actor_id='staff_audit_001',
            auth_source='authenticated_session',
        ),
        reason='Completed the authorised claim action.',
        source_refs=['action_audit_001'],
        visibility=AuditVisibility.INTERNAL_ONLY,
        claim_revision=2,
        created_at=created_at,
    )


def _mongodb_repository() -> MongoDBRepository:
    client = mongomock.MongoClient()
    return MongoDBRepository(client, 'northwind_audit_test')


def test_fixture_audit_event_is_append_only_and_idempotent() -> None:
    repository = FixtureRepository()
    event = _audit_event(
        'aud_fixture_001',
        datetime(2026, 9, 3, 1, 0, tzinfo=UTC),
    )

    repository.append_audit_event(event)
    repository.append_audit_event(event)

    stored = repository.list_audit_events_internal(event.subject)
    assert stored == [event]

    conflicting = event.model_copy(update={'reason': 'Attempted to rewrite the immutable event.'})
    with pytest.raises(IdempotencyConflict):
        repository.append_audit_event(conflicting)

    assert repository.list_audit_events_internal(event.subject) == [event]


def test_fixture_audit_query_filters_subject_time_and_orders_stably() -> None:
    repository = FixtureRepository()
    started = datetime(2026, 9, 3, 2, 0, tzinfo=UTC)

    first = _audit_event('aud_fixture_002', started)
    second = _audit_event('aud_fixture_003', started + timedelta(minutes=5))
    other_claim = _audit_event(
        'aud_fixture_004',
        started + timedelta(minutes=2),
        claim_id='clm_audit_002',
    )

    repository.append_audit_event(second)
    repository.append_audit_event(other_claim)
    repository.append_audit_event(first)

    assert repository.list_audit_events_internal(first.subject) == [first, second]
    assert repository.list_audit_events_internal(
        first.subject,
        start_at=started + timedelta(minutes=1),
        end_at=started + timedelta(minutes=5),
    ) == [second]

    with pytest.raises(ValueError, match='start_at'):
        repository.list_audit_events_internal(
            first.subject,
            start_at=started + timedelta(minutes=5),
            end_at=started,
        )


def test_mongodb_audit_event_is_append_only_and_idempotent() -> None:
    repository = _mongodb_repository()
    event = _audit_event(
        'aud_mongo_001',
        datetime(2026, 9, 3, 3, 0, tzinfo=UTC),
    )

    repository.append_audit_event(event)
    repository.append_audit_event(event)

    stored = repository.list_audit_events_internal(event.subject)
    assert stored == [event]

    conflicting = event.model_copy(
        update={'reason': 'Attempted to rewrite the immutable MongoDB event.'}
    )
    with pytest.raises(IdempotencyConflict):
        repository.append_audit_event(conflicting)

    assert repository.list_audit_events_internal(event.subject) == [event]


def test_mongodb_audit_query_filters_subject_time_and_orders_stably() -> None:
    repository = _mongodb_repository()
    started = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)

    first = _audit_event('aud_mongo_002', started)
    second = _audit_event('aud_mongo_003', started + timedelta(minutes=5))
    other_claim = _audit_event(
        'aud_mongo_004',
        started + timedelta(minutes=2),
        claim_id='clm_audit_mongo_other',
    )

    repository.append_audit_event(second)
    repository.append_audit_event(other_claim)
    repository.append_audit_event(first)

    assert repository.list_audit_events_internal(first.subject) == [first, second]
    assert repository.list_audit_events_internal(
        first.subject,
        start_at=started + timedelta(minutes=1),
        end_at=started + timedelta(minutes=5),
    ) == [second]

    with pytest.raises(ValueError, match='start_at'):
        repository.list_audit_events_internal(
            first.subject,
            start_at=started + timedelta(minutes=5),
            end_at=started,
        )
