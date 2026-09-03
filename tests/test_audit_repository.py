from datetime import UTC, datetime, timedelta
from typing import Any

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
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord
from backend.services.branching import build_applied_branch_evaluation


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
    client: Any = mongomock.MongoClient()
    repository = MongoDBRepository(client, 'northwind_audit_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


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


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_claim_mutation_persists_audit_and_branch_evaluation_together(
    repository_kind: str,
) -> None:
    repository = FixtureRepository() if repository_kind == 'fixture' else _mongodb_repository()
    timestamp = datetime(2026, 9, 3, 5, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id=f'clm_audit_atomic_{repository_kind}',
        customer_id=f'cus_audit_atomic_{repository_kind}',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        active_session_id=f'ses_audit_atomic_{repository_kind}',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)

    updated = claim.model_copy(
        update={
            'revision': 2,
            'updated_at': timestamp + timedelta(seconds=1),
        }
    )
    event = _audit_event(
        f'aud_atomic_{repository_kind}',
        timestamp + timedelta(seconds=1),
        claim_id=claim.claim_id,
    ).model_copy(update={'claim_revision': updated.revision})
    evaluation = build_applied_branch_evaluation(
        updated,
        repository=repository,
        recomputation_reason='audit_atomic_test',
        created_at=timestamp + timedelta(seconds=1),
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/audit-atomic-test',
        key=f'audit-atomic-{repository_kind}',
        request_fingerprint=f'fingerprint-{repository_kind}',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )

    repository.save_claim_mutation_with_audit(
        updated,
        expected_revision=1,
        idempotency=idempotency,
        audit_events=(event,),
        branch_evaluation=evaluation,
    )

    assert repository.get_claim_internal(claim.claim_id) == updated
    assert repository.list_audit_events_internal(event.subject) == [event]
    evaluations = repository.list_branch_evaluations(claim.claim_id, claim.customer_id)
    assert evaluations == [evaluation]
    assert (
        repository.find_idempotency(
            claim.customer_id,
            '/audit-atomic-test',
            f'audit-atomic-{repository_kind}',
        )
        == idempotency
    )


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_audit_conflict_rejects_claim_bundle_before_any_state_change(
    repository_kind: str,
) -> None:
    repository = FixtureRepository() if repository_kind == 'fixture' else _mongodb_repository()
    timestamp = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id=f'clm_audit_conflict_{repository_kind}',
        customer_id=f'cus_audit_conflict_{repository_kind}',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        active_session_id=f'ses_audit_conflict_{repository_kind}',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)

    updated = claim.model_copy(
        update={
            'revision': 2,
            'updated_at': timestamp + timedelta(seconds=1),
        }
    )
    stored_event = _audit_event(
        f'aud_conflict_{repository_kind}',
        timestamp,
        claim_id=claim.claim_id,
    ).model_copy(update={'claim_revision': updated.revision})
    repository.append_audit_event(stored_event)
    conflicting_event = stored_event.model_copy(
        update={'reason': 'Conflicting rewrite must reject the whole claim bundle.'}
    )
    evaluation = build_applied_branch_evaluation(
        updated,
        repository=repository,
        recomputation_reason='audit_conflict_test',
        created_at=timestamp + timedelta(seconds=1),
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/audit-conflict-test',
        key=f'audit-conflict-{repository_kind}',
        request_fingerprint=f'fingerprint-conflict-{repository_kind}',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_claim_mutation_with_audit(
            updated,
            expected_revision=1,
            idempotency=idempotency,
            audit_events=(conflicting_event,),
            branch_evaluation=evaluation,
        )

    assert repository.get_claim_internal(claim.claim_id) == claim
    assert repository.list_audit_events_internal(stored_event.subject) == [stored_event]
    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            claim.customer_id,
            '/audit-conflict-test',
            f'audit-conflict-{repository_kind}',
        )
        is None
    )
