from datetime import UTC, datetime

import pytest

from backend.domain.models import (
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
    RuntimeInvocationTrace,
    RuntimeTraceRecord,
    SessionRecord,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.key_layout import (
    claim_key,
    customer_claim_index_key,
    decision_key,
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


def make_runtime_records(
    claim: WorkingClaim,
    session: SessionRecord,
) -> tuple[
    WorkingClaim,
    SessionRecord,
    MessageRecord,
    MessageRecord,
    RuntimeTraceRecord,
    IdempotencyRecord,
]:
    claim = claim.model_copy(update={'active_session_id': session.session_id})
    session = session.model_copy(update={'context_revision': claim.revision})
    claimant_message = MessageRecord(
        message_id='msg_runtime_claimant',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id='runtime-client',
        actor='claimant',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Read my current report.'},
        created_at=claim.created_at,
    )
    agent_message = MessageRecord(
        message_id='msg_runtime_agent',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor='agent',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'I read the current report.'},
        in_reply_to=claimant_message.message_id,
        created_at=claim.created_at,
    )
    trace = RuntimeTraceRecord(
        trace_id='trace_runtime',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        model_profile_id='qwen-local',
        trigger_message_id=claimant_message.message_id,
        invocations=[
            RuntimeInvocationTrace(
                ordinal=1,
                provider_model='qwen3.8-27b',
                provider_request_id='provider-request-1',
                latency_ms=10,
            )
        ],
        tool_call_id='call_claim_read',
        tool_name='claim.read',
        tool_result_status='succeeded',
        action_code='conversation.answer',
        runtime_action_code='runtime.continue',
        reason_codes=['CLAIM_CONTEXT_READ'],
        status='succeeded',
        created_at=claim.created_at,
        finished_at=claim.updated_at,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/messages',
        key='runtime-key',
        request_fingerprint='runtime-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        runtime_trace_id=trace.trace_id,
    )
    return claim, session, claimant_message, agent_message, trace, idempotency


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


def test_fixture_claim_mutation_rejects_every_partial_write_precondition() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()
    updated = claim.model_copy(update={'revision': 2})
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/clm_fixture/consent',
        key='claim-mutation-key',
        request_fingerprint='claim-mutation-fingerprint',
        claim_id=claim.claim_id,
        session_id='',
    )

    with pytest.raises(KeyError):
        repository.save_claim_mutation(updated, 1, idempotency)

    repository.create_claim(claim, session)
    with pytest.raises(RevisionConflict):
        repository.save_claim_mutation(updated, 0, idempotency)
    with pytest.raises(KeyError):
        repository.save_claim_mutation(
            updated,
            1,
            IdempotencyRecord(**{**idempotency.__dict__, 'actor_id': 'another-customer'}),
        )

    repository.save_idempotency(idempotency)
    with pytest.raises(IdempotencyConflict):
        repository.save_claim_mutation(updated, 1, idempotency)

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim


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
    assert repository.list_sessions_for_claim(claim.claim_id, 'other_customer') == []
    with pytest.raises(KeyError):
        repository.save_session(session.model_copy(update={'customer_id': 'other_customer'}))
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
    earlier_tie_breaker = message.model_copy(update={'message_id': 'msg_a_fixture'})
    repository.save_message(earlier_tie_breaker, 'cus_fixture')
    repository.save_evidence(evidence, 'cus_fixture')

    assert [item.claim_id for item in repository.list_claims_for_customer('cus_fixture')] == [
        claim.claim_id
    ]
    assert repository.list_messages(claim.claim_id, session.session_id, 'cus_fixture') == [
        earlier_tie_breaker,
        message,
    ]
    assert repository.list_messages(claim.claim_id, session.session_id, 'other_customer') == []
    assert repository.get_evidence(claim.claim_id, evidence.evidence_id, 'cus_fixture') == evidence
    assert repository.list_evidence(claim.claim_id, 'other_customer') == []
    with pytest.raises(KeyError):
        repository.save_message(message, 'other_customer')
    with pytest.raises(KeyError):
        repository.save_evidence(evidence, 'other_customer')


def test_fixture_repository_persists_agent_turn_as_one_consistent_unit() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()
    claim = claim.model_copy(update={'active_session_id': session.session_id})
    repository.create_claim(claim, session)
    claimant_message = MessageRecord(
        message_id='msg_claimant',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id='client-turn',
        actor='claimant',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'A synthetic incident.'},
        created_at=claim.created_at,
    )
    agent_message = MessageRecord(
        message_id='msg_agent',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor='agent',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'Please confirm the incident.'},
        in_reply_to=claimant_message.message_id,
        created_at=claim.created_at,
    )
    decision = AgentDecisionRecord(
        decision_id='dec_fixture',
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
        created_at=claim.created_at,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/clm_fixture/sessions/ses_fixture/messages',
        key='turn-key',
        request_fingerprint='turn-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})

    repository.save_agent_turn(
        updated_claim,
        1,
        updated_session,
        claimant_message,
        agent_message,
        decision,
        idempotency,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert (
        repository.get_message(
            claim.claim_id,
            session.session_id,
            claimant_message.message_id,
            claim.customer_id,
        )
        == claimant_message
    )
    assert (
        repository.find_message_by_client_id(
            claim.claim_id,
            'client-turn',
            claim.customer_id,
        )
        == claimant_message
    )
    assert (
        repository.get_agent_decision(
            claim.claim_id,
            decision.decision_id,
            claim.customer_id,
        )
        == decision
    )
    assert (
        repository.find_agent_decision_for_trigger(
            claim.claim_id,
            claimant_message.message_id,
            claim.customer_id,
        )
        == decision
    )
    assert repository.list_agent_decisions(claim.claim_id, claim.customer_id) == [decision]
    assert repository.list_agent_decisions(claim.claim_id, 'other_customer') == []

    with pytest.raises(RevisionConflict):
        repository.save_agent_turn(
            updated_claim,
            1,
            updated_session,
            claimant_message.model_copy(update={'message_id': 'msg_retry'}),
            agent_message,
            decision,
            idempotency,
        )


def test_fixture_repository_rejects_inconsistent_agent_turn_records() -> None:
    repository = FixtureRepository()
    claim, session = make_claim()
    repository.create_claim(claim, session)
    claimant_message = MessageRecord(
        message_id='msg_claimant',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id='client-turn',
        actor='claimant',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'A synthetic incident.'},
        created_at=claim.created_at,
    )
    agent_message = claimant_message.model_copy(
        update={
            'message_id': 'msg_agent',
            'actor': 'agent',
            'client_message_id': None,
            'in_reply_to': 'wrong-trigger',
        }
    )
    decision = AgentDecisionRecord(
        decision_id='dec_fixture',
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
        created_at=claim.created_at,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/messages',
        key='turn-key',
        request_fingerprint='turn-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
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
            idempotency,
        )

    wrong_actor = claimant_message.model_copy(update={'actor': 'agent'})
    linked_agent_message = agent_message.model_copy(update={'in_reply_to': wrong_actor.message_id})
    with pytest.raises(KeyError):
        repository.save_agent_turn(
            claim.model_copy(update={'revision': 2}),
            1,
            session.model_copy(update={'context_revision': 2}),
            wrong_actor,
            linked_agent_message,
            decision,
            idempotency,
        )


def test_fixture_repository_persists_and_reads_runtime_trace() -> None:
    repository = FixtureRepository()
    records = make_runtime_records(*make_claim())
    claim, session, claimant_message, agent_message, trace, idempotency = records
    repository.create_claim(claim, session)

    repository.save_runtime_turn(
        claim,
        claim.revision,
        session,
        claimant_message,
        agent_message,
        trace,
        idempotency,
    )

    assert repository.get_runtime_trace(claim.claim_id, trace.trace_id, claim.customer_id) == trace
    assert (
        repository.find_runtime_trace_for_trigger(
            claim.claim_id,
            claimant_message.message_id,
            claim.customer_id,
        )
        == trace
    )
    assert repository.get_runtime_trace(claim.claim_id, trace.trace_id, 'other_customer') is None
    assert repository.get_runtime_trace(claim.claim_id, 'missing-trace', claim.customer_id) is None
    assert (
        repository.find_runtime_trace_for_trigger(
            claim.claim_id,
            'missing-message',
            claim.customer_id,
        )
        is None
    )


def test_fixture_runtime_turn_rejects_revision_records_and_retries() -> None:
    repository = FixtureRepository()
    claim, session, claimant_message, agent_message, trace, idempotency = make_runtime_records(
        *make_claim()
    )

    with pytest.raises(KeyError):
        repository.save_runtime_turn(
            claim,
            claim.revision,
            session,
            claimant_message,
            agent_message,
            trace,
            idempotency,
        )

    repository.create_claim(claim, session)
    with pytest.raises(RevisionConflict):
        repository.save_runtime_turn(
            claim,
            claim.revision - 1,
            session,
            claimant_message,
            agent_message,
            trace,
            idempotency,
        )

    with pytest.raises(KeyError):
        repository.save_runtime_turn(
            claim,
            claim.revision,
            session,
            claimant_message.model_copy(update={'claim_id': 'other-claim'}),
            agent_message,
            trace,
            idempotency,
        )

    repository.save_message(
        claimant_message.model_copy(update={'message_id': 'existing-message'}),
        claim.customer_id,
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_runtime_turn(
            claim,
            claim.revision,
            session,
            claimant_message,
            agent_message,
            trace,
            idempotency,
        )

    duplicate_repository = FixtureRepository()
    duplicate_repository.create_claim(claim, session)
    duplicate_repository.save_message(claimant_message, claim.customer_id)
    new_claimant_message = claimant_message.model_copy(update={'message_id': 'new-message'})
    new_agent_message = agent_message.model_copy(update={'in_reply_to': 'new-message'})
    with pytest.raises(IdempotencyConflict):
        duplicate_repository.save_runtime_turn(
            claim,
            claim.revision,
            session,
            new_claimant_message,
            new_agent_message,
            trace.model_copy(update={'trace_id': 'new-trace', 'trigger_message_id': 'new-message'}),
            IdempotencyRecord(
                **{
                    **idempotency.__dict__,
                    'message_id': 'new-message',
                    'runtime_trace_id': 'new-trace',
                }
            ),
        )

    conflict_repository = FixtureRepository()
    conflict_repository.create_claim(claim, session)
    conflict_repository.save_idempotency(idempotency)
    with pytest.raises(IdempotencyConflict):
        conflict_repository.save_runtime_turn(
            claim,
            claim.revision,
            session,
            claimant_message,
            agent_message,
            trace,
            idempotency.__class__(
                **{
                    **idempotency.__dict__,
                    'request_fingerprint': 'different-fingerprint',
                }
            ),
        )


def test_logical_key_layout_keeps_provider_keys_outside_api_models() -> None:
    assert claim_key('clm_1').partition == 'CLAIM#clm_1'
    assert claim_key('clm_1').sort == 'CLAIM'
    assert session_key('clm_1', 'ses_1').sort == 'SESSION#ses_1'
    assert message_key('clm_1', '2026-08-11T00:00:00Z', 'msg_1').sort.startswith('MESSAGE#')
    assert decision_key('clm_1', '2026-08-11T00:00:00Z', 'dec_1').sort.startswith('DECISION#')
    assert evidence_key('clm_1', 'evd_1').sort == 'EVIDENCE#evd_1'
    assert customer_claim_index_key('cus_1', '2026-08-11T00:00:00Z', 'clm_1').partition == (
        'CUSTOMER#cus_1'
    )
