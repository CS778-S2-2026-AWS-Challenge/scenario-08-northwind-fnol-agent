from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from backend.adapters.policy_history import MockPolicyHistoryAdapter, ProviderLookupEnvelope
from backend.domain.models import (
    AgentAction,
    ClaimCreationStatus,
    CustomerNextStep,
    ExternalClaimResult,
    FormSource,
    FormStatus,
    IntegrationSource,
    MessageRecord,
    MessageVisibility,
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
                responsible_party=ResponsibleParty.NORTHWIND,
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
        assert branch_results[branch_id].status == 'candidate'
        assert claimant_message_id in branch_results[branch_id].source_refs


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
def test_invalid_claim_history_tool_arguments_do_not_call_provider(
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

    response = submit_message(
        client,
        auth_headers,
        created['claim']['claim_id'],
        created['session']['session_id'],
    )

    assert response.status_code == 200
    assert adapter.history_calls == 0
    assert repository.list_retrieval_records(created['claim']['claim_id'], 'cus_demo') == []


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
        key='guided-location',
        client_message_id='guided-location',
        text='A synthetic car park in Auckland.',
    )

    assert confirmation.status_code == 200
    assert confirmation.json()['customer_next_step']['status'] == 'provide_incident_location'
    assert confirmation.json()['customer_next_step']['required_items'] == ['incident.location']
    assert second_turn.status_code == 200
    assert second_turn.json()['form_changes'][0]['field_code'] == 'incident.location'
    assert second_turn.json()['decision']['customer_next_step']['required_items'] == [
        'incident.location'
    ]

    location_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-guided-location',
            'If-Match': str(second_turn.json()['claim_revision']),
        },
        json={'field_codes': ['incident.location']},
    ).json()
    loss_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=location_confirmation['revision'],
        key='guided-loss',
        client_message_id='guided-loss',
        text='A synthetic rear bumper was scratched.',
    ).json()
    final_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-guided-loss',
            'If-Match': str(loss_turn['claim_revision']),
        },
        json={'field_codes': ['loss.description']},
    ).json()
    additional_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=final_confirmation['revision'],
        key='guided-additional',
        client_message_id='guided-additional',
        text='A synthetic additional note.',
    )

    assert loss_turn['form_changes'][0]['field_code'] == 'loss.description'
    assert final_confirmation['customer_next_step']['status'] == 'ready_to_create'
    assert additional_turn.status_code == 200
    assert additional_turn.json()['form_changes'] == []
    assert additional_turn.json()['decision']['action'] == 'UPDATE'


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

    paused_session = first_session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'summary': 'The claimant confirmed a synthetic rear-end incident.',
            'unresolved_questions': ['confirm:vehicle.drivable'],
            'pending_items': ['police_report'],
            'prior_commitments': [
                'The claimant can provide the police report later without restarting.'
            ],
        }
    )
    repository.save_session(paused_session)

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
