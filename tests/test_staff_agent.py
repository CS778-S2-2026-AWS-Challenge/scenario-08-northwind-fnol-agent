from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.staff_agent import (
    StaffAgentDraft,
    StaffAgentDraftKind,
    StaffAgentModelOutput,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import ControlledAgent
from backend.services.staff_agent import (
    StaffAgentContext,
    StaffAgentProviderResult,
    StaffAgentTurnProvider,
)

STAFF_HEADERS = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_HEADERS = {'Authorization': 'Bearer synthetic-claimant'}


@dataclass
class RecordingStaffAgent(StaffAgentTurnProvider):
    draft_claim_id: str | None = None
    contexts: list[StaffAgentContext] = field(default_factory=list)

    def respond(self, context: StaffAgentContext) -> StaffAgentProviderResult:
        self.contexts.append(context)
        drafts = []
        if self.draft_claim_id is not None:
            drafts.append(
                StaffAgentDraft(
                    kind=StaffAgentDraftKind.INTERNAL_NOTE,
                    title='Review note',
                    content='Check the source before taking action.',
                    claim_id=self.draft_claim_id,
                )
            )
        return StaffAgentProviderResult(
            output=StaffAgentModelOutput(
                answer='Review the available evidence before deciding the next action.',
                drafts=drafts,
            ),
            provider_model='test-staff-model',
            provider_request_id='req_staff_test',
        )


def _client(
    repository: FixtureRepository,
    provider: StaffAgentTurnProvider | None,
) -> TestClient:
    return TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            repository=repository,
            agent_turn_provider=ControlledAgent(),
            staff_agent_turn_provider=provider,
        )
    )


def _create_claim(client: TestClient, suffix: str = 'staff-agent') -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_HEADERS, 'Idempotency-Key': suffix},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(response.json()['claim']['claim_id'])


def _create_session(client: TestClient) -> str:
    response = client.post(
        '/api/v1/workbench/agent/sessions',
        headers=STAFF_HEADERS,
        json={'title': 'Evidence review'},
    )
    assert response.status_code == 201
    return str(response.json()['session_id'])


def test_staff_agent_persists_explicit_multi_claim_scope_and_lists_conversation() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        first_claim = _create_claim(client, 'staff-agent-first')
        second_claim = _create_claim(client, 'staff-agent-second')
        session_id = _create_session(client)

        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'staff-question-1',
                'content': 'Compare the missing evidence for these Claims.',
                'claim_ids': [first_claim, second_claim],
            },
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload['staff_message']['claim_ids'] == [first_claim, second_claim]
        assert payload['assistant_message']['claim_ids'] == [first_claim, second_claim]
        assert payload['assistant_message']['provider_model'] == 'test-staff-model'
        assert len(provider.contexts) == 1
        assert [item['claim_id'] for item in provider.contexts[0].claims] == [
            first_claim,
            second_claim,
        ]

        messages = client.get(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
        )
        conversations = client.get('/api/v1/workbench/conversations', headers=STAFF_HEADERS)

        assert [item['role'] for item in messages.json()['items']] == ['staff', 'assistant']
        agent_conversation = next(
            item for item in conversations.json()['items'] if item['kind'] == 'staff_agent'
        )
        assert agent_conversation['session_id'] == session_id
        assert agent_conversation['summary'] == payload['assistant_message']['content']


def test_staff_agent_accepts_an_explicit_empty_claim_scope() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        session_id = _create_session(client)
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'general-question',
                'content': 'What should I verify before contacting a claimant?',
                'claim_ids': [],
            },
        )

    assert response.status_code == 201
    assert provider.contexts[0].claims == ()
    assert response.json()['staff_message']['claim_ids'] == []


def test_staff_agent_context_includes_claim_operational_records_and_limitations() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        claim_id = _create_claim(client, 'staff-agent-context')
        session_id = _create_session(client)
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'context-question',
                'content': 'Summarise the current Claim context and any operational blockers.',
                'claim_ids': [claim_id],
            },
        )

    assert response.status_code == 201
    context = provider.contexts[0]
    claim_context = context.claims[0]
    assert {
        'claimant',
        'claim_id',
        'claim_state',
        'form',
        'evidence',
        'references',
        'review_signals',
        'handoffs',
        'staff_actions',
        'customer_updates',
        'external_services',
        'context_limitations',
    } <= set(claim_context)
    assert context.references == ()
    assert context.review_signals == ()
    assert context.handoffs == ()
    assert context.staff_actions == ()
    assert context.customer_updates == ()
    assert context.external_services == ()
    assert not any(
        'External-service records are unavailable' in item for item in context.context_limitations
    )


def test_staff_agent_rejects_an_out_of_scope_draft_without_saving_the_turn() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent(draft_claim_id='clm_not_selected')
    with _client(repository, provider) as client:
        session_id = _create_session(client)
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'unsafe-draft',
                'content': 'Draft an update.',
                'claim_ids': [],
            },
        )
        messages = client.get(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert messages.json()['items'] == []


def test_staff_agent_fails_closed_when_no_model_profile_is_configured() -> None:
    repository = FixtureRepository()
    with _client(repository, None) as client:
        session_id = _create_session(client)
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'unconfigured-agent',
                'content': 'Help me review this Claim.',
                'claim_ids': [],
            },
        )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'


def test_staff_agent_routes_require_staff_identity() -> None:
    repository = FixtureRepository()
    with _client(repository, RecordingStaffAgent()) as client:
        response = client.get(
            '/api/v1/workbench/agent/sessions',
            headers=CLAIMANT_HEADERS,
        )

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'


def test_staff_agent_returns_not_found_for_unknown_session() -> None:
    repository = FixtureRepository()
    with _client(repository, RecordingStaffAgent()) as client:
        response = client.get(
            '/api/v1/workbench/agent/sessions/sas_missing/messages',
            headers=STAFF_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_staff_agent_replays_idempotent_turn_and_rejects_duplicate_claim_scope() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        claim_id = _create_claim(client, 'staff-agent-replay')
        session_id = _create_session(client)
        payload = {
            'client_message_id': 'replay-question',
            'content': 'Summarise this Claim.',
            'claim_ids': [claim_id],
        }
        first = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json=payload,
        )
        replay = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json=payload,
        )
        duplicate = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                **payload,
                'client_message_id': 'duplicate-scope',
                'claim_ids': [claim_id, claim_id],
            },
        )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert (
        replay.json()['assistant_message']['message_id']
        == first.json()['assistant_message']['message_id']
    )
    assert duplicate.status_code == 422
    assert duplicate.json()['error']['code'] == 'VALIDATION_ERROR'


def test_staff_agent_rejects_reused_message_identity_and_missing_claim() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        session_id = _create_session(client)
        first = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'identity-conflict',
                'content': 'First question.',
                'claim_ids': [],
            },
        )
        conflict = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'identity-conflict',
                'content': 'Different question.',
                'claim_ids': [],
            },
        )
        missing = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'missing-claim',
                'content': 'Review this.',
                'claim_ids': ['clm_missing'],
            },
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert missing.status_code == 404
    assert missing.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
