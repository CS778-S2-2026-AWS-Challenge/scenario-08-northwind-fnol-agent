from datetime import UTC, datetime

import mongomock
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
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 26, 1, 30, tzinfo=UTC)


def _repository() -> tuple[MongoDBRepository, WorkingClaim, SessionRecord, SessionRecord]:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_session_boundary')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    claim = WorkingClaim(
        claim_id='clm_mongo_session_boundary',
        customer_id='cus_mongo_session_boundary',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_mongo_authoritative',
        customer_next_step=CustomerNextStep(
            status='continue_intake',
            summary='Continue the claim intake.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    authoritative_session = SessionRecord(
        session_id='ses_mongo_authoritative',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=1,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
        status=SessionStatus.ACTIVE,
    )
    alternate_session = authoritative_session.model_copy(
        update={'session_id': 'ses_mongo_alternate'}
    )
    repository.create_claim(claim, authoritative_session)
    repository.save_session(alternate_session)
    return repository, claim, authoritative_session, alternate_session


def _message(claim: WorkingClaim, session: SessionRecord) -> MessageRecord:
    return MessageRecord(
        message_id='msg_mongo_session_switch',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id='client-msg-mongo-session-switch',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Continue on the alternate session.'},
        created_at=FIXED_TIME,
    )


def test_mongodb_claimant_message_cannot_switch_authoritative_active_session() -> None:
    repository, claim, authoritative_session, alternate_session = _repository()
    incoming_claim = claim.model_copy(
        update={'revision': 2, 'active_session_id': alternate_session.session_id}
    )
    incoming_session = alternate_session.model_copy(update={'context_revision': 2})
    message = _message(claim, alternate_session)
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/messages',
        key='mongo-message-session-switch',
        request_fingerprint='mongo-message-session-switch-fingerprint',
        claim_id=claim.claim_id,
        session_id=alternate_session.session_id,
        message_id=message.message_id,
    )

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
    assert (
        repository.get_message(
            claim.claim_id,
            alternate_session.session_id,
            message.message_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_mongodb_evidence_mutation_cannot_switch_authoritative_active_session() -> None:
    repository, claim, _, alternate_session = _repository()
    incoming_claim = claim.model_copy(
        update={'revision': 2, 'active_session_id': alternate_session.session_id}
    )
    evidence = EvidenceRecord(
        evidence_id='evd_mongo_session_switch',
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
        route='/evidence',
        key='mongo-evidence-session-switch',
        request_fingerprint='mongo-evidence-session-switch-fingerprint',
        claim_id=claim.claim_id,
        session_id=alternate_session.session_id,
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
        repository.get_evidence(
            claim.claim_id,
            evidence.evidence_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )
