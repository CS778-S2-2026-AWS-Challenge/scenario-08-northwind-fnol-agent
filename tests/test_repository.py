from datetime import UTC, datetime

import pytest

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.key_layout import (
    claim_key,
    customer_claim_index_key,
    evidence_key,
    message_key,
    session_key,
)
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


def test_fixture_repository_supports_customer_message_and_evidence_access_patterns() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()
    repository.create_claim(claim, session)
    message = MessageRecord(
        message_id='msg_fixture',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor='claimant',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'A synthetic report.'},
        created_at=claim.created_at,
    )
    evidence = EvidenceRecord(
        evidence_id='evd_fixture',
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
    repository.save_message(message, 'cus_fixture')
    repository.save_evidence(evidence, 'cus_fixture')

    assert [item.claim_id for item in repository.list_claims_for_customer('cus_fixture')] == [
        claim.claim_id
    ]
    assert repository.list_messages(claim.claim_id, session.session_id, 'cus_fixture') == [message]
    assert repository.list_messages(claim.claim_id, session.session_id, 'other_customer') == []
    assert repository.get_evidence(claim.claim_id, evidence.evidence_id, 'cus_fixture') == evidence
    assert repository.list_evidence(claim.claim_id, 'other_customer') == []
    with pytest.raises(KeyError):
        repository.save_message(message, 'other_customer')
    with pytest.raises(KeyError):
        repository.save_evidence(evidence, 'other_customer')


def test_logical_key_layout_keeps_provider_keys_outside_api_models() -> None:
    assert claim_key('clm_1').partition == 'CLAIM#clm_1'
    assert claim_key('clm_1').sort == 'CLAIM'
    assert session_key('clm_1', 'ses_1').sort == 'SESSION#ses_1'
    assert message_key('clm_1', '2026-08-11T00:00:00Z', 'msg_1').sort.startswith('MESSAGE#')
    assert evidence_key('clm_1', 'evd_1').sort == 'EVIDENCE#evd_1'
    assert customer_claim_index_key('cus_1', '2026-08-11T00:00:00Z', 'clm_1').partition == (
        'CUSTOMER#cus_1'
    )
