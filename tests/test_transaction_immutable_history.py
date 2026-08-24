from datetime import UTC, datetime

import pytest

from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
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
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 24, 2, 30, tzinfo=UTC)


def _claim(repository: FixtureRepository, suffix: str) -> WorkingClaim:
    claim = WorkingClaim(
        claim_id=f'clm_{suffix}',
        customer_id=f'cus_{suffix}',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id=f'ses_{suffix}',
        customer_next_step=CustomerNextStep(
            status='collecting',
            summary='Continue the claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    repository.create_claim(
        claim,
        SessionRecord(
            session_id=claim.active_session_id or '',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=FIXED_TIME,
            last_active_at=FIXED_TIME,
        ),
    )
    return claim


def _turn_records(
    claim: WorkingClaim,
    *,
    session_id: str | None = None,
    suffix: str = 'turn',
) -> tuple[MessageRecord, MessageRecord, AgentDecisionRecord, IdempotencyRecord]:
    resolved_session_id = session_id or claim.active_session_id or ''
    claimant_message = MessageRecord(
        message_id=f'msg_{suffix}_claimant',
        claim_id=claim.claim_id,
        session_id=resolved_session_id,
        client_message_id=f'client-{suffix}',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic claimant turn.'},
        created_at=FIXED_TIME,
    )
    agent_message = MessageRecord(
        message_id=f'msg_{suffix}_agent',
        claim_id=claim.claim_id,
        session_id=resolved_session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic agent reply.'},
        in_reply_to=claimant_message.message_id,
        created_at=FIXED_TIME,
    )
    decision = AgentDecisionRecord(
        decision_id=f'dec_{suffix}',
        claim_id=claim.claim_id,
        session_id=resolved_session_id,
        trigger_message_id=claimant_message.message_id,
        action=AgentAction.ASK,
        reason_codes=['MORE_INFORMATION_REQUIRED'],
        customer_reason='More information is needed.',
        customer_response='Please provide more information.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='controlled_agent',
            validated_by='deterministic_authority',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=2,
        created_at=FIXED_TIME,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions/{resolved_session_id}/messages',
        key=f'key-{suffix}',
        request_fingerprint=f'fingerprint-{suffix}',
        claim_id=claim.claim_id,
        session_id=resolved_session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )
    return claimant_message, agent_message, decision, idempotency


def test_agent_turn_rejects_paused_stored_session_without_partial_write() -> None:
    repository = FixtureRepository()
    claim = _claim(repository, 'paused_session')
    stored_session = repository.get_session(
        claim.claim_id,
        claim.active_session_id or '',
        claim.customer_id,
    )
    assert stored_session is not None
    paused_session = stored_session.model_copy(update={'status': SessionStatus.PAUSED})
    repository.save_session(paused_session)

    claimant_message, agent_message, decision, idempotency = _turn_records(
        claim,
        suffix='paused-session',
    )
    incoming_session = paused_session.model_copy(
        update={'status': SessionStatus.ACTIVE, 'context_revision': 2}
    )

    with pytest.raises(KeyError):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 2}),
            1,
            incoming_session,
            claimant_message,
            agent_message,
            decision,
            idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(claim.claim_id, paused_session.session_id, claim.customer_id)
        == paused_session
    )
    assert repository.list_messages(claim.claim_id, paused_session.session_id, claim.customer_id) == []
    assert repository.list_agent_decisions(claim.claim_id, claim.customer_id) == []
    assert repository.find_idempotency(
        claim.customer_id,
        idempotency.route,
        idempotency.key,
    ) is None


