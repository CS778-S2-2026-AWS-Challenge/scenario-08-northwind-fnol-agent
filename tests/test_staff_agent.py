from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import backend.services.staff_agent as staff_agent_service
from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.auth import Principal
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelRequest,
    ModelResponse,
)
from backend.domain.staff_agent import (
    ExecuteStaffAgentDraftRequest,
    StaffAgentDraft,
    StaffAgentDraftKind,
    StaffAgentMessage,
    StaffAgentMessageRole,
    StaffAgentModelOutput,
    StaffAgentSession,
)
from backend.prompts import STAFF_ASSISTANT_PROMPT_ID
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
    draft_kind: StaffAgentDraftKind = StaffAgentDraftKind.INTERNAL_NOTE
    draft_action_code: str | None = None
    draft_target_ref: str | None = None
    draft_payload: dict[str, object] = field(default_factory=dict)
    contexts: list[StaffAgentContext] = field(default_factory=list)

    def respond(self, context: StaffAgentContext) -> StaffAgentProviderResult:
        self.contexts.append(context)
        drafts = []
        if self.draft_claim_id is not None:
            drafts.append(
                StaffAgentDraft(
                    kind=self.draft_kind,
                    title='Review note',
                    content='Check the source before taking action.',
                    claim_id=self.draft_claim_id,
                    action_code=self.draft_action_code,
                    target_ref=self.draft_target_ref,
                    payload=self.draft_payload,
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


@dataclass
class RecordingModelGateway:
    requests: list[ModelRequest] = field(default_factory=list)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={
                'answer': 'The configured Staff Agent is ready.',
                'drafts': [],
            },
            provider_model='test-staff-model',
            provider_request_id='req-staff-runtime',
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


def _create_session(client: TestClient, model_profile_id: str | None = None) -> str:
    response = client.post(
        '/api/v1/workbench/agent/sessions',
        headers=STAFF_HEADERS,
        json={
            'title': 'Evidence review',
            **({'model_profile_id': model_profile_id} if model_profile_id else {}),
        },
    )
    assert response.status_code == 201
    return str(response.json()['session_id'])


def test_staff_agent_session_persists_selected_model_profile() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        response = client.post(
            '/api/v1/workbench/agent/sessions',
            headers=STAFF_HEADERS,
            json={'title': 'GPT review', 'model_profile_id': 'nowcoding-gpt54mini'},
        )
        assert response.status_code == 201
        session_id = response.json()['session_id']
        assert response.json()['model_profile_id'] == 'nowcoding-gpt54mini'
        listed = client.get('/api/v1/workbench/agent/sessions', headers=STAFF_HEADERS)
        assert listed.status_code == 200
        assert listed.json()['items'][0]['model_profile_id'] == 'nowcoding-gpt54mini'

        message = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'profile-bound-question',
                'content': 'Summarise the current work.',
                'claim_ids': [],
            },
        )

    assert message.status_code == 201
    assert provider.contexts[0].model_profile_id == 'nowcoding-gpt54mini'
    assert message.json()['session']['model_profile_id'] == 'nowcoding-gpt54mini'


def test_staff_agent_capabilities_exposes_published_model_catalog() -> None:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_base_url='http://model.example.test/v1',
        model_identifier='qwen3.8-27b',
    )
    with TestClient(create_app(settings, repository=FixtureRepository())) as client:
        response = client.get(
            '/api/v1/workbench/agent/capabilities',
            headers=STAFF_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body['default_model_profile_id'] == 'qwen-local'
    assert [item['id'] for item in body['models']] == ['qwen-local']


def test_staff_agent_capabilities_is_empty_for_controlled_runtime() -> None:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    with TestClient(create_app(settings)) as client:
        response = client.get(
            '/api/v1/workbench/agent/capabilities',
            headers=STAFF_HEADERS,
        )

    assert response.status_code == 200
    assert response.json() == {'models': [], 'default_model_profile_id': None}


def _model_gateway_runtime_client(
    gateway: RecordingModelGateway,
) -> TestClient:
    registry = ModelGatewayRegistry()
    registry.register('test_gateway', lambda _config: gateway)
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='test_gateway',
        model_base_url='https://model.example.test/v1',
        model_identifier='test-model',
    )
    return TestClient(
        create_app(
            settings,
            repository=FixtureRepository(),
            model_gateway_registry=registry,
        )
    )


def test_staff_agent_builds_default_gateway_from_runtime_profile() -> None:
    gateway = RecordingModelGateway()
    with _model_gateway_runtime_client(gateway) as client:
        session = client.post(
            '/api/v1/workbench/agent/sessions',
            headers=STAFF_HEADERS,
            json={'title': 'Configured Staff Agent'},
        )
        assert session.status_code == 201
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session.json()["session_id"]}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'configured-staff-message',
                'content': 'Summarise the current Claim context.',
                'claim_ids': [],
            },
        )

    assert response.status_code == 201
    assert response.json()['assistant_message']['content'] == (
        'The configured Staff Agent is ready.'
    )
    assert len(gateway.requests) == 1
    assert gateway.requests[0].purpose == 'staff_assistant'
    assert gateway.requests[0].prompt_version == STAFF_ASSISTANT_PROMPT_ID


