from datetime import UTC, datetime

import pytest

from backend.domain.models import (
    ActorType,
    Channel,
    CustomerNextStep,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 26, 0, 30, tzinfo=UTC)


def _repository() -> tuple[FixtureRepository, WorkingClaim, SessionRecord]:
    repository = FixtureRepository()
    claim = WorkingClaim(
        claim_id='clm_staff_message_session',
        customer_id='cus_staff_message_session',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_staff_message_session',
        customer_next_step=CustomerNextStep(
            status='staff_review',
            summary='Northwind staff are reviewing the claim.',
            responsible_party=ResponsibleParty.NORTHWIND,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_staff_message_session',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    return repository, claim, session


def _message(claim: WorkingClaim, session_id: str, message_id: str) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        claim_id=claim.claim_id,
        session_id=session_id,
        actor=ActorType.STAFF,
        visibility=MessageVisibility.SHARED,
        content={'text': 'A staff update for the claimant.'},
        created_at=FIXED_TIME,
    )


def _idempotency(claim: WorkingClaim, session_id: str, message_id: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id='stf_demo',
        route=f'/api/v1/workbench/claims/{claim.claim_id}/messages',
        key=f'idem-{message_id}',
        request_fingerprint=f'fingerprint-{message_id}',
        claim_id=claim.claim_id,
        session_id=session_id,
        message_id=message_id,
    )


def _assert_no_message_side_effect(
    repository: FixtureRepository,
    claim: WorkingClaim,
    session_id: str,
    idempotency: IdempotencyRecord,
) -> None:
    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_messages(claim.claim_id, session_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_staff_message_rejects_nonexistent_incoming_active_session_without_partial_write() -> None:
    repository, claim, _ = _repository()
    missing_session_id = 'ses_does_not_exist'
    message = _message(claim, missing_session_id, 'msg_staff_missing_session')
    idempotency = _idempotency(claim, missing_session_id, message.message_id)

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(
                update={
                    'revision': 2,
                    'active_session_id': missing_session_id,
                }
            ),
            expected_revision=1,
            idempotency=idempotency,
            message=message,
        )

    _assert_no_message_side_effect(repository, claim, missing_session_id, idempotency)
    assert repository.get_session(claim.claim_id, missing_session_id, claim.customer_id) is None


def test_staff_message_rejects_paused_authoritative_session_without_partial_write() -> None:
    repository, claim, session = _repository()
    paused_session = session.model_copy(update={'status': SessionStatus.PAUSED})
    repository.save_session(paused_session)
    message = _message(claim, session.session_id, 'msg_staff_paused_session')
    idempotency = _idempotency(claim, session.session_id, message.message_id)

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            message=message,
        )

    _assert_no_message_side_effect(repository, claim, session.session_id, idempotency)
    assert (
        repository.get_session(claim.claim_id, session.session_id, claim.customer_id)
        == paused_session
    )
