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
    StaffActionRecord,
    StaffActionStatus,
    SupportNeed,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)


def _repository() -> tuple[FixtureRepository, WorkingClaim, SessionRecord]:
    repository = FixtureRepository()
    claim = WorkingClaim(
        claim_id='clm_tx',
        customer_id='cus_tx',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_tx',
        customer_next_step=CustomerNextStep(
            status='continue',
            summary='Continue the report.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_tx',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    return repository, claim, session


def _message() -> MessageRecord:
    return MessageRecord(
        message_id='msg_tx',
        claim_id='clm_tx',
        session_id='ses_tx',
        client_message_id='client-tx',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Additional context.'},
        created_at=FIXED_TIME,
    )


def _claimant_idempotency(*, message_id: str | None = None) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id='cus_tx',
        route='/api/v1/claims/clm_tx/sessions/ses_tx/messages',
        key='tx-key',
        request_fingerprint='tx-fingerprint',
        claim_id='clm_tx',
        session_id='ses_tx',
        message_id=message_id,
    )


def _assert_no_message_side_effect(
    repository: FixtureRepository,
    original_claim: WorkingClaim,
    idempotency: IdempotencyRecord,
) -> None:
    assert (
        repository.get_claim(original_claim.claim_id, original_claim.customer_id) == original_claim
    )
    assert repository.list_messages('clm_tx', 'ses_tx', 'cus_tx') == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_message_mutation_rejects_revision_jump_without_partial_write() -> None:
    repository, claim, session = _repository()
    message = _message()
    idempotency = _claimant_idempotency(message_id=message.message_id)
    jumped_claim = claim.model_copy(update={'revision': 3})
    jumped_session = session.model_copy(update={'context_revision': 3})

    with pytest.raises(KeyError):
        repository.save_message_mutation(
            jumped_claim,
            expected_revision=1,
            session=jumped_session,
            message=message,
            idempotency=idempotency,
        )

    _assert_no_message_side_effect(repository, claim, idempotency)
    assert repository.get_session('clm_tx', 'ses_tx', 'cus_tx') == session


def test_message_mutation_rejects_cross_record_idempotency_link_without_partial_write() -> None:
    repository, claim, session = _repository()
    message = _message()
    idempotency = IdempotencyRecord(
        **{
            **_claimant_idempotency(message_id='msg_other').__dict__,
            'key': 'wrong-message-link',
        },
    )
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})

    with pytest.raises(KeyError):
        repository.save_message_mutation(
            updated_claim,
            expected_revision=1,
            session=updated_session,
            message=message,
            idempotency=idempotency,
        )

    _assert_no_message_side_effect(repository, claim, idempotency)
    assert repository.get_session('clm_tx', 'ses_tx', 'cus_tx') == session


