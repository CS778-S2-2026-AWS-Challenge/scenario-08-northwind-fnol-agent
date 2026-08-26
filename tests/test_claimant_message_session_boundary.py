from datetime import UTC, datetime

import pytest

from backend.domain.models import (
    ActorType,
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
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)


def _repository() -> tuple[FixtureRepository, WorkingClaim, SessionRecord]:
    repository = FixtureRepository()
    claim = WorkingClaim(
        claim_id='clm_claimant_message_session',
        customer_id='cus_claimant_message_session',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_authoritative',
        customer_next_step=CustomerNextStep(
            status='continue_intake',
            summary='Continue the claim intake.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_authoritative',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)
    return repository, claim, session


def _claimant_message(claim: WorkingClaim, session_id: str) -> MessageRecord:
    return MessageRecord(
        message_id='msg_claimant_non_authoritative_session',
        claim_id=claim.claim_id,
        session_id=session_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.SHARED,
        content={'text': 'Continue this claim on the other session.'},
        created_at=FIXED_TIME,
        client_message_id='client-msg-non-authoritative-session',
    )


def _idempotency(claim: WorkingClaim, session_id: str, message_id: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/messages',
        key='idem-claimant-non-authoritative-session',
        request_fingerprint='fingerprint-claimant-non-authoritative-session',
        claim_id=claim.claim_id,
        session_id=session_id,
        message_id=message_id,
    )


def test_claimant_message_cannot_switch_authoritative_active_session_without_partial_write(
) -> None:
    repository, claim, authoritative_session = _repository()
    alternate_session = SessionRecord(
        session_id='ses_alternate',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
        status=SessionStatus.ACTIVE,
    )
    repository.save_session(alternate_session)

    incoming_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': alternate_session.session_id,
        }
    )
    incoming_session = alternate_session.model_copy(update={'context_revision': 2})
    message = _claimant_message(claim, alternate_session.session_id)
    idempotency = _idempotency(claim, alternate_session.session_id, message.message_id)

    with pytest.raises(KeyError):
        repository.save_message_mutation(
            incoming_claim,
            expected_revision=1,
            session=incoming_session,
            message=message,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(
            claim.claim_id,
            authoritative_session.session_id,
            claim.customer_id,
        )
        == authoritative_session
    )
    assert (
        repository.get_session(
            claim.claim_id,
            alternate_session.session_id,
            claim.customer_id,
        )
        == alternate_session
    )
    assert repository.list_messages(
        claim.claim_id,
        alternate_session.session_id,
        claim.customer_id,
    ) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_evidence_mutation_cannot_switch_authoritative_active_session() -> None:
    repository, claim, authoritative_session = _repository()
    incoming_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': 'ses_unrelated',
        }
    )
    evidence = EvidenceRecord(
        evidence_id='evd_non_authoritative_session',
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/evidence',
        key='idem-evidence-non-authoritative-session',
        request_fingerprint='fingerprint-evidence-non-authoritative-session',
        claim_id=claim.claim_id,
        session_id='ses_unrelated',
    )

    with pytest.raises(KeyError):
        repository.save_evidence_mutation(
            incoming_claim,
            expected_revision=1,
            evidence=evidence,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(
            claim.claim_id,
            authoritative_session.session_id,
            claim.customer_id,
        )
        == authoritative_session
    )
    assert repository.list_evidence(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )
