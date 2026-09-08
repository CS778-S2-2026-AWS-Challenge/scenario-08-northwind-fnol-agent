from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.branch_registry import validate_registered_field_value
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentProposalSource,
    AssertionRelation,
    AuthorityOutcome,
    Channel,
    CustomerNextStep,
    FactResolutionState,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    ProposedFormChange,
    ResponsibleParty,
    SessionRecord,
    StructuredFormField,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext
from backend.services.fact_resolution import (
    provenance_messages_for_fields,
    resolve_form_change,
)
from backend.services.messages import _apply_question_accounting, _build_form_changes

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=UTC)
CLAIMANT = ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_fact')
AUTH = {'Authorization': 'Bearer synthetic-claimant'}
SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def field(value: object, *, source_ref: str = 'msg_original') -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=[source_ref],
        status=FormStatus.CONFIRMED,
        needed_for=NeededFor.CURRENT_ACTION,
        confidence=1.0,
        updated_at=NOW,
        updated_by=CLAIMANT,
    )


def proposal(value: object, **updates: object) -> ProposedFormChange:
    return ProposedFormChange(
        field_code='incident.occurred_at',
        value=value,
        source=FormSource.CLAIMANT,
        status=FormStatus.CONFIRMED,
        **updates,
    )


def resolve(
    existing: StructuredFormField,
    candidate: ProposedFormChange,
    text: str,
) -> StructuredFormField:
    return resolve_form_change(
        field_code=candidate.field_code,
        existing=existing,
        proposal=candidate,
        source_ref='msg_update',
        message_text=text,
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=CLAIMANT,
    )


def test_equivalent_statement_preserves_resolution_without_false_conflict() -> None:
    resolved = resolve(field('around 8pm'), proposal(' around   8PM '), 'Around 8pm.')

    assert resolved.status is FormStatus.CONFIRMED
    assert resolved.resolution_state is FactResolutionState.RESOLVED
    assert resolved.value == 'around 8pm'
    assert resolved.source_refs == ['msg_original', 'msg_update']
    assert [item.relation for item in resolved.assertions] == [
        AssertionRelation.INITIAL,
        AssertionRelation.EQUIVALENT,
    ]


def test_explicit_correction_supersedes_prior_assertion() -> None:
    resolved = resolve(field('around 8pm'), proposal('9pm'), 'Actually, it was 9pm.')

    assert resolved.value == '9pm'
    assert resolved.status is FormStatus.CONFIRMED
    assert resolved.resolution_state is FactResolutionState.RESOLVED
    assert resolved.assertions[0].status is FormStatus.SUPERSEDED
    assert resolved.assertions[-1].relation is AssertionRelation.CORRECTION
    assert resolved.current_assertion_id == resolved.assertions[-1].assertion_id


def test_selecting_original_value_resolves_a_disputed_fact() -> None:
    disputed = resolve(field('around 8pm'), proposal('9pm'), 'Maybe it was 9pm.')

    resolved = resolve(disputed, proposal('around 8pm'), 'Use the original time, around 8pm.')

    assert resolved.value == 'around 8pm'
    assert resolved.status is FormStatus.CONFIRMED
    assert resolved.resolution_state is FactResolutionState.RESOLVED
    assert resolved.assertions[-1].relation is AssertionRelation.EQUIVALENT
    assert resolved.assertions[1].status is FormStatus.SUPERSEDED


def test_unmarked_material_change_remains_disputed() -> None:
    resolved = resolve(field('Symonds Street'), proposal('Queen Street'), 'Queen Street.')

    assert resolved.value == 'Symonds Street'
    assert resolved.status is FormStatus.DISPUTED
    assert resolved.resolution_state is FactResolutionState.CLARIFICATION_REQUIRED
    assert resolved.source_refs == ['msg_original', 'msg_update']
    assert resolved.assertions[-1].relation is AssertionRelation.MATERIAL_CONFLICT
    assert resolved.assertions[-1].reason_code == 'MATERIAL_VALUE_CONFLICT'


def test_temporal_contract_preserves_approximate_range_and_partial_values() -> None:
    for value in (
        {'time': '20:00', 'precision': 'approximate', 'reported_text': 'around 8pm'},
        {
            'date': '2026-09-07',
            'start': '20:00',
            'end': '21:00',
            'precision': 'range',
        },
        {'date': '2026-09', 'precision': 'partial'},
        {'reported_text': 'I do not know when', 'precision': 'unknown'},
    ):
        validate_registered_field_value('incident.occurred_at', value)

    with pytest.raises(ValueError, match='temporal'):
        validate_registered_field_value('incident.occurred_at', {})


