from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, RevisionConflict


def _claim(revision: int = 1) -> WorkingClaim:
    timestamp = datetime(2026, 8, 21, tzinfo=UTC)
    return WorkingClaim(
        claim_id='clm_mongo_001',
        customer_id='cus_mongo_001',
        revision=revision,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_mongo_001',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _session(claim: WorkingClaim) -> SessionRecord:
    timestamp = claim.created_at
    return SessionRecord(
        session_id='ses_mongo_001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )


@pytest.fixture
def repository() -> MongoDBRepository:
    return MongoDBRepository(mongomock.MongoClient(), 'northwind_test')


def test_claim_and_session_round_trip_enforces_customer_ownership(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.get_claim(claim.claim_id, 'another-customer') is None
    assert repository.get_session(claim.claim_id, session.session_id, claim.customer_id) == session
    assert repository.list_claims_for_customer(claim.customer_id) == [claim]
    assert repository.list_sessions_for_claim(claim.claim_id, claim.customer_id) == [session]


def test_claim_save_uses_optimistic_revision(repository: MongoDBRepository) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    updated = claim.model_copy(update={'revision': 2})

    repository.save_claim(updated, expected_revision=1)
    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated

    with pytest.raises(RevisionConflict) as error:
        repository.save_claim(updated.model_copy(update={'revision': 3}), expected_revision=1)
    assert error.value.current_revision == 2


def test_idempotency_rejects_changed_replay(repository: MongoDBRepository) -> None:
    from backend.repositories.protocols import IdempotencyRecord

    record = IdempotencyRecord(
        actor_id='cus_mongo_001',
        route='/api/v1/claims',
        key='same-key',
        request_fingerprint='fingerprint-a',
        claim_id='clm_mongo_001',
        session_id='ses_mongo_001',
    )
    repository.save_idempotency(record)
    assert repository.find_idempotency(record.actor_id, record.route, record.key) == record

    repository.save_idempotency(record)
    with pytest.raises(IdempotencyConflict):
        repository.save_idempotency(
            record.__class__(**{**record.__dict__, 'request_fingerprint': 'fingerprint-b'})
        )


def test_session_mutation_rejects_cross_record_relationships_before_transaction(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    session = _session(claim).model_copy(update={'customer_id': 'another-customer'})
    from backend.repositories.protocols import IdempotencyRecord

    with pytest.raises(KeyError):
        repository.save_session_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            session=session,
            idempotency=IdempotencyRecord(
                actor_id=claim.customer_id,
                route='/sessions',
                key='session-key',
                request_fingerprint='fingerprint',
                claim_id=claim.claim_id,
                session_id=session.session_id,
            ),
        )


def test_session_identity_cannot_be_overwritten_by_another_claim(
    repository: MongoDBRepository,
) -> None:
    first_claim = _claim()
    repository.create_claim(first_claim, _session(first_claim))
    assert first_claim.active_session_id is not None
    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'active_session_id': first_claim.active_session_id,
        }
    )
    second_session = _session(second_claim)

    with pytest.raises(IdempotencyConflict):
        repository.create_claim(second_claim, second_session)

    stored = repository._collection.find_one(
        {'_id': repository._record_id('session', first_claim.active_session_id)}
    )
    assert stored is not None
    assert stored['claim_id'] == first_claim.claim_id
    assert stored['customer_id'] == first_claim.customer_id


def test_save_session_rejects_existing_session_for_another_customer(
    repository: MongoDBRepository,
) -> None:
    first_claim = _claim()
    repository.create_claim(first_claim, _session(first_claim))
    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'active_session_id': 'ses_mongo_002',
            'customer_id': 'another-customer',
        }
    )
    second_session = _session(second_claim).model_copy(update={'session_id': 'ses_mongo_002'})
    repository.create_claim(second_claim, second_session)
    conflicting = second_session.model_copy(update={'session_id': first_claim.active_session_id})

    with pytest.raises(IdempotencyConflict):
        repository.save_session(conflicting)