def test_staff_agent_gateway_fails_closed_when_profile_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = RecordingModelGateway()
    with _model_gateway_runtime_client(gateway) as client:
        session = client.post(
            '/api/v1/workbench/agent/sessions',
            headers=STAFF_HEADERS,
            json={'title': 'Configuration failure'},
        )
        monkeypatch.setattr(
            'backend.app.model_configuration',
            lambda _request, _profile_id: (_ for _ in ()).throw(ValueError('invalid profile')),
        )
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session.json()["session_id"]}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'configuration-failure-message',
                'content': 'Review this Claim.',
                'claim_ids': [],
            },
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert gateway.requests == []


def test_staff_agent_gateway_fails_closed_when_profile_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = RecordingModelGateway()
    with _model_gateway_runtime_client(gateway) as client:
        session = client.post(
            '/api/v1/workbench/agent/sessions',
            headers=STAFF_HEADERS,
            json={'title': 'Missing profile'},
        )
        monkeypatch.setattr('backend.app.model_configuration', lambda _request, _profile_id: None)
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session.json()["session_id"]}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'missing-profile-message',
                'content': 'Review this Claim.',
                'claim_ids': [],
            },
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert gateway.requests == []


def test_staff_agent_rejects_model_override_in_message_request() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        session_id = _create_session(client, 'nowcoding-gpt54mini')
        response = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'profile-override',
                'content': 'Use another model for this question.',
                'claim_ids': [],
                'model_profile_id': 'qwen-local',
            },
        )

    assert response.status_code == 422


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
                'content': 'The base excess',
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
    assert context.knowledge_status == 'evidence_found'
    assert context.knowledge[0]['document_id'] == 'nw-policy-motor-standard-mvp-2026-1'
    assert context.knowledge[0]['chunk_id'].endswith('#MTR-EXC-01')
    assert context.knowledge[0]['checksum'] == (
        'a7e4d4782f90571c7a711823fe14b1d580e13a867613a9a833a33a1fdc1ad989'
    )
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


def test_staff_agent_draft_requires_confirmation_and_executes_registered_action_once() -> None:
    repository = FixtureRepository()
    provider = RecordingStaffAgent()
    with _client(repository, provider) as client:
        claim_id = _create_claim(client, 'staff-agent-draft-execution')
        support = client.post(
            f'/api/v1/claims/{claim_id}/support-requests',
            headers={
                **CLAIMANT_HEADERS,
                'Idempotency-Key': 'staff-agent-support',
                'If-Match': '1',
            },
            json={
                'reason': 'I would like a staff member to help me.',
                'support_need': 'human_requested',
                'preferred_channel': 'in_app',
            },
        )
        assert support.status_code == 201, support.text
        handoff_id = support.json()['handoff']['handoff_id']
        presence = client.patch(
            '/api/v1/workbench/staff/presence',
            headers=STAFF_HEADERS,
            json={'online': True, 'available': True, 'lease_seconds': 60},
        )
        assert presence.status_code == 200, presence.text

        provider.draft_claim_id = claim_id
        provider.draft_action_code = 'human.accept_handoff'
        provider.draft_target_ref = handoff_id
        provider.draft_payload = {}
        session_id = _create_session(client)
        turn = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'accept-draft-request',
                'content': 'Prepare the Claim acceptance action.',
                'claim_ids': [claim_id],
            },
        )
        assert turn.status_code == 201, turn.text
        assistant = turn.json()['assistant_message']
        draft = assistant['drafts'][0]
        assert draft['draft_id'].startswith('sdr_')
        endpoint = (
            f'/api/v1/workbench/agent/sessions/{session_id}/messages/'
            f'{assistant["message_id"]}/drafts/{draft["draft_id"]}/execute'
        )

        unconfirmed = client.post(endpoint, headers=STAFF_HEADERS, json={'confirmed': False})
        assert unconfirmed.status_code == 409
        assert unconfirmed.json()['error']['code'] == 'CONFIRMATION_REQUIRED'
        unconfirmed_claim = repository.get_claim_internal(claim_id)
        assert unconfirmed_claim is not None
        assert unconfirmed_claim.revision == 2

        headers = {
            **STAFF_HEADERS,
            'Idempotency-Key': 'execute-staff-agent-draft',
            'If-Match': '2',
        }
        executed = client.post(endpoint, headers=headers, json={'confirmed': True})
        replay = client.post(endpoint, headers=headers, json={'confirmed': True})

        assert executed.status_code == 200, executed.text
        assert replay.status_code == 200, replay.text
        assert replay.json() == executed.json()
        assert executed.json()['action_code'] == 'human.accept_handoff'
        assert executed.json()['outcome'] == 'executed'
        assert executed.json()['result']['handoff']['status'] == 'accepted'
        executed_claim = repository.get_claim_internal(claim_id)
        assert executed_claim is not None
        assert executed_claim.revision == 3
        execution_record = repository.find_idempotency(
            'stf_demo',
            f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
            'execute-staff-agent-draft',
        )
        assert execution_record is not None
        assert execution_record.staff_agent_session_id == session_id
        assert execution_record.staff_agent_message_id == assistant['message_id']
        assert execution_record.staff_agent_draft_id == draft['draft_id']

        second_turn = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages',
            headers=STAFF_HEADERS,
            json={
                'client_message_id': 'accept-draft-request-2',
                'content': 'Prepare the same Claim acceptance action again.',
                'claim_ids': [claim_id],
            },
        )
        assert second_turn.status_code == 201, second_turn.text
        second_assistant = second_turn.json()['assistant_message']
        second_draft = second_assistant['drafts'][0]
        conflicting_replay = client.post(
            f'/api/v1/workbench/agent/sessions/{session_id}/messages/'
            f'{second_assistant["message_id"]}/drafts/{second_draft["draft_id"]}/execute',
            headers={
                **STAFF_HEADERS,
                'Idempotency-Key': 'execute-staff-agent-draft',
                'If-Match': '3',
            },
            json={'confirmed': True},
        )
        assert conflicting_replay.status_code == 409
        assert conflicting_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


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


