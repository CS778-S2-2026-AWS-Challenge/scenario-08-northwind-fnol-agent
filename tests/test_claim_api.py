from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from backend.adapters.policy_history import MockPolicyHistoryAdapter, ProviderLookupEnvelope
from backend.domain.models import (
    AgentAction,
    ClaimCreationStatus,
    ContentsLossType,
    ContentsOwnership,
    CustomerNextStep,
    ExternalClaimResult,
    FormSource,
    FormStatus,
    IntegrationSource,
    MessageRecord,
    MessageVisibility,
    ProposedContentsItem,
    ProposedFormChange,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    StateChange,
    WorkflowState,
)
from backend.domain.retrieval import ClaimHistoryRetrievalRecord, ClaimHistorySearchRequest
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext


class HighImpactAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return AgentProposal(
            action=AgentAction.CREATE_CLAIM,
            reason_codes=['CLAIM_CREATION_AUTHORISED'],
            customer_reason='A model proposed claim creation.',
            customer_response='I have enough confirmed information to propose claim creation.',
            customer_next_step=CustomerNextStep(
                status='claim_creation_proposed',
                summary='The claim is being created.',
                responsible_party=ResponsibleParty.SYSTEM,
            ),
            form_changes=[
                ProposedFormChange(
                    field_code='incident.description',
                    value=context.message_text,
                    status=FormStatus.CONFIRMED,
                )
            ],
            state_changes=[StateChange(path='claim_state.next_action', to='CREATE_CLAIM')],
            proposed_signals=[],
            required_tools=[{'tool': 'claim_creation', 'status': 'requested'}],
            next_action_requirements=[],
        )


class OtherPartyAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['OTHER_PARTY_RECORDED'],
            customer_reason='The claimant reported another party.',
            customer_response='I have recorded that another party was involved.',
            customer_next_step=context.claim.customer_next_step,
            form_changes=[
                ProposedFormChange(
                    field_code='parties.other_parties',
                    value=True,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.CONFIRMED,
                )
            ],
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
        )


class ClaimHistoryLookupAgent:
    def __init__(self, tool: dict[str, object]) -> None:
        self._tool = tool

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['ADDITIONAL_CONTEXT_RECORDED'],
            customer_reason='A history lookup is needed for this synthetic turn.',
            customer_response='I will check the relevant claim history.',
            customer_next_step=context.claim.customer_next_step,
            form_changes=[],
            state_changes=[],
            proposed_signals=[],
            required_tools=[
                {
                    'tool': 'claim_history',
                    'operation': 'search_claim_history',
                    **self._tool,
                }
            ],
            next_action_requirements=[],
        )


class ContentsCorrectionAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        current = context.claim.contents_items[0] if context.claim.contents_items else None
        message_text = context.message_text or ''
        loss_type = (
            ContentsLossType.STOLEN
            if 'stolen' in message_text.casefold()
            else ContentsLossType.DAMAGED
        )
        return AgentProposal(
            action=AgentAction.CONFIRM,
            reason_codes=['CONTENTS_ITEM_REVIEW_REQUIRED'],
            customer_reason='The contents item needs claimant confirmation.',
            customer_response='Please check the item details before I continue.',
            customer_next_step=CustomerNextStep(
                status='confirmation_required',
                summary='Check the contents item.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=['contents.items'],
            ),
            form_changes=[],
            contents_item_changes=[
                ProposedContentsItem(
                    item_id=current.item_id if current is not None else None,
                    description='Laptop computer',
                    category='electronics',
                    quantity=1,
                    loss_type=loss_type,
                    ownership=ContentsOwnership.OWNED,
                    confidence=1.0,
                    reported_text=message_text.rstrip('.'),
                )
            ],
            state_changes=[StateChange(path='claim_state.next_action', to='CONFIRM')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['contents.items'],
        )


class CompleteVpPathAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        family = context.claim.incident_type
        if family not in {'motor', 'home', 'contents'}:
            raise AssertionError('The VP path test requires one selected family.')
        values: dict[str, object] = {
            'claim.product_family': family,
            'incident.description': context.message_text,
            'incident.injury_or_danger': False,
            'incident.occurred_at': '2026-09-08 at approximately 09:30 NZST',
            'incident.location': '10 Example Street, Auckland',
            'loss.description': 'The insured property was damaged.',
        }
        values.update(
            {
                'motor': {
                    'vehicle.damage_description': 'The rear bumper is dented.',
                    'vehicle.drivable': True,
                },
                'home': {
                    'property.address': '10 Example Street, Auckland',
                    'property.affected_areas': ['kitchen', 'hallway'],
                    'property.ongoing_risk': 'none',
                    'property.habitable': True,
                },
                'contents': {},
            }[family]
        )
        contents = (
            [
                ProposedContentsItem(
                    description='Laptop computer',
                    category='electronics',
                    quantity=1,
                    loss_type=ContentsLossType.DAMAGED,
                    ownership=ContentsOwnership.OWNED,
                    confidence=1.0,
                    reported_text='My laptop was damaged.',
                )
            ]
            if family == 'contents'
            else []
        )
        confirmation_items = [*values, *(['contents.items'] if contents else [])]
        return AgentProposal(
            action=AgentAction.CONFIRM,
            reason_codes=['VP_PATH_FACTS_PROPOSED'],
            customer_reason='The reported facts require claimant confirmation.',
            customer_response='Please review the facts before Northwind creates the claim.',
            customer_next_step=CustomerNextStep(
                status='confirmation_required',
                summary='Review the reported facts.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=confirmation_items,
            ),
            form_changes=[
                ProposedFormChange(
                    field_code=field_code,
                    value=value,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.PROPOSED,
                    confidence=1.0,
                    reported_text=context.message_text,
                )
                for field_code, value in values.items()
            ],
            contents_item_changes=contents,
            state_changes=[StateChange(path='claim_state.next_action', to='CONFIRM')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=confirmation_items,
        )


class QuestionAndFactAgent:
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return AgentProposal(
            action=AgentAction.ASK,
            reason_codes=['INCIDENT_LOCATION_REQUIRED'],
            customer_reason='The incident location is still needed.',
            customer_response='Where did the incident happen?',
            customer_next_step=CustomerNextStep(
                status='provide_incident_location',
                summary='Tell us where the incident happened.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=['incident.location'],
            ),
            form_changes=[
                ProposedFormChange(
                    field_code='incident.description',
                    value=context.message_text,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.PROPOSED,
                    confidence=1.0,
                    reported_text=context.message_text,
                )
            ],
            state_changes=[StateChange(path='claim_state.next_action', to='ASK')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['incident.location'],
        )


class SpyPolicyHistoryAdapter(MockPolicyHistoryAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.history_calls = 0

    def search_claim_history(self, command: ClaimHistorySearchRequest) -> ProviderLookupEnvelope:
        self.history_calls += 1
        return super().search_claim_history(command)


def create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str = 'claim-1',
    *,
    incident_type: str = 'motor',
) -> Response:
    headers = {**auth_headers, 'Idempotency-Key': key}
    return client.post(
        '/api/v1/claims',
        headers=headers,
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': incident_type},
    )


def submit_message(
    client: TestClient,
    auth_headers: dict[str, str],
    claim_id: str,
    session_id: str,
    *,
    revision: int = 1,
    key: str = 'message-1',
    client_message_id: str = 'client-message-1',
    text: str = 'A synthetic rear-end incident. Nobody was injured.',
) -> Response:
    return client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': key,
            'If-Match': str(revision),
        },
        json={
            'client_message_id': client_message_id,
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )


def test_create_claim_returns_claim_and_first_session(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = create_claim(client, auth_headers)

    assert response.status_code == 201
    payload = response.json()
    claim = payload['claim']
    session = payload['session']
    assert claim['claim_id'].startswith('clm_')
    assert claim['revision'] == 1
    assert claim['workflow_state'] == 'collecting'
    assert claim['form'] == {}
    assert claim['customer_next_step']['status'] == 'describe_incident'
    assert session['session_id'].startswith('ses_')
    assert session['claim_id'] == claim['claim_id']
    assert session['status'] == 'active'
    assert 'customer_id' not in claim
    assert 'fraud_signal' not in claim


@pytest.mark.parametrize('incident_type', ['home', 'contents'])
def test_cross_path_other_party_proposal_passes_branch_validation(
    client: TestClient,
    app: FastAPI,
    auth_headers: dict[str, str],
    incident_type: str,
) -> None:
    app.state.agent_turn_provider = OtherPartyAgent()
    created = create_claim(
        client,
        auth_headers,
        key=f'{incident_type}-other-party',
        incident_type=incident_type,
    ).json()

    turn = submit_message(
        client,
        auth_headers,
        created['claim']['claim_id'],
        created['session']['session_id'],
        key=f'{incident_type}-other-party-turn',
        client_message_id=f'{incident_type}-other-party-message',
        text='Another person was involved in this loss.',
    )

    assert turn.status_code == 200, turn.text
    other_party = next(
        item
        for item in turn.json()['form_changes']
        if item['field_code'] == 'parties.other_parties'
    )
    assert other_party['field']['value'] is True
    assert other_party['field']['status'] == 'confirmed'


@pytest.mark.parametrize(
    ('family', 'message'),
    [
        (
            'motor',
            'Another car hit mine in Auckland this morning. The rear bumper is damaged, '
            'the car is drivable, and nobody is injured.',
        ),
        (
            'home',
            'A pipe leaked at my Auckland home this morning. The kitchen and hallway are '
            'damaged, the leak is stopped, and the house is safe to live in.',
        ),
        (
            'contents',
            'My laptop was damaged at home in Auckland this morning. Nobody was injured.',
        ),
    ],
)
def test_vp_family_journey_confirms_registered_facts_and_creates_claim(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    family: str,
    message: str,
) -> None:
    app.state.agent_turn_provider = CompleteVpPathAgent()
    created = create_claim(
        client,
        auth_headers,
        key=f'{family}-vp-journey',
        incident_type=family,
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        key=f'{family}-vp-intake',
        client_message_id=f'{family}-vp-message',
        text=message,
    )

    assert turn.status_code == 200, turn.text
    turn_body = turn.json()
    assert turn_body['dynamic_form']['selected_family'] == family
    requirements = turn_body['dynamic_form']['requirements']
    assert requirements['current_action_total'] > 0
    assert 0 <= requirements['current_action_satisfied'] <= requirements['current_action_total']
    assert turn_body['decision']['customer_next_step']['required_items']
    assert turn_body['decision']['customer_next_step']['status'] == 'confirmation_required'
    confirmation_items = [item['field_code'] for item in turn_body['form_changes']]
    if family == 'contents':
        confirmation_items.append('contents.items')
        assert len(turn_body['contents_item_changes']) == 1

    confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{family}-vp-confirm',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': confirmation_items},
    )

    assert confirmation.status_code == 200, confirmation.text
    confirmed = confirmation.json()
    assert confirmed['dynamic_form']['requirements']['ready'] is True
    assert confirmed['dynamic_form']['requirements']['missing_required_now'] == []
    assert confirmed['customer_next_step']['status'] == 'ready_to_create'

    external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{family}-vp-create',
            'If-Match': str(confirmed['revision']),
        },
    )

    assert external.status_code == 201, external.text
    external_body = external.json()
    assert external_body['external_claim']['route'] == f'standard_{family}_intake'
    assert external_body['external_claim']['creation_status'] == 'created'
    claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert claimant_view['workflow_state'] == 'created'
    assert claimant_view['dynamic_form']['requirements']['ready'] is True
    final_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert final_session is not None
    assert final_session.repeated_question_count == 0
    if family == 'contents':
        assert claimant_view['contents_items'][0]['description'] == 'Laptop computer'


def test_default_home_journey_creates_without_an_unapproved_external_service(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    message_text = (
        'A pipe leaked at my Auckland home this morning. The kitchen and hallway are '
        'damaged, the leak is stopped, and the house is safe to live in. Nobody was injured.'
    )
    created = create_claim(
        client,
        auth_headers,
        key='home-default-runtime',
        incident_type='home',
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        key='home-default-runtime-message',
        client_message_id='home-default-runtime-message',
        text=message_text,
    )

    assert turn.status_code == 200, turn.text
    turn_body = turn.json()
    proposed_fields = [
        change['field_code']
        for change in turn_body['form_changes']
        if change['field']['status'] == 'proposed'
    ]
    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'home-default-runtime-confirm',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': proposed_fields},
    )

    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    remaining_values = {
        'incident.injury_or_danger': False,
        'incident.location': '10 Example Street, Auckland',
        'property.address': '10 Example Street, Auckland',
        'property.affected_areas': ['kitchen', 'hallway'],
        'property.ongoing_risk': 'none',
        'property.habitable': True,
    }
    assert set(confirmed_body['dynamic_form']['requirements']['missing_required_now']) == set(
        remaining_values
    )
    completed = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed_body['revision'])},
        json={
            'updates': [
                {'field_code': field_code, 'value': value, 'status': 'confirmed'}
                for field_code, value in remaining_values.items()
            ]
        },
    )

    assert completed.status_code == 200, completed.text
    completed_body = completed.json()
    assert completed_body['dynamic_form']['requirements']['ready'] is True
    creation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'home-default-runtime-create',
            'If-Match': str(completed_body['revision']),
        },
    )

    assert creation.status_code == 201, creation.text
    assert creation.json()['external_claim']['route'] == 'standard_home_intake'
    assert creation.json()['external_service_action'] is None
    claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert claimant_view['workflow_state'] == 'created'
    assert claimant_view['external_service_action'] is None
    assert repository.list_external_tasks_internal(claim_id) == []
    assert repository.list_external_task_requests_internal(claim_id) == []


def test_default_contents_journey_preserves_the_report_without_inventing_a_provider(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    first_message = 'My laptop was damaged at home in Auckland this morning. Nobody was injured.'
    second_message = 'The damaged item is my laptop.'
    created = create_claim(
        client,
        auth_headers,
        key='contents-default-runtime',
        incident_type='contents',
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        key='contents-default-runtime-message',
        client_message_id='contents-default-runtime-message',
        text=first_message,
    )

    assert turn.status_code == 200, turn.text
    turn_body = turn.json()
    assert turn_body['contents_item_changes'] == []
    proposed_fields = [
        change['field_code']
        for change in turn_body['form_changes']
        if change['field']['status'] == 'proposed'
    ]
    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'contents-default-runtime-confirm',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': proposed_fields},
    )

    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    assert confirmed_body['dynamic_form']['requirements']['missing_required_now'] == [
        'incident.injury_or_danger',
        'contents.items',
    ]
    completed_form = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed_body['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'incident.injury_or_danger',
                    'value': False,
                    'status': 'confirmed',
                }
            ]
        },
    )

    assert completed_form.status_code == 200, completed_form.text
    completed_body = completed_form.json()
    assert completed_body['dynamic_form']['requirements']['missing_required_now'] == [
        'contents.items'
    ]
    missing_item_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=completed_body['revision'],
        key='contents-default-runtime-item',
        client_message_id='contents-default-runtime-item',
        text=second_message,
    )

    assert missing_item_turn.status_code == 200, missing_item_turn.text
    missing_item_body = missing_item_turn.json()
    assert missing_item_body['decision']['action'] == 'ASK'
    assert missing_item_body['decision']['customer_next_step']['required_items'] == [
        'contents.items'
    ]
    assert missing_item_body['contents_item_changes'] == []
    creation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'contents-default-runtime-create',
            'If-Match': str(missing_item_body['claim_revision']),
        },
    )

    assert creation.status_code == 409
    assert [detail['field'] for detail in creation.json()['error']['details']] == ['contents.items']
    claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert claimant_view['workflow_state'] == 'collecting'
    assert claimant_view['dynamic_form']['requirements']['missing_required_now'] == [
        'contents.items'
    ]
    assert claimant_view['external_service_action'] is None
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.contents_items == []
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert session is not None
    assert session.status is SessionStatus.ACTIVE
    claimant_messages = [
        message.content['text']
        for message in repository.list_messages(claim_id, session_id, 'cus_demo')
        if message.actor.value == 'claimant'
    ]
    assert claimant_messages == [first_message, second_message]
    assert repository.list_external_tasks_internal(claim_id) == []
    assert repository.list_external_task_requests_internal(claim_id) == []


def test_question_accounting_and_provenance_survive_a_new_session(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = QuestionAndFactAgent()
    created = create_claim(client, auth_headers, key='question-resume').json()
    claim_id = created['claim']['claim_id']
    first_session_id = created['session']['session_id']
    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        first_session_id,
        key='question-resume-turn',
        client_message_id='question-resume-message',
        text='My car was damaged, but I have not said where yet.',
    )

    assert turn.status_code == 200, turn.text
    turn_body = turn.json()
    first_session = repository.get_session(claim_id, first_session_id, 'cus_demo')
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert first_session is not None
    assert stored_claim is not None
    assert first_session.question_turn_count == 1
    assert first_session.requested_fact_count == 1
    assert first_session.repeated_question_count == 0
    assert first_session.question_history[0].field_codes == ['incident.location']
    assert (
        first_session.question_history[0].trigger_message_id
        == turn_body['claimant_message']['message_id']
    )
    assert stored_claim.form['incident.description'].source_refs == [
        turn_body['claimant_message']['message_id']
    ]

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'question-resume-new-session'},
        json={'intent': 'new'},
    )

    assert resumed.status_code == 201, resumed.text
    resume_body = resumed.json()
    assert resume_body['session_id'] != first_session_id
    assert resume_body['resume']['question_turn_count'] == 1
    assert resume_body['resume']['requested_fact_count'] == 1
    assert resume_body['resume']['remaining_question_budget'] == 8
    assert 'question_history' not in resume_body['resume']
    latest_claim = repository.get_claim(claim_id, 'cus_demo')
    assert latest_claim is not None
    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'question-resume-support',
            'If-Match': str(latest_claim.revision),
        },
        json={
            'reason': 'I need a claims professional to help me continue.',
            'support_need': 'human_requested',
            'preferred_channel': 'in_app',
        },
    )
    assert support.status_code == 201, support.text
    staff_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}/sessions', headers=staff_auth_headers
    )
    assert staff_response.status_code == 200, staff_response.text
    staff_sessions = staff_response.json()['items']
    active_staff_session = next(
        item for item in staff_sessions if item['session_id'] == resume_body['session_id']
    )
    assert active_staff_session['question_history'][0]['field_codes'] == ['incident.location']
    assert (
        active_staff_session['question_history'][0]['trigger_message_id']
        == turn_body['claimant_message']['message_id']
    )


def test_question_budget_stops_additional_agent_questions_and_requests_follow_up(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = QuestionAndFactAgent()
    created = create_claim(client, auth_headers, key='question-budget').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert session is not None
    repository.save_session(
        session.model_copy(
            update={
                'question_budget': 1,
            }
        )
    )

    first = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        key='question-budget-first',
        client_message_id='question-budget-first',
        text='My car was damaged.',
    )
    second = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=first.json()['claim_revision'],
        key='question-budget-second',
        client_message_id='question-budget-second',
        text='I still need help describing the incident.',
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body['decision']['customer_next_step']['status'] == 'question_budget_reached'
    assert 'saved' in second_body['agent_message']['content']['text'].casefold()
    final_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert final_session is not None
    assert final_session.question_turn_count == 1
    assert final_session.requested_fact_count == 1
    assert final_session.repeated_question_count == 0
    assert final_session.post_session_follow_up_required is True
    session_view = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}', headers=auth_headers
    ).json()
    assert session_view['resume']['remaining_question_budget'] == 0
    assert session_view['resume']['post_session_follow_up_required'] is True


def test_form_patch_rejects_an_incompatible_registered_field_shape(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, key='invalid-other-party-shape').json()

    response = client.patch(
        f'/api/v1/claims/{created["claim"]["claim_id"]}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={
            'updates': [
                {
                    'field_code': 'parties.other_parties',
                    'value': ['unbounded participant data'],
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert response.json()['error']['details'][0]['field'] == 'parties.other_parties'


def test_applied_message_evaluation_retains_message_branch_candidates(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-branch-candidates').json()
    claim_id = created['claim']['claim_id']

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        created['session']['session_id'],
        key='message-branch-candidates-turn',
        client_message_id='message-branch-candidates-client',
        text='Another car hit my house and Police attended.',
    )

    assert turn.status_code == 200, turn.text
    turn_body = turn.json()
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    applied = evaluations[-1]
    branch_results = {item.branch_id: item for item in applied.branch_results}
    claimant_message_id = turn_body['claimant_message']['message_id']

    assert applied.resulting_claim_revision == turn_body['claim_revision']
    for branch_id in (
        'incident.collision',
        'participant.another_party',
        'authority.police',
    ):
        assert branch_results[branch_id].status in {'candidate', 'active'}
        assert claimant_message_id in branch_results[branch_id].source_refs


def test_claim_read_carries_the_latest_dynamic_form_to_the_current_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='read-dynamic-form').json()
    claim_id = created['claim']['claim_id']
    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        created['session']['session_id'],
        key='read-dynamic-form-turn',
        client_message_id='read-dynamic-form-client',
        text='Another car hit mine.',
    ).json()
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    unrelated_revision = stored.model_copy(
        update={
            'revision': stored.revision + 1,
            'updated_at': stored.updated_at + timedelta(seconds=1),
        }
    )
    repository.save_claim(unrelated_revision, expected_revision=stored.revision)

    response = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert response.status_code == 200
    projection = response.json()['dynamic_form']
    assert projection is not None
    assert projection['claim_revision'] == unrelated_revision.revision
    assert projection['field_registry_version'] == turn['dynamic_form']['field_registry_version']
    assert projection['branch_rules_version'] == turn['dynamic_form']['branch_rules_version']
    assert projection['fields'] == turn['dynamic_form']['fields']


def test_create_claim_is_idempotent_and_conflicting_reuse_is_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    first = create_claim(client, auth_headers, key='retry-1')
    second = create_claim(client, auth_headers, key='retry-1')
    conflicting = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'retry-1'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'home'},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()['claim']['claim_id'] == first.json()['claim']['claim_id']
    assert conflicting.status_code == 409
    assert conflicting.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_read_claim_and_session_use_same_fixture_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']
    session = created.json()['session']

    read_claim = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=auth_headers)
    read_session = client.get(
        f'/api/v1/claims/{claim["claim_id"]}/sessions/{session["session_id"]}',
        headers=auth_headers,
    )

    assert read_claim.status_code == 200
    assert read_claim.json()['claim_id'] == claim['claim_id']
    assert read_claim.json()['dynamic_form'] is None
    assert read_session.status_code == 200
    assert read_session.json()['session_id'] == session['session_id']
    assert read_session.json()['resume']['unresolved_questions'] == []


def test_start_session_requires_idempotency_and_reuses_active_session(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']
    first_session = created.json()['session']

    missing_key = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions',
        headers=auth_headers,
        json={'intent': 'resume'},
    )
    resumed = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'session-1'},
        json={'intent': 'resume'},
    )

    assert missing_key.status_code == 400
    assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'
    assert resumed.status_code == 201
    assert resumed.json()['session_id'] == first_session['session_id']


def test_form_update_records_registered_field_and_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']

    response = client.patch(
        f'/api/v1/claims/{claim["claim_id"]}/form',
        headers={**auth_headers, 'If-Match': '"1"'},
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': 'A rear-end collision.',
                    'status': 'confirmed',
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()['revision'] == 2
    assert response.json()['updated_fields']['incident.description']['source'] == 'claimant'
    assert (
        response.json()['updated_fields']['incident.description']['updated_by']['actor_id']
        == 'cus_demo'
    )
    evaluations = repository.list_branch_evaluations(claim['claim_id'], 'cus_demo')
    assert evaluations[-1].evaluated_against_claim_revision == 2
    assert evaluations[-1].resulting_claim_revision == 2
    assert evaluations[-1].recomputation_reason == 'form_updated'


def test_form_update_rejects_stale_revision_unknown_field_and_silent_overwrite(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    update_url = f'/api/v1/claims/{claim_id}/form'
    first = {
        'updates': [
            {'field_code': 'incident.description', 'value': 'First description'},
        ]
    }
    client.patch(update_url, headers={**auth_headers, 'If-Match': '1'}, json=first)

    stale = client.patch(update_url, headers={**auth_headers, 'If-Match': '1'}, json=first)
    unknown = client.patch(
        update_url,
        headers={**auth_headers, 'If-Match': '2'},
        json={'updates': [{'field_code': 'invented.field', 'value': 'x'}]},
    )
    overwrite = client.patch(
        update_url,
        headers={**auth_headers, 'If-Match': '2'},
        json={'updates': [{'field_code': 'incident.description', 'value': 'Changed'}]},
    )

    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == 2
    assert unknown.status_code == 422
    assert unknown.json()['error']['code'] == 'VALIDATION_ERROR'
    assert overwrite.status_code == 409
    assert overwrite.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


def test_claim_routes_require_the_synthetic_claimant_token(client: TestClient) -> None:
    response = client.post(
        '/api/v1/claims',
        headers={'Idempotency-Key': 'unauthenticated'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_claimant_can_start_an_anonymous_browser_session(client: TestClient) -> None:
    anonymous_session = str(uuid4())
    response = client.post(
        '/api/v1/claims',
        headers={
            'X-Northwind-Anonymous-Session': anonymous_session,
            'Idempotency-Key': f'anonymous-{anonymous_session}',
        },
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )

    assert response.status_code == 201
    assert response.json()['claim']['claim_id']
    assert response.json()['session']['claim_id'] == response.json()['claim']['claim_id']


def test_claim_creation_rejects_missing_and_overlong_idempotency_keys(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    missing = client.post(
        '/api/v1/claims',
        headers=auth_headers,
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    overlong = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'x' * 201},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )

    assert missing.status_code == 400
    assert missing.json()['error']['code'] == 'VALIDATION_ERROR'
    assert overlong.status_code == 400
    assert overlong.json()['error']['code'] == 'VALIDATION_ERROR'


def test_form_update_requires_a_valid_if_match_header(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    update_url = f'/api/v1/claims/{claim_id}/form'
    body = {'updates': [{'field_code': 'incident.description', 'value': 'A description'}]}

    missing = client.patch(update_url, headers=auth_headers, json=body)
    malformed = client.patch(update_url, headers={**auth_headers, 'If-Match': 'bad'}, json=body)

    assert missing.status_code == 409
    assert missing.json()['error']['code'] == 'REVISION_REQUIRED'
    assert malformed.status_code == 409
    assert malformed.json()['error']['code'] == 'REVISION_REQUIRED'


def test_claim_and_session_reads_return_not_found_for_unknown_resources(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claim = client.get('/api/v1/claims/clm_missing', headers=auth_headers)
    session = client.get(
        '/api/v1/claims/clm_missing/sessions/ses_missing',
        headers=auth_headers,
    )

    assert claim.status_code == 404
    assert claim.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert session.status_code == 404
    assert session.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_resumed_session_idempotency_replays_and_rejects_conflicting_payload(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    endpoint = f'/api/v1/claims/{claim_id}/sessions'
    headers = {**auth_headers, 'Idempotency-Key': 'resume-1'}

    first = client.post(endpoint, headers=headers, json={'intent': 'resume'})
    replay = client.post(endpoint, headers=headers, json={'intent': 'resume'})
    conflict = client.post(endpoint, headers=headers, json={'intent': 'handoff'})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()['session_id'] == first.json()['session_id']
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_message_turn_persists_messages_proposed_field_and_validated_action(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-turn').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    response = submit_message(client, auth_headers, claim_id, session_id)

    assert response.status_code == 200
    body = response.json()
    assert body['claim_revision'] == 2
    assert body['claimant_message']['actor'] == 'claimant'
    assert body['agent_message']['actor'] == 'agent'
    assert body['agent_message']['in_reply_to'] == body['claimant_message']['message_id']
    assert body['form_changes'][0]['field_code'] == 'incident.description'
    assert body['form_changes'][0]['field']['status'] == 'proposed'
    assert body['form_changes'][0]['field']['source_refs'] == [
        body['claimant_message']['message_id']
    ]
    assert body['decision']['action'] == 'CONFIRM'
    assert 'authority' not in body['decision']

    decision = repository.find_agent_decision_for_trigger(
        claim_id,
        body['claimant_message']['message_id'],
        'cus_demo',
    )
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert decision is not None
    assert decision.authority.outcome.value == 'authorised'
    assert decision.reason_codes == ['MATERIAL_FACTS_PROPOSED']
    assert claim is not None
    assert claim.form['incident.description'].status.value == 'proposed'
    assert claim.claim_state.next_action.value == 'CONFIRM'


def test_high_impact_agent_proposal_is_recorded_but_not_executed(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = HighImpactAgent()
    created = create_claim(client, auth_headers, key='high-impact-turn').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    response = submit_message(client, auth_headers, claim_id, session_id)

    assert response.status_code == 200
    body = response.json()
    assert body['decision']['action'] == 'CREATE_CLAIM'
    assert body['decision']['customer_next_step']['status'] == 'professional_review_required'
    assert body['form_changes'][0]['field']['status'] == 'proposed'
    decision = repository.find_agent_decision_for_trigger(
        claim_id,
        body['claimant_message']['message_id'],
        'cus_demo',
    )
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert decision is not None
    assert decision.authority.outcome.value == 'review_required'
    assert claim is not None
    assert claim.claim_state.next_action.value == 'ASK'
    assert claim.external_claim is None


def test_agent_claim_history_lookup_is_persisted_without_advancing_revision(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = ClaimHistoryLookupAgent(
        {
            'history_reference': 'synthetic-history-204',
        }
    )
    created = create_claim(client, auth_headers, key='history-lookup-turn').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    response = submit_message(client, auth_headers, claim_id, session_id)

    assert response.status_code == 200
    body = response.json()
    assert body['claim_revision'] == 2
    records = repository.list_retrieval_records(claim_id, 'cus_demo')
    history_records = [
        record for record in records if isinstance(record, ClaimHistoryRetrievalRecord)
    ]
    assert len(history_records) == 1
    assert history_records[0].facts.history_reference == 'synthetic-history-204'
    assert history_records[0].source.system == 'fixture_claims_history'

    replay = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=2,
        key='history-lookup-replay',
        client_message_id='history-lookup-replay',
    )
    assert replay.status_code == 200
    assert (
        len(
            [
                record
                for record in repository.list_retrieval_records(claim_id, 'cus_demo')
                if isinstance(record, ClaimHistoryRetrievalRecord)
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    'tool',
    [
        {'history_reference': []},
        {'history_reference': {}},
        {'history_reference': '   '},
        {'history_reference': 'synthetic-history-204', 'limit': None},
        {'history_reference': 'synthetic-history-204', 'limit': '10'},
        {'history_reference': 'synthetic-history-204', 'limit': 2.5},
        {'history_reference': 'synthetic-history-204', 'limit': True},
        {'history_reference': 'synthetic-history-204', 'limit': 0},
        {'history_reference': 'synthetic-history-204', 'limit': 51},
    ],
)
def test_invalid_claim_history_tool_arguments_fail_atomically(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    tool: dict[str, object],
) -> None:
    adapter = SpyPolicyHistoryAdapter()
    app.state.policy_history_adapter = adapter
    app.state.agent_turn_provider = ClaimHistoryLookupAgent(tool)
    created = create_claim(client, auth_headers, key='invalid-history-tool').json()
    before_claim = repository.get_claim(created['claim']['claim_id'], 'cus_demo')
    assert before_claim is not None

    response = submit_message(
        client,
        auth_headers,
        created['claim']['claim_id'],
        created['session']['session_id'],
    )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'AGENT_TOOL_NOT_PERMITTED'
    assert adapter.history_calls == 0
    assert repository.list_retrieval_records(created['claim']['claim_id'], 'cus_demo') == []
    assert (
        repository.list_messages(
            created['claim']['claim_id'], created['session']['session_id'], 'cus_demo'
        )
        == []
    )
    assert repository.list_agent_decisions(created['claim']['claim_id'], 'cus_demo') == []
    assert repository.get_claim(created['claim']['claim_id'], 'cus_demo') == before_claim


def test_message_turn_deduplicates_retries_and_rejects_conflicting_client_id(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-dedup').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    first = submit_message(client, auth_headers, claim_id, session_id, key='turn-a')
    idempotency_replay = submit_message(client, auth_headers, claim_id, session_id, key='turn-a')
    client_id_replay = submit_message(client, auth_headers, claim_id, session_id, key='turn-b')
    conflict = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=2,
        key='turn-c',
        text='Different content with the same client ID.',
    )

    assert first.status_code == 200
    assert idempotency_replay.json() == first.json()
    assert client_id_replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert len(repository.list_messages(claim_id, session_id, 'cus_demo')) == 2


def test_form_confirmation_and_explicit_correction_preserve_source_and_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='confirm-field').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    message = submit_message(client, auth_headers, claim_id, session_id).json()
    endpoint = f'/api/v1/claims/{claim_id}/form/confirmations'

    confirmed = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-1',
            'If-Match': str(message['claim_revision']),
        },
        json={'field_codes': ['incident.description']},
    )
    silent_overwrite = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed.json()['revision'])},
        json={
            'updates': [{'field_code': 'incident.description', 'value': 'A changed description.'}]
        },
    )
    explicit_correction = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed.json()['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': 'A corrected synthetic description.',
                    'correction_reason': 'The first description was incomplete.',
                }
            ]
        },
    )
    replay = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-1',
            'If-Match': str(message['claim_revision']),
        },
        json={'field_codes': ['incident.description']},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()['revision'] == 3
    assert confirmed.json()['confirmed_fields']['incident.description']['status'] == 'confirmed'
    assert silent_overwrite.status_code == 409
    assert explicit_correction.status_code == 200
    assert explicit_correction.json()['revision'] == 4
    corrected = explicit_correction.json()['updated_fields']['incident.description']
    assert corrected['source'] == 'claimant'
    assert corrected['updated_by']['actor_id'] == 'cus_demo'
    assert replay.json() == confirmed.json()
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    assert [item.recomputation_reason for item in evaluations[-2:]] == [
        'form_confirmed',
        'form_updated',
    ]
    assert evaluations[-1].resulting_claim_revision == 4


def test_contents_item_confirmation_and_natural_language_correction_preserve_history(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = ContentsCorrectionAgent()
    created = create_claim(
        client,
        auth_headers,
        key='contents-correction-claim',
        incident_type='contents',
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    proposed = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=1,
        key='contents-item-proposal',
        client_message_id='contents-item-proposal',
        text='My owned laptop was damaged.',
    )
    assert proposed.status_code == 200, proposed.text
    first_turn = proposed.json()
    first_item = first_turn['contents_item_changes'][0]
    assert first_item['status'] == 'proposed'
    assert first_item['resolution_state'] == 'needs_confirmation'

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-contents-item',
            'If-Match': str(first_turn['claim_revision']),
        },
        json={'field_codes': ['contents.items']},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['confirmed_contents_items'][0]['resolution_state'] == 'resolved'

    corrected = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=confirmed.json()['revision'],
        key='contents-item-correction',
        client_message_id='contents-item-correction',
        text='Actually, the laptop was stolen, not damaged.',
    )
    assert corrected.status_code == 200, corrected.text
    corrected_turn = corrected.json()
    corrected_item = corrected_turn['contents_item_changes'][0]
    assert corrected_item['item_id'] == first_item['item_id']
    assert corrected_item['loss_type'] == 'stolen'
    assert corrected_item['status'] == 'proposed'

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert len(stored.contents_items) == 1
    assert stored.contents_items[0].item_id == first_item['item_id']
    assert [assertion.relation.value for assertion in stored.contents_items[0].assertions] == [
        'initial',
        'correction',
    ]
    assert [assertion.status.value for assertion in stored.contents_items[0].assertions] == [
        'superseded',
        'proposed',
    ]

    reconfirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'reconfirm-contents-item',
            'If-Match': str(corrected_turn['claim_revision']),
        },
        json={'field_codes': ['contents.items']},
    )
    assert reconfirmed.status_code == 200, reconfirmed.text
    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    final_item = final_claim.contents_items[0]
    assert final_item.status is FormStatus.CONFIRMED
    assert final_item.assertions[-1].status is FormStatus.CONFIRMED

    conflicted = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=reconfirmed.json()['revision'],
        key='contents-item-conflict',
        client_message_id='contents-item-conflict',
        text='The laptop was damaged.',
    )
    assert conflicted.status_code == 200, conflicted.text
    conflict_turn = conflicted.json()
    assert conflict_turn['decision']['customer_next_step']['status'] == 'clarification_needed'
    assert conflict_turn['decision']['customer_next_step']['required_items'] == ['contents.items']
    stored_after_conflict = repository.get_claim(claim_id, 'cus_demo')
    assert stored_after_conflict is not None
    assert len(stored_after_conflict.contents_items) == 1
    disputed_item = stored_after_conflict.contents_items[0]
    assert disputed_item.status is FormStatus.DISPUTED
    assert disputed_item.assertions[-1].relation.value == 'material_conflict'
    assert disputed_item.assertions[-1].status is FormStatus.DISPUTED
    decision = repository.find_agent_decision_for_trigger(
        claim_id,
        conflict_turn['claimant_message']['message_id'],
        'cus_demo',
    )
    assert decision is not None
    assert decision.discrepancy_candidates[0].field_code == 'contents.items'