def test_provenance_retrieval_uses_full_messages_only_for_unresolved_fields() -> None:
    repository = FixtureRepository()
    disputed = resolve(field('8pm'), proposal('9pm'), 'Maybe it was 9pm.')
    session = SessionRecord(
        session_id='ses_fact',
        claim_id='clm_fact',
        customer_id='cus_fact',
        started_at=NOW,
        last_active_at=NOW,
    )
    repository.create_claim(
        WorkingClaim(
            claim_id='clm_fact',
            customer_id='cus_fact',
            channel=Channel.WEB_AGENT,
            locale='en-NZ',
            customer_next_step=CustomerNextStep(
                status='describe_incident',
                summary='Describe the incident.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
            created_at=NOW,
            updated_at=NOW,
        ),
        session,
    )
    for message_id, text in (
        ('msg_original', 'It happened around 8pm after I left work.'),
        ('msg_update', 'Maybe it was 9pm, because the shop had already closed.'),
    ):
        repository.save_message(
            MessageRecord(
                message_id=message_id,
                claim_id='clm_fact',
                session_id='ses_fact',
                actor=ActorType.CLAIMANT,
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={'type': 'text', 'text': text},
                created_at=NOW,
            ),
            'cus_fact',
        )

    messages = provenance_messages_for_fields(
        repository,
        claim_id='clm_fact',
        customer_id='cus_fact',
        fields=[disputed],
    )

    assert [message.content['text'] for message in messages] == [
        'It happened around 8pm after I left work.',
        'Maybe it was 9pm, because the shop had already closed.',
    ]
    assert (
        provenance_messages_for_fields(
            repository,
            claim_id='clm_fact',
            customer_id='cus_fact',
            fields=[field('8pm')],
        )
        == []
    )


def asking_proposal(field_code: str) -> AgentProposal:
    next_step = CustomerNextStep(
        status='more_information_needed',
        summary='Provide the next incident detail.',
        responsible_party=ResponsibleParty.CLAIMANT,
        required_items=[field_code],
    )
    return AgentProposal(
        action=AgentAction.ASK,
        reason_codes=['MORE_INFORMATION_REQUIRED'],
        customer_reason=next_step.summary,
        customer_response='What happened next?',
        customer_next_step=next_step,
        form_changes=[],
        state_changes=[],
        proposed_signals=[],
        required_tools=[],
        next_action_requirements=[field_code],
    )


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
def test_question_budget_counts_repetition_and_stops_the_tenth_question(family: str) -> None:
    session = SessionRecord(
        session_id=f'ses_{family}',
        claim_id=f'clm_{family}',
        customer_id='cus_fact',
        question_budget=1,
        started_at=NOW,
        last_active_at=NOW,
    )
    next_step = asking_proposal('incident.location').customer_next_step
    session, _, _ = _apply_question_accounting(
        session,
        asking_proposal('incident.location'),
        next_step,
        'Where did it happen?',
        'msg_first',
        NOW,
    )
    exhausted, exhausted_step, response = _apply_question_accounting(
        session,
        asking_proposal('incident.location'),
        next_step,
        'Where did it happen?',
        'msg_second',
        NOW,
    )

    assert exhausted.question_turn_count == 1
    assert exhausted.requested_fact_count == 1
    assert exhausted.post_session_follow_up_required is True
    assert exhausted_step.status == 'question_budget_reached'
    assert '?' not in response


def test_question_accounting_marks_repeated_requested_fact() -> None:
    session = SessionRecord(
        session_id='ses_questions',
        claim_id='clm_questions',
        customer_id='cus_fact',
        started_at=NOW,
        last_active_at=NOW,
    )
    proposal_value = asking_proposal('incident.location')
    session, _, _ = _apply_question_accounting(
        session,
        proposal_value,
        proposal_value.customer_next_step,
        'Where did it happen?',
        'msg_first',
        NOW,
    )
    session, _, _ = _apply_question_accounting(
        session,
        proposal_value,
        proposal_value.customer_next_step,
        'Where did it happen?',
        'msg_second',
        NOW,
    )

    assert session.question_turn_count == 2
    assert session.requested_fact_count == 2
    assert session.repeated_question_count == 1
    assert session.question_history[-1].repeated is True


def test_runtime_ignores_irrelevant_change_to_confirmed_fact() -> None:
    existing = {'incident.location': field('Symonds Street')}
    message = MessageRecord(
        message_id='msg_guard',
        claim_id='clm_fact',
        session_id='ses_fact',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'I was talking about a different trip.'},
        created_at=NOW,
    )

    assert (
        _build_form_changes(
            existing,
            [
                ProposedFormChange(
                    field_code='incident.location',
                    value='Queen Street',
                    relation=AssertionRelation.IRRELEVANT,
                )
            ],
            message,
            NOW,
            authority_outcome=AuthorityOutcome.AUTHORISED,
            proposal_source=AgentProposalSource.MODEL_GATEWAY,
        )
        == {}
    )


class TemporalClaimantAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentTurnContext] = []

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        self.contexts.append(context)
        text = context.message_text or ''
        changes = []
        if '8pm' in text:
            changes.append(proposal('around 8pm'))
        elif '9pm' in text:
            changes.append(proposal('9pm'))
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['INCIDENT_TIME_RECORDED'],
            customer_reason='The reported time was recorded.',
            customer_response='I recorded that detail.',
            customer_next_step=context.claim.customer_next_step,
            form_changes=changes,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
        )


class RepeatingQuestionAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return asking_proposal('incident.location')


def _create_claim(client: TestClient, family: str, key: str) -> dict[str, Any]:
    response = client.post(
        '/api/v1/claims',
        headers={**AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': family},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _send(
    client: TestClient,
    claim_id: str,
    session_id: str,
    revision: int,
    text: str,
    key: str,
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
        json={
            'client_message_id': f'client-{key}',
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
def test_runtime_preserves_cross_session_conflict_and_recovers_full_provenance(
    family: str,
) -> None:
    repository = FixtureRepository()
    agent = TemporalClaimantAgent()
    with TestClient(create_app(SETTINGS, repository, agent)) as client:
        created = _create_claim(client, family, f'create-{family}')
        claim_id = str(created['claim']['claim_id'])
        session_id = str(created['session']['session_id'])
        first = _send(client, claim_id, session_id, 1, 'It happened around 8pm.', f'first-{family}')
        new_session = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': f'resume-{family}'},
            json={'intent': 'new'},
        )
        assert new_session.status_code == 201
        session_id = new_session.json()['session_id']
        second = _send(
            client,
            claim_id,
            session_id,
            int(first['claim_revision']) + 1,
            'Maybe it was 9pm.',
            f'second-{family}',
        )
        third = _send(
            client,
            claim_id,
            session_id,
            int(second['claim_revision']),
            'Can we resolve the time?',
            f'third-{family}',
        )

        claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH)

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    occurred_at = stored.form['incident.occurred_at']
    assert occurred_at.status is FormStatus.DISPUTED
    decisions = repository.list_agent_decisions(claim_id, 'cus_demo')
    assert decisions[-2].discrepancy_candidates[0].field_code == 'incident.occurred_at'
    assert [message.content['text'] for message in agent.contexts[-1].provenance_messages] == [
        'It happened around 8pm.',
        'Maybe it was 9pm.',
    ]
    assert third['agent_message']['content']['text'] == 'I recorded that detail.'
    assert claimant_view.status_code == 200
    assert 'discrepancy_candidates' not in claimant_view.text


def test_runtime_applies_explicit_claimant_correction_without_fraud_signal() -> None:
    repository = FixtureRepository()
    agent = TemporalClaimantAgent()
    with TestClient(create_app(SETTINGS, repository, agent)) as client:
        created = _create_claim(client, 'motor', 'create-correction')
        claim_id = str(created['claim']['claim_id'])
        session_id = str(created['session']['session_id'])
        first = _send(client, claim_id, session_id, 1, 'It happened around 8pm.', 'time-first')
        _send(
            client,
            claim_id,
            session_id,
            int(first['claim_revision']),
            'Actually, it was 9pm.',
            'time-correction',
        )

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    occurred_at = stored.form['incident.occurred_at']
    assert occurred_at.value == '9pm'
    assert occurred_at.resolution_state is FactResolutionState.RESOLVED
    assert occurred_at.assertions[-1].relation is AssertionRelation.CORRECTION
    assert repository.list_review_signals(claim_id, 'cus_demo') == []


def test_question_budget_is_persisted_across_a_restarted_claim_session() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository, RepeatingQuestionAgent())) as client:
        created = _create_claim(client, 'motor', 'create-budget')
        claim_id = str(created['claim']['claim_id'])
        session_id = str(created['session']['session_id'])
        revision = 1
        for index in range(5):
            turn = _send(
                client,
                claim_id,
                session_id,
                revision,
                'I still need help.',
                f'budget-before-{index}',
            )
            revision = int(turn['claim_revision'])

        resumed = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'restart-budget'},
            json={'intent': 'new'},
        )
        assert resumed.status_code == 201
        assert resumed.json()['resume']['question_turn_count'] == 5
        assert resumed.json()['resume']['remaining_question_budget'] == 4
        session_id = resumed.json()['session_id']
        revision += 1

        for index in range(5, 10):
            turn = _send(
                client,
                claim_id,
                session_id,
                revision,
                'I still need help.',
                f'budget-after-{index}',
            )
            revision = int(turn['claim_revision'])

    stored_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert stored_session is not None
    assert stored_session.question_turn_count == 9
    assert stored_session.repeated_question_count == 8
    assert stored_session.post_session_follow_up_required is True
    assert turn['decision']['customer_next_step']['status'] == 'question_budget_reached'
    assert '?' not in turn['agent_message']['content']['text']
