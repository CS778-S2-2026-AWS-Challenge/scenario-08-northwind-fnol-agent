from datetime import UTC, datetime

import pytest

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord, RevisionConflict


def make_claim() -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_fixture',
        customer_id='cus_fixture',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_fixture',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    return claim, session


def test_fixture_repository_enforces_ownership_and_revision() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()
    repository.create_claim(claim, session)

    assert repository.get_claim(claim.claim_id, 'other_customer') is None
    stored = repository.get_claim(claim.claim_id, claim.customer_id)
    assert stored is not None
    stored.revision = 2

    with pytest.raises(RevisionConflict) as error:
        repository.save_claim(stored, expected_revision=0)

    assert error.value.current_revision == 1


def test_fixture_repository_handles_missing_records_and_idempotency_conflicts() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()

    assert repository.claim_count == 0
    assert repository.get_session(claim.claim_id, session.session_id, claim.customer_id) is None
    assert repository.get_active_session(claim.claim_id, claim.customer_id) is None
    with pytest.raises(KeyError):
        repository.save_claim(claim, expected_revision=1)

    repository.create_claim(claim, session)
    assert repository.get_active_session(claim.claim_id, claim.customer_id) is None
    record = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims',
        key='same-key',
        request_fingerprint='first',
        claim_id=claim.claim_id,
        session_id=session.session_id,
    )
    repository.save_idempotency(record)
    conflicting_record = IdempotencyRecord(
        actor_id=record.actor_id,
        route=record.route,
        key=record.key,
        request_fingerprint='second',
        claim_id=record.claim_id,
        session_id=record.session_id,
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_idempotency(conflicting_record)