def test_confirmed_family_patch_atomically_updates_claim_and_branch_projection(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='family-patch').json()
    claim_id = created['claim']['claim_id']

    response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'claim.product_family', 'value': 'home'}]},
    )

    assert response.status_code == 200
    assert response.json()['updated_fields']['claim.product_family']['value'] == 'home'
    stored = repository.get_claim(claim_id, 'cus_demo')
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.incident_type == 'home'
    assert stored.form['claim.product_family'].value == 'home'
    assert stored.form['claim.product_family'].status is FormStatus.CONFIRMED
    assert evaluations[-1].resulting_claim_revision == stored.revision
    assert evaluations[-1].selected_family == 'home'
    assert evaluations[-1].unresolved_family_conflict == []


def test_family_confirmation_uses_same_atomic_projection_as_patch(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='family-confirm').json()
    claim_id = created['claim']['claim_id']
    proposed = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={
            'updates': [
                {
                    'field_code': 'claim.product_family',
                    'value': 'home',
                    'status': 'proposed',
                }
            ]
        },
    )

    response = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-home-family',
            'If-Match': str(proposed.json()['revision']),
        },
        json={'field_codes': ['claim.product_family']},
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-home-family',
            'If-Match': str(proposed.json()['revision']),
        },
        json={'field_codes': ['claim.product_family']},
    )

    assert proposed.status_code == 200
    assert response.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == response.json()
    stored = repository.get_claim(claim_id, 'cus_demo')
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    assert stored is not None
    assert response.json()['confirmed_fields']['claim.product_family']['value'] == 'home'
    assert stored.incident_type == 'home'
    assert evaluations[-1].selected_family == 'home'
    assert evaluations[-1].resulting_claim_revision == stored.revision

    history_before_stale_write = list(evaluations)
    stale = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(proposed.json()['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'claim.product_family',
                    'value': 'contents',
                    'correction_reason': 'Synthetic stale correction.',
                }
            ]
        },
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.get_claim(claim_id, 'cus_demo') == stored
    assert repository.list_branch_evaluations(claim_id, 'cus_demo') == history_before_stale_write


def test_created_claim_rejects_family_change_without_partial_state(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='locked-family').json()
    claim_id = created['claim']['claim_id']
    proposed = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={
            'updates': [
                {
                    'field_code': 'claim.product_family',
                    'value': 'home',
                    'status': 'proposed',
                }
            ]
        },
    )
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    locked = claim.model_copy(
        update={
            'external_claim': ExternalClaimResult(
                external_claim_id='ext_locked_motor',
                claim_number='NW-LOCKED-MOTOR',
                creation_status=ClaimCreationStatus.CREATED,
                route='motor_claims',
                next_step='Northwind owns the created claim.',
                source=IntegrationSource.FIXTURE,
                created_at=claim.updated_at,
            ),
            'claim_state': claim.claim_state.model_copy(
                update={'workflow_state': WorkflowState.CREATED}
            ),
            'revision': claim.revision + 1,
        }
    )
    repository.save_claim(locked, expected_revision=claim.revision)
    before = repository.get_claim(claim_id, 'cus_demo')
    evaluations_before = repository.list_branch_evaluations(claim_id, 'cus_demo')

    patch_response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(locked.revision)},
        json={'updates': [{'field_code': 'claim.product_family', 'value': 'home'}]},
    )
    confirmation_response = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'locked-family-confirmation',
            'If-Match': str(locked.revision),
        },
        json={'field_codes': ['claim.product_family']},
    )

    assert proposed.status_code == 200
    assert patch_response.status_code == 409
    assert patch_response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert confirmation_response.status_code == 409
    assert confirmation_response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert repository.get_claim(claim_id, 'cus_demo') == before
    assert repository.list_branch_evaluations(claim_id, 'cus_demo') == evaluations_before


