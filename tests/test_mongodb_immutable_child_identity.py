"""Same-claim identity reuse must not rewrite an immutable child record.

The evidence here is logical: ``mongomock`` proves the guard ordering and the
resulting snapshot, not live MongoDB transaction rollback or concurrency
behaviour.
"""

from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
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
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 27, 2, 0, tzinfo=UTC)


def _repository() -> tuple[MongoDBRepository, WorkingClaim, SessionRecord]:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_immutable_identity')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    claim = WorkingClaim(
        claim_id='clm_mongo_immutable',
        customer_id='cus_mongo_immutable',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_mongo_immutable',
        customer_next_step=CustomerNextStep(
            status='continue_intake',
            summary='Continue the claim intake.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_mongo_immutable',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=1,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)
    return repository, claim, session


def _message(claim: WorkingClaim, session: SessionRecord) -> MessageRecord:
    return MessageRecord(
        message_id='msg_mongo_immutable',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Original persisted message.'},
        created_at=FIXED_TIME,
    )


def _idempotency(claim: WorkingClaim, session: SessionRecord, key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/messages',
        key=key,
        request_fingerprint=key + '-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id='msg_mongo_immutable',
    )


def test_mongodb_rejects_same_claim_message_identity_reuse() -> None:
    repository, claim, session = _repository()
    persisted = _message(claim, session)
    repository.save_message_mutation(
        claim.model_copy(update={'revision': 2}),
        expected_revision=1,
        session=session.model_copy(update={'context_revision': 2}),
        message=persisted,
        idempotency=_idempotency(claim, session, 'immutable-first'),
    )
    stored_claim = repository.get_claim(claim.claim_id, claim.customer_id)
    assert stored_claim is not None

    rewrite = persisted.model_copy(
        update={'content': {'type': 'text', 'text': 'Rewritten history.'}}
    )
    replay_key = _idempotency(claim, session, 'immutable-second')

    with pytest.raises(IdempotencyConflict):
        repository.save_message_mutation(
            claim.model_copy(update={'revision': 3}),
            expected_revision=2,
            session=session.model_copy(update={'context_revision': 3}),
            message=rewrite,
            idempotency=replay_key,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == stored_claim
    assert (
        repository.get_message(
            claim.claim_id,
            session.session_id,
            persisted.message_id,
            claim.customer_id,
        )
        == persisted
    )
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == [
        persisted
    ]
    assert (
        repository.find_idempotency(replay_key.actor_id, replay_key.route, replay_key.key) is None
    )


def test_mongodb_rejects_same_claim_agent_decision_identity_reuse() -> None:
    repository, claim, session = _repository()
    claimant_message = MessageRecord(
        message_id='msg_mongo_claimant',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'A synthetic incident.'},
        created_at=FIXED_TIME,
    )
    agent_message = claimant_message.model_copy(
        update={
            'message_id': 'msg_mongo_agent',
            'actor': ActorType.AGENT,
            'content': {'type': 'text', 'text': 'Please confirm the incident.'},
            'in_reply_to': 'msg_mongo_claimant',
        }
    )
    decision = AgentDecisionRecord(
        decision_id='dec_mongo_immutable',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        trigger_message_id=claimant_message.message_id,
        action=AgentAction.CONFIRM,
        reason_codes=['MATERIAL_FACTS_PROPOSED'],
        customer_reason='Please confirm the proposed detail.',
        customer_response='Please confirm the proposed detail.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=2,
        created_at=FIXED_TIME,
    )
    repository.save_agent_turn(
        claim.model_copy(update={'revision': 2}),
        1,
        session.model_copy(update={'context_revision': 2}),
        claimant_message,
        agent_message,
        decision,
        IdempotencyRecord(
            actor_id=claim.customer_id,
            route='/agent-turn',
            key='agent-turn-first',
            request_fingerprint='agent-turn-first-fingerprint',
            claim_id=claim.claim_id,
            session_id=session.session_id,
            message_id=claimant_message.message_id,
            agent_message_id=agent_message.message_id,
            decision_id=decision.decision_id,
        ),
    )
    stored_claim = repository.get_claim(claim.claim_id, claim.customer_id)
    stored_messages = repository.list_messages(
        claim.claim_id, session.session_id, claim.customer_id
    )

    replay_claimant = claimant_message.model_copy(update={'message_id': 'msg_mongo_claimant_two'})
    replay_agent = agent_message.model_copy(
        update={'message_id': 'msg_mongo_agent_two', 'in_reply_to': 'msg_mongo_claimant_two'}
    )
    replay_decision = decision.model_copy(
        update={
            'trigger_message_id': replay_claimant.message_id,
            'customer_reason': 'Rewritten decision history.',
            'resulting_revision': 3,
        }
    )
    replay_key = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/agent-turn',
        key='agent-turn-second',
        request_fingerprint='agent-turn-second-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=replay_claimant.message_id,
        agent_message_id=replay_agent.message_id,
        decision_id=replay_decision.decision_id,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 3}),
            2,
            session.model_copy(update={'context_revision': 3}),
            replay_claimant,
            replay_agent,
            replay_decision,
            replay_key,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == stored_claim
    assert (
        repository.get_agent_decision(claim.claim_id, decision.decision_id, claim.customer_id)
        == decision
    )
    assert (
        repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)
        == stored_messages
    )
    assert (
        repository.find_idempotency(replay_key.actor_id, replay_key.route, replay_key.key) is None
    )


def test_mongodb_still_allows_mutable_lifecycle_record_updates() -> None:
    repository, claim, session = _repository()
    evidence = EvidenceRecord(
        evidence_id='evd_mongo_immutable',
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.PENDING,
        file_status=EvidenceFileStatus.AWAITING_UPLOAD,
        source=EvidenceSource.CLAIMANT,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    repository.save_evidence_mutation(
        claim.model_copy(update={'revision': 2}),
        expected_revision=1,
        evidence=evidence,
        idempotency=IdempotencyRecord(
            actor_id=claim.customer_id,
            route='/evidence',
            key='evidence-first',
            request_fingerprint='evidence-first-fingerprint',
            claim_id=claim.claim_id,
            session_id=session.session_id,
        ),
    )

    settled = evidence.model_copy(
        update={'status': EvidenceStatus.RECEIVED, 'file_status': EvidenceFileStatus.READY}
    )
    repository.save_evidence_mutation(
        claim.model_copy(update={'revision': 3}),
        expected_revision=2,
        evidence=settled,
        idempotency=IdempotencyRecord(
            actor_id=claim.customer_id,
            route='/evidence',
            key='evidence-second',
            request_fingerprint='evidence-second-fingerprint',
            claim_id=claim.claim_id,
            session_id=session.session_id,
        ),
    )

    assert (
        repository.get_evidence(claim.claim_id, evidence.evidence_id, claim.customer_id) == settled
    )