def test_agent_turn_rejects_non_current_session_without_partial_write() -> None:
    repository = FixtureRepository()
    claim = _claim(repository, 'current_session')
    current_session = repository.get_session(
        claim.claim_id,
        claim.active_session_id or '',
        claim.customer_id,
    )
    assert current_session is not None
    old_session = SessionRecord(
        session_id='ses_old_session',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=1,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.save_session(old_session)

    claimant_message, agent_message, decision, idempotency = _turn_records(
        claim,
        session_id=old_session.session_id,
        suffix='old-session',
    )
    incoming_session = old_session.model_copy(update={'context_revision': 2})

    with pytest.raises(KeyError):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 2}),
            1,
            incoming_session,
            claimant_message,
            agent_message,
            decision,
            idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(claim.claim_id, current_session.session_id, claim.customer_id)
        == current_session
    )
    assert repository.get_session(claim.claim_id, old_session.session_id, claim.customer_id) == old_session
    assert repository.list_messages(claim.claim_id, old_session.session_id, claim.customer_id) == []
    assert repository.list_agent_decisions(claim.claim_id, claim.customer_id) == []
    assert repository.find_idempotency(
        claim.customer_id,
        idempotency.route,
        idempotency.key,
    ) is None


@pytest.mark.parametrize('collision_kind', ['claimant_message', 'agent_message', 'decision'])
def test_agent_turn_rejects_same_claim_immutable_identity_collision(
    collision_kind: str,
) -> None:
    repository = FixtureRepository()
    claim = _claim(repository, f'immutable_{collision_kind}')
    claimant_message, agent_message, decision, idempotency = _turn_records(
        claim,
        suffix=collision_kind,
    )
    session = repository.get_session(
        claim.claim_id,
        claim.active_session_id or '',
        claim.customer_id,
    )
    assert session is not None
    incoming_session = session.model_copy(update={'context_revision': 2})

    original_message: MessageRecord | None = None
    original_decision: AgentDecisionRecord | None = None
    if collision_kind == 'claimant_message':
        original_message = claimant_message.model_copy(
            update={'content': {'type': 'text', 'text': 'Original claimant history.'}}
        )
        repository.save_message(original_message, claim.customer_id)
    elif collision_kind == 'agent_message':
        original_message = agent_message.model_copy(
            update={'content': {'type': 'text', 'text': 'Original agent history.'}}
        )
        repository.save_message(original_message, claim.customer_id)
    else:
        original_decision = decision.model_copy(
            update={'customer_response': 'Original durable decision.'}
        )
        repository.save_agent_decision(original_decision, claim.customer_id)

    with pytest.raises(IdempotencyConflict):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 2}),
            1,
            incoming_session,
            claimant_message,
            agent_message,
            decision,
            idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.get_session(claim.claim_id, session.session_id, claim.customer_id) == session
    if original_message is not None:
        assert (
            repository.get_message(
                claim.claim_id,
                session.session_id,
                original_message.message_id,
                claim.customer_id,
            )
            == original_message
        )
    if original_decision is not None:
        assert (
            repository.get_agent_decision(
                claim.claim_id,
                original_decision.decision_id,
                claim.customer_id,
            )
            == original_decision
        )
    assert repository.find_idempotency(
        claim.customer_id,
        idempotency.route,
        idempotency.key,
    ) is None


def test_staff_mutation_rejects_same_claim_message_identity_collision() -> None:
    repository = FixtureRepository()
    claim = _claim(repository, 'staff_message_collision')
    session_id = claim.active_session_id or ''
    original = MessageRecord(
        message_id='msg_staff_durable',
        claim_id=claim.claim_id,
        session_id=session_id,
        actor=ActorType.STAFF,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Original staff message.'},
        created_at=FIXED_TIME,
    )
    repository.save_message(original, claim.customer_id)
    replacement = original.model_copy(
        update={'content': {'type': 'text', 'text': 'Replacement staff message.'}}
    )
    idempotency = IdempotencyRecord(
        actor_id='stf_demo',
        route=f'/api/v1/workbench/claims/{claim.claim_id}/messages',
        key='staff-message-collision',
        request_fingerprint='fingerprint-staff-message-collision',
        claim_id=claim.claim_id,
        session_id=session_id,
        message_id=original.message_id,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            1,
            idempotency,
            message=replacement,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.get_message(
        claim.claim_id,
        session_id,
        original.message_id,
        claim.customer_id,
    ) == original
    assert repository.find_idempotency(
        idempotency.actor_id,
        idempotency.route,
        idempotency.key,
    ) is None