def test_form_correction_persists_current_transition_and_immutable_previous_evaluation(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='branch-correction').json()
    claim_id = created['claim']['claim_id']
    collision = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'incident.type', 'value': 'collision'}]},
    )
    corrected = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(collision.json()['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'incident.type',
                    'value': 'other',
                    'correction_reason': 'The incident did not involve an impact.',
                }
            ]
        },
    )

    assert collision.status_code == 200
    assert corrected.status_code == 200
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    assert len(evaluations) == 2
    previous_collision = next(
        item for item in evaluations[0].branch_results if item.branch_id == 'incident.collision'
    )
    current_collision = next(
        item for item in evaluations[1].branch_results if item.branch_id == 'incident.collision'
    )
    assert previous_collision.status == 'active'
    assert previous_collision.source_refs == [f'claim:{claim_id}:revision:2:field:incident.type']
    assert current_collision.status == 'suspended'
    assert current_collision.source_refs == [
        f'claim:{claim_id}:revision:2:field:incident.type',
        f'claim:{claim_id}:revision:3:field:incident.type',
    ]
    assert evaluations[0].resulting_claim_revision == 2
    assert evaluations[1].resulting_claim_revision == 3


def test_confirmed_intake_field_is_not_asked_again(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, key='guided-intake').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    first_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        key='guided-description',
        client_message_id='guided-description',
    ).json()

    confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-guided-description',
            'If-Match': str(first_turn['claim_revision']),
        },
        json={'field_codes': ['incident.description']},
    )
    second_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=confirmation.json()['revision'],
        key='guided-safety',
        client_message_id='guided-safety',
        text='Nobody was injured and there is no immediate danger at the scene.',
    )

    assert confirmation.status_code == 200
    assert confirmation.json()['customer_next_step']['status'] == 'more_information_needed'
    assert confirmation.json()['customer_next_step']['required_items'] == [
        'incident.injury_or_danger'
    ]
    assert second_turn.status_code == 200
    assert second_turn.json()['form_changes'][0]['field_code'] == 'incident.injury_or_danger'
    assert second_turn.json()['decision']['customer_next_step']['required_items'] == [
        'incident.occurred_at'
    ]
    assert (
        'incident.description'
        not in second_turn.json()['decision']['customer_next_step']['required_items']
    )


def test_message_reads_hide_internal_records_and_validate_session_state(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-read').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    turn = submit_message(client, auth_headers, claim_id, session_id).json()
    claimant_record = repository.get_message(
        claim_id,
        session_id,
        turn['claimant_message']['message_id'],
        'cus_demo',
    )
    assert claimant_record is not None
    repository.save_message(
        MessageRecord(
            message_id='msg_internal',
            claim_id=claim_id,
            session_id=session_id,
            actor='system',
            visibility=MessageVisibility.INTERNAL_ONLY,
            content={'type': 'status', 'text': 'Internal validation details.'},
            created_at=claimant_record.created_at + timedelta(seconds=1),
        ),
        'cus_demo',
    )

    listed = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages?limit=1',
        headers=auth_headers,
    )
    second_page = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers=auth_headers,
        params={'cursor': listed.json()['page']['next_cursor']},
    )
    missing_session = client.get(
        f'/api/v1/claims/{claim_id}/sessions/ses_missing/messages',
        headers=auth_headers,
    )

    assert listed.status_code == 200
    assert second_page.status_code == 200
    returned_ids = [
        listed.json()['items'][0]['message_id'],
        second_page.json()['items'][0]['message_id'],
    ]
    expected_ids = sorted(
        [turn['claimant_message']['message_id'], turn['agent_message']['message_id']]
    )
    assert returned_ids == expected_ids
    assert missing_session.status_code == 404


def test_message_turn_requires_headers_active_session_and_owned_evidence(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-guards').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    endpoint = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    payload = {
        'client_message_id': 'guard-message',
        'content': {'type': 'text', 'text': 'A guarded synthetic message.'},
        'evidence_refs': [],
    }

    missing_idempotency = client.post(
        endpoint,
        headers={**auth_headers, 'If-Match': '1'},
        json=payload,
    )
    missing_revision = client.post(
        endpoint,
        headers={**auth_headers, 'Idempotency-Key': 'guard-missing-revision'},
        json=payload,
    )
    unknown_evidence = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'guard-evidence',
            'If-Match': '1',
        },
        json={**payload, 'evidence_refs': ['evd_missing']},
    )
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert session is not None
    repository.save_session(session.model_copy(update={'status': SessionStatus.CLOSED}))
    closed_session = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'guard-closed',
            'If-Match': '1',
        },
        json=payload,
    )

    assert missing_idempotency.status_code == 400
    assert missing_revision.status_code == 409
    assert unknown_evidence.status_code == 422
    assert closed_session.status_code == 409
    assert closed_session.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


def test_message_turn_rejects_a_non_current_session_and_cross_session_client_id(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='message-session-scope').json()
    claim_id = created['claim']['claim_id']
    first_session_id = created['session']['session_id']
    first_turn = submit_message(client, auth_headers, claim_id, first_session_id)
    claim = repository.get_claim(claim_id, 'cus_demo')
    first_session = repository.get_session(claim_id, first_session_id, 'cus_demo')
    assert claim is not None
    assert first_session is not None
    second_session = first_session.model_copy(
        update={
            'session_id': 'ses_second_active',
            'context_revision': 2,
            'started_at': first_session.started_at + timedelta(seconds=1),
            'last_active_at': first_session.last_active_at + timedelta(seconds=1),
        }
    )
    repository.save_session(second_session)

    non_current = submit_message(
        client,
        auth_headers,
        claim_id,
        second_session.session_id,
        revision=2,
        key='non-current-session',
        client_message_id='new-client-id',
    )
    # Fixture seeding: this precondition is outside the save_claim() transaction
    # boundary (pointer change or revision-neutral write), so it is stored directly.
    repository._claims[claim.claim_id] = claim.model_copy(
        update={'active_session_id': second_session.session_id, 'revision': 2}
    )
    cross_session_replay = submit_message(
        client,
        auth_headers,
        claim_id,
        second_session.session_id,
        revision=2,
        key='cross-session-replay',
    )

    assert first_turn.status_code == 200
    assert non_current.status_code == 409
    assert non_current.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert cross_session_replay.status_code == 409
    assert cross_session_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_message_and_confirmation_requests_reject_empty_or_unconfirmable_input(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, key='invalid-message').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    message_endpoint = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'

    empty_message = client.post(
        message_endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'empty-message',
            'If-Match': '1',
        },
        json={'client_message_id': 'empty', 'content': None, 'evidence_refs': []},
    )
    unknown_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unknown-confirmation',
            'If-Match': '1',
        },
        json={'field_codes': ['incident.description']},
    )

    assert empty_message.status_code == 422
    assert unknown_confirmation.status_code == 422
    assert unknown_confirmation.json()['error']['code'] == 'VALIDATION_ERROR'


def test_message_list_time_filters_require_timezone_and_apply_strict_bounds(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, key='message-time').json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    turn = submit_message(client, auth_headers, claim_id, session_id).json()
    endpoint = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'

    before = client.get(
        endpoint,
        headers=auth_headers,
        params={'before': turn['claimant_message']['created_at']},
    )
    after = client.get(
        endpoint,
        headers=auth_headers,
        params={'after': turn['agent_message']['created_at']},
    )
    missing_timezone = client.get(
        f'{endpoint}?after=2026-08-12T10:00:00',
        headers=auth_headers,
    )

    assert before.status_code == 200
    assert before.json()['items'] == []
    assert after.status_code == 200
    assert after.json()['items'] == []
    assert missing_timezone.status_code == 422


def test_claim_collection_filters_ownership_and_paginates_updated_claims(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    first = create_claim(client, auth_headers, key='list-1').json()['claim']
    second = create_claim(client, auth_headers, key='list-2').json()['claim']
    client.patch(
        f'/api/v1/claims/{first["claim_id"]}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'incident.description', 'value': 'Updated'}]},
    )

    owned_claim = repository.get_claim(second['claim_id'], 'cus_demo')
    assert owned_claim is not None
    updated_claim = repository.get_claim(first['claim_id'], 'cus_demo')
    assert updated_claim is not None
    # Fixture seeding: this precondition is outside the save_claim() transaction
    # boundary (pointer change or revision-neutral write), so it is stored directly.
    repository._claims[updated_claim.claim_id] = updated_claim.model_copy(
        update={'updated_at': owned_claim.updated_at + timedelta(seconds=1)}
    )
    other_claim = owned_claim.model_copy(
        update={
            'claim_id': 'clm_other',
            'customer_id': 'cus_other',
            'active_session_id': 'ses_other',
        }
    )
    other_session = SessionRecord(
        session_id='ses_other',
        claim_id=other_claim.claim_id,
        customer_id=other_claim.customer_id,
        started_at=other_claim.created_at,
        last_active_at=other_claim.created_at,
    )
    repository.create_claim(other_claim, other_session)

    page_one = client.get(
        '/api/v1/claims?limit=1&workflow_state=collecting',
        headers=auth_headers,
    )
    cursor = page_one.json()['page']['next_cursor']
    page_two = client.get(f'/api/v1/claims?limit=1&cursor={cursor}', headers=auth_headers)
    updated_after = client.get(
        '/api/v1/claims',
        headers=auth_headers,
        params={'updated_after': second['updated_at']},
    )

    assert page_one.status_code == 200
    assert page_one.json()['items'][0]['claim_id'] == first['claim_id']
    assert page_one.json()['items'][0]['revision'] == 2
    assert page_one.json()['items'][0]['can_resume'] is True
    assert 'customer_id' not in page_one.json()['items'][0]
    assert 'fraud_signal' not in page_one.json()['items'][0]
    assert cursor is not None
    assert page_two.status_code == 200
    assert page_two.json()['items'][0]['claim_id'] == second['claim_id']
    assert page_two.json()['page']['next_cursor'] is None
    assert updated_after.status_code == 200
    assert [item['claim_id'] for item in updated_after.json()['items']] == [first['claim_id']]


def test_claim_collection_rejects_invalid_filter_and_cursor(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    invalid_state = client.get(
        '/api/v1/claims?workflow_state=invented',
        headers=auth_headers,
    )
    invalid_cursor = client.get('/api/v1/claims?cursor=not-a-cursor', headers=auth_headers)
    missing_timezone = client.get(
        '/api/v1/claims?updated_after=2026-08-11T10:00:00',
        headers=auth_headers,
    )

    assert invalid_state.status_code == 422
    assert invalid_state.json()['error']['code'] == 'VALIDATION_ERROR'
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()['error']['code'] == 'VALIDATION_ERROR'
    assert missing_timezone.status_code == 422
    assert missing_timezone.json()['error']['code'] == 'VALIDATION_ERROR'
    assert missing_timezone.json()['error']['details'][0]['field'] == 'updated_after'


def test_claim_remains_readable_across_multiple_persisted_sessions(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='multiple-sessions').json()
    claim_id = created['claim']['claim_id']
    first_session_id = created['session']['session_id']
    first_session = repository.get_session(claim_id, first_session_id, 'cus_demo')
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert first_session is not None
    assert claim is not None

    paused_session = first_session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'summary': 'The claimant confirmed the first incident description.',
        }
    )
    repository.save_session(paused_session)
    second_session = SessionRecord(
        session_id='ses_second',
        claim_id=claim_id,
        customer_id='cus_demo',
        context_revision=claim.revision,
        started_at=first_session.started_at + timedelta(seconds=1),
        last_active_at=first_session.last_active_at + timedelta(seconds=1),
    )
    repository.save_session(second_session)
    # Fixture seeding: this precondition is outside the save_claim() transaction
    # boundary (pointer change or revision-neutral write), so it is stored directly.
    repository._claims[claim.claim_id] = claim.model_copy(
        update={
            'active_session_id': second_session.session_id,
            'revision': claim.revision + 1,
            'updated_at': second_session.started_at,
        }
    )

    first_read = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}',
        headers=auth_headers,
    )
    second_read = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{second_session.session_id}',
        headers=auth_headers,
    )
    claim_read = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert first_read.status_code == 200
    assert first_read.json()['status'] == 'paused'
    assert first_read.json()['resume']['summary'] == paused_session.summary
    assert second_read.status_code == 200
    assert second_read.json()['status'] == 'active'
    assert claim_read.status_code == 200
    assert claim_read.json()['revision'] == 2
    assert [
        session.session_id for session in repository.list_sessions_for_claim(claim_id, 'cus_demo')
    ] == [
        first_session_id,
        second_session.session_id,
    ]


def test_resume_creates_new_session_with_saved_context(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='resume-context').json()
    claim_id = created['claim']['claim_id']
    first_session_id = created['session']['session_id']

    first_session = repository.get_session(claim_id, first_session_id, 'cus_demo')
    assert first_session is not None

    prepared_session = first_session.model_copy(
        update={
            'summary': 'The claimant confirmed a synthetic rear-end incident.',
            'unresolved_questions': ['confirm:vehicle.drivable'],
            'pending_items': ['police_report'],
            'prior_commitments': [
                'The claimant can provide the police report later without restarting.'
            ],
        }
    )
    repository.save_session(prepared_session)

    pause = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'resume-context-pause',
            'If-Match': f'"{created["claim"]["revision"]}"',
        },
    )
    assert pause.status_code == 200

    paused_session = repository.get_session(
        claim_id,
        first_session_id,
        'cus_demo',
    )
    assert paused_session is not None
    assert paused_session.status is SessionStatus.PAUSED

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-context-1'},
        json={'intent': 'resume'},
    )

    assert response.status_code == 201
    resumed = response.json()

    assert resumed['session_id'] != first_session_id
    assert resumed['status'] == 'active'
    assert resumed['resume']['summary'] == paused_session.summary
    assert resumed['resume']['unresolved_questions'] == paused_session.unresolved_questions
    assert resumed['resume']['pending_items'] == paused_session.pending_items
    assert resumed['resume']['prior_commitments'] == paused_session.prior_commitments

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.active_session_id == resumed['session_id']

    sessions = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    assert [session.session_id for session in sessions] == [
        first_session_id,
        resumed['session_id'],
    ]
