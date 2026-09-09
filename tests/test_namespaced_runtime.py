import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository


class SequenceToolGateway:
    """Small provider-neutral gateway that exposes a real two-call sequence."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.responses = [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='call_claim_read_1',
                        name='claim.read',
                        arguments={},
                    )
                ],
                provider_model='qwen3.8-27b',
                provider_request_id='provider-request-1',
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    'action_code': 'conversation.answer',
                    'runtime_action_code': 'runtime.continue',
                    'reason_codes': ['CLAIM_CONTEXT_READ'],
                    'customer_reason': 'The current claim context was read.',
                    'customer_response': 'I have read the current claim context.',
                    'customer_next_step': {
                        'status': 'continue_current_report',
                        'summary': 'Continue the report when ready.',
                        'responsible_party': 'claimant',
                        'required_items': [],
                    },
                    'source_refs': [],
                },
                provider_model='qwen3.8-27b',
                provider_request_id='provider-request-2',
            ),
        ]

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def test_namespaced_runtime_persists_tool_loop_without_legacy_decision_or_revision() -> None:
    gateway = SequenceToolGateway()
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda _config: gateway)
    repository = FixtureRepository()
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='qwen-local',
        model_base_url='http://model.example.test/v1',
        model_identifier='qwen3.8-27b',
        model_supports_tools=True,
    )

    with TestClient(
        create_app(
            settings,
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        headers = {'Authorization': 'Bearer synthetic-claimant'}
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'runtime-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
                'model_profile_id': 'qwen-local',
            },
        )
        assert created.status_code == 201, created.text
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']

        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': 'runtime-message',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'runtime-client-message',
                'content': {'type': 'text', 'text': 'Please read the current report.'},
                'evidence_refs': [],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['claim_revision'] == 1
        assert body['decision'] is None
        assert body['agent_message']['content']['text'] == (
            'I have read the current claim context.'
        )

        stored_claim = repository.get_claim(claim_id, 'cus_demo')
        assert stored_claim is not None
        assert stored_claim.revision == 1
        assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
        trace = repository.find_runtime_trace_for_trigger(
            claim_id,
            body['claimant_message']['message_id'],
            'cus_demo',
        )
        assert trace is not None
        assert trace.tool_name == 'claim.read'
        assert trace.action_code == 'conversation.answer'
        assert trace.runtime_action_code == 'runtime.continue'

        assert len(gateway.requests) == 2
        first = gateway.requests[0]
        assert [tool.name for tool in first.tools] == ['claim.read']
        assert first.response_schema is None
        second = gateway.requests[1]
        assert second.response_schema is not None
        assert [message.role.value for message in second.messages[-2:]] == ['assistant', 'tool']
        assert second.messages[-1].tool_call_id == 'call_claim_read_1'
        assert json.loads(second.messages[-1].content or '{}')['claim_id'] == claim_id

        replay = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': 'runtime-message',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'runtime-client-message',
                'content': {'type': 'text', 'text': 'Please read the current report.'},
                'evidence_refs': [],
            },
        )
        assert replay.status_code == 200
        assert replay.json() == body
        assert len(gateway.requests) == 2


def test_session_model_catalog_exposes_qwen_default_and_gpt_selection() -> None:
    configurations = ConfigurationRepository()
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='qwen-local',
        model_base_url='http://100.71.25.5:8080/v1',
        model_identifier='qwen3.8-27b',
        model_supports_tools=True,
    )
    common = {
        'protocol': 'openai_compatible',
        'purpose': 'agent_turn',
        'privacy_class': 'synthetic_fnol',
        'prompt_version': settings.model_prompt_version,
        'evaluation_status': 'configured',
        'timeout_seconds': 30.0,
        'structured_output': True,
        'tools': True,
    }
    for profile_id, model_identifier, base_url in (
        ('qwen-local', 'qwen3.8-27b', 'http://100.71.25.5:8080/v1'),
        ('nowcoding-gpt54mini', 'gpt-5.4-mini', 'https://nowcoding.ai/v1'),
    ):
        configurations.create(
            ConfigurationRecord(
                configuration_id=f'cfg_{profile_id}',
                domain='model',
                configuration_key=profile_id,
                revision=1,
                state=ConfigurationState.PUBLISHED,
                impact=ConfigurationImpact.HIGH,
                values={
                    **common,
                    'provider': 'qwen-local' if profile_id == 'qwen-local' else 'nowcoding',
                    'model_identifier': model_identifier,
                    'base_url': base_url,
                    'profile_id': profile_id,
                    'credential_environment_variable': (
                        None if profile_id == 'qwen-local' else 'NORTHWIND_MODEL_API_KEY'
                    ),
                },
                author='test',
                reason='Published test profile.',
                updated_at=datetime.now(UTC),
            )
        )
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda _config: SequenceToolGateway())
    app = create_app(
        settings,
        repository=FixtureRepository(),
        configuration_repository=configurations,
        model_gateway_registry=registry,
    )
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer synthetic-claimant'}
        capabilities = client.get('/api/v1/claims/capabilities', headers=headers)
        assert capabilities.status_code == 200
        body = capabilities.json()
        assert body['default_model_profile_id'] == 'qwen-local'
        assert [item['id'] for item in body['models']] == [
            'qwen-local',
            'nowcoding-gpt54mini',
        ]
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'gpt-session-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
                'model_profile_id': 'nowcoding-gpt54mini',
            },
        )
        assert created.status_code == 201
        assert created.json()['session']['model_profile_id'] == 'nowcoding-gpt54mini'

        unknown = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'unknown-profile-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'model_profile_id': 'unknown-profile',
            },
        )
        assert unknown.status_code == 422
        assert unknown.json()['error']['code'] == 'MODEL_PROFILE_UNAVAILABLE'