@pytest.mark.parametrize(
    ('action_code', 'handler_name'),
    [
        ('human.accept_handoff', 'accept_handoff'),
        ('conversation.send_claimant_message', 'send_staff_message'),
        ('human.resolve_handoff', 'resolve_handoff'),
        ('signal.record_decision', 'decide_review_signal'),
        ('work_item.create', 'create_staff_action'),
        ('work_item.update', 'update_staff_action'),
        ('ownership.request_cowork', 'create_cowork_request'),
        ('ownership.invite_cowork', 'create_cowork_request'),
        ('ownership.request_transfer', 'create_transfer_request'),
        ('ownership.decide_cowork', 'decide_collaboration_request'),
        ('ownership.decide_transfer', 'decide_collaboration_request'),
        ('ownership.requeue', 'requeue_claim'),
    ],
)
def test_staff_agent_dispatches_each_registered_action_with_durable_source(
    action_code: str,
    handler_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every registered dispatch path receives the explicit draft provenance."""

    class RequestStub:
        @classmethod
        def model_validate(cls, value: object) -> object:
            return value

    for request_name in (
        'AcceptHandoffRequest',
        'CreateStaffMessageRequest',
        'ResolveHandoffRequest',
        'SignalDecisionRequest',
        'CreateStaffActionRequest',
        'UpdateStaffActionRequest',
        'CreateCoworkRequest',
        'CreateTransferRequest',
        'DecideCollaborationRequest',
        'RequeueClaimRequest',
    ):
        monkeypatch.setattr(staff_agent_service, request_name, RequestStub)

    handler = Mock(return_value=StaffAgentModelOutput(answer='Executed.', drafts=[]))
    monkeypatch.setattr(staff_agent_service, handler_name, handler)
    repository = Mock()
    timestamp = datetime.now(UTC)
    repository.get_staff_agent_session.return_value = StaffAgentSession(
        session_id='sas_test',
        staff_id='stf_demo',
        title='Test',
        created_at=timestamp,
        updated_at=timestamp,
    )
    repository.list_staff_agent_messages.return_value = [
        StaffAgentMessage(
            message_id='sam_test',
            session_id='sas_test',
            staff_id='stf_demo',
            role=StaffAgentMessageRole.ASSISTANT,
            content='Draft.',
            claim_ids=['clm_test'],
            drafts=[
                StaffAgentDraft(
                    draft_id='sdr_test',
                    kind=StaffAgentDraftKind.INTERNAL_NOTE,
                    title='Action',
                    content='Execute.',
                    claim_id='clm_test',
                    action_code=action_code,
                    target_ref='target_test',
                )
            ],
            created_at=timestamp,
        )
    ]
    repository.get_claim_internal.return_value = SimpleNamespace(active_session_id='target_test')

    response = staff_agent_service.execute_staff_agent_draft(
        repository,
        Principal(subject='stf_demo', actor_type='staff'),
        'sas_test',
        'sam_test',
        'sdr_test',
        ExecuteStaffAgentDraftRequest(confirmed=True),
        f'key-{action_code}',
        '1',
    )

    assert response.outcome.value == 'executed'
    assert handler.call_args.kwargs['source'].session_id == 'sas_test'
    assert handler.call_args.kwargs['source'].message_id == 'sam_test'
    assert handler.call_args.kwargs['source'].draft_id == 'sdr_test'


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