def test_agent_turn_rejects_revision_jump_before_any_child_write() -> None:
    repository, claim, session = _repository()
    claimant_message = _message()
    agent_message = MessageRecord(
        message_id='msg_agent_tx',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Please confirm.'},
        in_reply_to=claimant_message.message_id,
        created_at=FIXED_TIME,
    )
    jumped_claim = claim.model_copy(update={'revision': 3})
    jumped_session = session.model_copy(update={'context_revision': 3})
    decision = AgentDecisionRecord(
        decision_id='dec_tx',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        trigger_message_id=claimant_message.message_id,
        action=AgentAction.CONFIRM,
        reason_codes=['MATERIAL_FACTS_PROPOSED'],
        customer_reason='Confirm the supplied facts.',
        customer_response='Please confirm the supplied facts.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=3,
        created_at=FIXED_TIME,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/clm_tx/sessions/ses_tx/messages',
        key='agent-turn-jump',
        request_fingerprint='agent-turn-jump',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )

    with pytest.raises(KeyError):
        repository.save_agent_turn(
            jumped_claim,
            expected_revision=1,
            session=jumped_session,
            claimant_message=claimant_message,
            agent_message=agent_message,
            decision=decision,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == []
    assert repository.list_agent_decisions(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_evidence_mutation_rejects_revision_jump_without_partial_write() -> None:
    repository, claim, _session = _repository()
    evidence = EvidenceRecord(
        evidence_id='evd_tx',
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
        route='/api/v1/claims/clm_tx/evidence',
        key='evidence-jump',
        request_fingerprint='evidence-jump',
        claim_id=claim.claim_id,
        session_id='ses_tx',
    )

    with pytest.raises(KeyError):
        repository.save_evidence_mutation(
            claim.model_copy(update={'revision': 3}),
            expected_revision=1,
            evidence=evidence,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_evidence(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def _handoff(claim: WorkingClaim) -> HandoffRecord:
    return HandoffRecord(
        handoff_id='hnd_tx',
        claim_id=claim.claim_id,
        type=HandoffType.HUMAN_SUPPORT,
        status=HandoffStatus.REQUESTED,
        priority=HandoffPriority.STANDARD,
        queue='human_support',
        support_need=SupportNeed.HUMAN_REQUESTED,
        trigger=HandoffTrigger.CLAIMANT_SUPPORT_REQUEST,
        reason_codes=['HUMAN_SUPPORT_REQUESTED'],
        reason='The claimant requested a person.',
        requested_action='Continue the report with staff support.',
        applied_rule='human_support_request',
        packet=HandoffPacket(
            form_revision=claim.revision,
            promised_next_step='Northwind staff will continue the report.',
        ),
        source_message_id='msg_source',
        created_at=FIXED_TIME,
    )


def test_handoff_mutation_rejects_revision_jump_without_partial_write() -> None:
    repository, claim, _session = _repository()
    handoff = _handoff(claim)
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/clm_tx/support-requests',
        key='handoff-jump',
        request_fingerprint='handoff-jump',
        claim_id=claim.claim_id,
        session_id='ses_tx',
        handoff_id=handoff.handoff_id,
    )

    with pytest.raises(KeyError):
        repository.save_handoff_mutation(
            claim.model_copy(update={'revision': 3}),
            expected_revision=1,
            handoff=handoff,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_handoffs(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def _staff_action(claim: WorkingClaim) -> StaffActionRecord:
    return StaffActionRecord(
        action_id='act_tx',
        claim_id=claim.claim_id,
        action_type='professional_review',
        status=StaffActionStatus.OPEN,
        assigned_to='stf_demo',
        requested_outcome='Review the supplied context.',
        created_at=FIXED_TIME,
    )


def test_staff_mutation_rejects_revision_jump_without_partial_write() -> None:
    repository, claim, _session = _repository()
    action = _staff_action(claim)
    idempotency = IdempotencyRecord(
        actor_id='stf_demo',
        route='/api/v1/workbench/claims/clm_tx/staff-actions',
        key='staff-jump',
        request_fingerprint='staff-jump',
        claim_id=claim.claim_id,
        session_id='ses_tx',
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 3}),
            expected_revision=1,
            idempotency=idempotency,
            staff_action=action,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_staff_actions(claim.claim_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_staff_mutation_rejects_cross_claim_idempotency_without_partial_write() -> None:
    repository, claim, _session = _repository()
    action = _staff_action(claim)
    idempotency = IdempotencyRecord(
        actor_id='stf_demo',
        route='/api/v1/workbench/claims/clm_tx/staff-actions',
        key='staff-cross-claim',
        request_fingerprint='staff-cross-claim',
        claim_id='clm_other',
        session_id='ses_tx',
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            staff_action=action,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_staff_actions(claim.claim_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_staff_mutation_allows_session_agnostic_staff_action() -> None:
    repository, claim, _session = _repository()
    action = _staff_action(claim)
    updated_claim = claim.model_copy(update={'revision': 2})
    idempotency = IdempotencyRecord(
        actor_id='stf_demo',
        route='/api/v1/workbench/claims/clm_tx/staff-actions',
        key='staff-no-session',
        request_fingerprint='staff-no-session',
        claim_id=claim.claim_id,
        session_id='',
    )

    repository.save_staff_mutation(
        updated_claim,
        expected_revision=1,
        idempotency=idempotency,
        staff_action=action,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert repository.list_staff_actions(claim.claim_id) == [action]
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        == idempotency
    )


def test_staff_mutation_rejects_non_staff_message_without_partial_write() -> None:
    repository, claim, _session = _repository()
    message = _message()
    idempotency = IdempotencyRecord(
        actor_id='stf_demo',
        route='/api/v1/workbench/claims/clm_tx/messages',
        key='staff-wrong-message-actor',
        request_fingerprint='staff-wrong-message-actor',
        claim_id=claim.claim_id,
        session_id='ses_tx',
        message_id=message.message_id,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            message=message,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_messages(claim.claim_id, 'ses_tx', claim.customer_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )
