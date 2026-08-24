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
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    SupportNeed,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 24, 1, 50, tzinfo=UTC)


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
            session_id=f'ses_{suffix}',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=FIXED_TIME,
            last_active_at=FIXED_TIME,
        ),
    )
    return claim


def _claimant_retry(claim: WorkingClaim, key: str, **links: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/{key}',
        key=key,
        request_fingerprint=f'fingerprint-{key}',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        **links,
    )


def _evidence(claim_id: str, evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='photo',
        status=EvidenceStatus.INCOMPLETE,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def _handoff(claim_id: str, handoff_id: str) -> HandoffRecord:
    return HandoffRecord(
        handoff_id=handoff_id,
        claim_id=claim_id,
        type=HandoffType.HUMAN_SUPPORT,
        status=HandoffStatus.QUEUED,
        priority=HandoffPriority.STANDARD,
        queue='human_support',
        support_need=SupportNeed.HUMAN_REQUESTED,
        trigger=HandoffTrigger.CLAIMANT_SUPPORT_REQUEST,
        reason_codes=['HUMAN_REQUESTED'],
        reason='The claimant requested human support.',
        requested_action='Continue the claim with the claimant.',
        applied_rule='claimant_requested_human_support',
        packet=HandoffPacket(
            form_revision=1,
            promised_next_step='A staff member will continue the claim.',
        ),
        created_at=FIXED_TIME,
    )


def test_evidence_id_cannot_be_reowned_by_another_claim() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_evidence')
    second = _claim(repository, 'second_evidence')
    original = _evidence(first.claim_id, 'evd_shared_identity')
    repository.save_evidence(original, first.customer_id)

    with pytest.raises(KeyError):
        repository.save_evidence_mutation(
            second.model_copy(update={'revision': 2}),
            1,
            original.model_copy(update={'claim_id': second.claim_id}),
            _claimant_retry(second, 'steal-evidence'),
        )

    assert repository.get_evidence(first.claim_id, original.evidence_id, first.customer_id) == original
    assert repository.get_evidence(second.claim_id, original.evidence_id, second.customer_id) is None
    assert repository.get_claim(second.claim_id, second.customer_id) == second


def test_handoff_id_cannot_be_reowned_by_another_claim() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_handoff')
    second = _claim(repository, 'second_handoff')
    original = _handoff(first.claim_id, 'hnd_shared_identity')
    repository.save_handoff(original, first.customer_id)

    with pytest.raises(KeyError):
        repository.save_handoff_mutation(
            second.model_copy(update={'revision': 2}),
            1,
            original.model_copy(update={'claim_id': second.claim_id}),
            _claimant_retry(second, 'steal-handoff', handoff_id=original.handoff_id),
        )

    assert repository.get_handoff(first.claim_id, original.handoff_id, first.customer_id) == original
    assert repository.get_handoff(second.claim_id, original.handoff_id, second.customer_id) is None
    assert repository.get_claim(second.claim_id, second.customer_id) == second


def test_agent_decision_id_cannot_be_reowned_by_another_claim_turn() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_turn')
    second = _claim(repository, 'second_turn')
    original_decision = AgentDecisionRecord(
        decision_id='dec_shared_identity',
        claim_id=first.claim_id,
        session_id=first.active_session_id or '',
        trigger_message_id='msg_seed_trigger',
        action=AgentAction.ASK,
        reason_codes=['MORE_INFORMATION_REQUIRED'],
        customer_reason='More information is needed.',
        customer_response='Please provide more information.',
        customer_next_step=first.customer_next_step,
        authority=AgentAuthority(
            proposed_by='controlled_agent',
            validated_by='deterministic_authority',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=1,
        created_at=FIXED_TIME,
    )
    repository.save_agent_decision(original_decision, first.customer_id)

    claimant_message = MessageRecord(
        message_id='msg_second_claimant',
        claim_id=second.claim_id,
        session_id=second.active_session_id or '',
        client_message_id='client-second-turn',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic claimant turn.'},
        created_at=FIXED_TIME,
    )
    agent_message = MessageRecord(
        message_id='msg_second_agent',
        claim_id=second.claim_id,
        session_id=second.active_session_id or '',
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic agent reply.'},
        in_reply_to=claimant_message.message_id,
        created_at=FIXED_TIME,
    )
    decision = original_decision.model_copy(
        update={
            'claim_id': second.claim_id,
            'session_id': second.active_session_id or '',
            'trigger_message_id': claimant_message.message_id,
            'customer_next_step': second.customer_next_step,
            'resulting_revision': 2,
        }
    )
    updated_session = repository.get_session(
        second.claim_id,
        second.active_session_id or '',
        second.customer_id,
    )
    assert updated_session is not None
    updated_session = updated_session.model_copy(update={'context_revision': 2})
    retry = _claimant_retry(
        second,
        'steal-decision',
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )

    with pytest.raises(KeyError):
        repository.save_agent_turn(
            second.model_copy(update={'revision': 2}),
            1,
            updated_session,
            claimant_message,
            agent_message,
            decision,
            retry,
        )

    assert repository.get_agent_decision_internal(first.claim_id, original_decision.decision_id) == original_decision
    assert repository.get_agent_decision_internal(second.claim_id, original_decision.decision_id) is None
    assert repository.get_claim(second.claim_id, second.customer_id) == second


def test_agent_turn_rejects_claimant_and_agent_message_identity_aliasing() -> None:
    repository = FixtureRepository()
    claim = _claim(repository, 'aliased_messages')
    shared_message_id = 'msg_aliased'
    claimant_message = MessageRecord(
        message_id=shared_message_id,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        client_message_id='client-aliased',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic claimant turn.'},
        created_at=FIXED_TIME,
    )
    agent_message = MessageRecord(
        message_id=shared_message_id,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Synthetic agent reply.'},
        in_reply_to=shared_message_id,
        created_at=FIXED_TIME,
    )
    decision = AgentDecisionRecord(
        decision_id='dec_alias_test',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        trigger_message_id=shared_message_id,
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
    session = repository.get_session(
        claim.claim_id,
        claim.active_session_id or '',
        claim.customer_id,
    )
    assert session is not None
    session = session.model_copy(update={'context_revision': 2})
    retry = _claimant_retry(
        claim,
        'aliased-messages',
        message_id=shared_message_id,
        agent_message_id=shared_message_id,
        decision_id=decision.decision_id,
    )

    with pytest.raises(KeyError):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 2}),
            1,
            session,
            claimant_message,
            agent_message,
            decision,
            retry,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_messages(claim.claim_id, claim.active_session_id or '', claim.customer_id) == []
