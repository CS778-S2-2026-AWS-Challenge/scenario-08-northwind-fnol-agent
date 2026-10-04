from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.agent_tool_registry import tool_contract
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeBinding,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from backend.domain.release import ConfigurationReference, ReleaseSetRecord, ReleaseSetState
from backend.prompts import CLAIMANT_V8_PROMPT_ID
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.initial_runtime_release import repository_release_values
from backend.services.model_profiles import (
    _settings_configuration,
    model_catalog,
    model_configuration,
    select_model_profile,
)
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationSnapshot,
)
from tests.journey_v8_support import envelope


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
                        'status': 'confirmation_required',
                        'summary': 'Review the incident description.',
                        'responsible_party': 'claimant',
                        'required_items': ['incident.description'],
                    },
                    'form_changes': [
                        {
                            'field_code': 'incident.description',
                            'value': 'Please read the current report.',
                            'reported_text': 'Please read the current report.',
                        }
                    ],
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


class RepeatableToolGateway:
    """Provider-neutral gateway used to prove per-turn model selection."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.turn_number = 0

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self.turn_number += 1
        return ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output=envelope(reply=f'Turn {self.turn_number} reviewed.'),
            provider_model=request.model_profile_id,
            provider_request_id=f'request-{len(self.requests)}',
        )


def published_model_catalog(
    settings: Settings,
) -> tuple[ConfigurationRepository, ReleaseSetRepository]:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    common = {
        'protocol': 'openai_compatible',
        'purpose': 'agent_turn',
        'privacy_class': 'synthetic_fnol',
        'prompt_version': CLAIMANT_V8_PROMPT_ID,
        'evaluation_status': 'configured',
        'timeout_seconds': 30.0,
        'structured_output': True,
        'tools': True,
    }
    records: dict[str, ConfigurationRecord] = {}
    for profile_id, model_identifier, base_url in (
        ('qwen-local', 'qwen3.8-27b', 'http://100.71.25.5:8080/v1'),
        ('openrouter-gpt4o-mini', 'openai/gpt-4o-mini', 'https://openrouter.ai/api/v1'),
    ):
        record = ConfigurationRecord(
            configuration_id=f'cfg_{profile_id}',
            domain='model',
            configuration_key=profile_id,
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            values={
                **common,
                'provider': 'qwen-local' if profile_id == 'qwen-local' else 'openrouter',
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
        configurations.create(record)
        records[f'model:{profile_id}'] = record
    # The Agent policy is the repository's complete release for these two bindings.
    bindings = [
        ModelRuntimeBinding.model_validate(
            {
                key: value
                for key, value in records[f'model:{profile_id}'].values.items()
                if key in ModelRuntimeBinding.model_fields
            }
        )
        for profile_id in ('qwen-local', 'openrouter-gpt4o-mini')
    ]
    agent_values = {
        slot: values
        for slot, values in repository_release_values(bindings).items()
        if not slot.startswith('model:')
    }
    for domain, values in agent_values.items():
        record = ConfigurationRecord(
            configuration_id=f'cfg_{domain}',
            domain=domain,
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            values=values,
            author='test',
            reason='Publish the complete test Agent policy.',
            updated_at=datetime.now(UTC),
        )
        configurations.create(record)
        records[domain] = record
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_model_catalog',
            environment=settings.environment,
            runtime_profile=settings.data_runtime_profile.value,
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                slot: ConfigurationReference(
                    configuration_id=record.configuration_id,
                    revision=record.revision,
                )
                for slot, record in records.items()
            },
            author='test',
            reason='Publish both selectable model profiles with one complete Agent policy.',
            effective_time=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    return configurations, releases


def test_model_profile_can_change_between_turns_without_new_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_MODEL_API_KEY', 'test-gpt-key')
    gateway = RepeatableToolGateway()
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda _config: gateway)
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
    configurations, releases = published_model_catalog(settings)

    with TestClient(
        create_app(
            settings,
            repository=FixtureRepository(),
            configuration_repository=configurations,
            release_set_repository=releases,
            model_gateway_registry=registry,
        )
    ) as client:
        headers = {'Authorization': 'Bearer synthetic-claimant'}
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'switch-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'model_profile_id': 'qwen-local'},
        )
        assert created.status_code == 201, created.text
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']

        revision = created.json()['claim']['revision']
        for index, profile_id in enumerate(('qwen-local', 'openrouter-gpt4o-mini'), start=1):
            response = client.post(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers={
                    **headers,
                    'Idempotency-Key': f'switch-message-{index}',
                    'If-Match': str(revision),
                },
                json={
                    'client_message_id': f'switch-client-{index}',
                    'model_profile_id': profile_id,
                    'content': {'type': 'text', 'text': f'Please review turn {index}.'},
                },
            )
            assert response.status_code == 200, response.text
            revision = response.json()['claim_revision']

        session = client.get(f'/api/v1/claims/{claim_id}/sessions/{session_id}', headers=headers)
        assert session.status_code == 200
        assert session.json()['model_profile_id'] == 'openrouter-gpt4o-mini'
        # One model call per turn, each on the profile the claimant selected for it.
        assert [request.model_profile_id for request in gateway.requests] == [
            'qwen-local',
            'openrouter-gpt4o-mini',
        ]


def test_session_model_catalog_exposes_qwen_default_and_gpt_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_MODEL_API_KEY', 'test-gpt-key')
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
    configurations, releases = published_model_catalog(settings)
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda _config: SequenceToolGateway())
    app = create_app(
        settings,
        repository=FixtureRepository(),
        configuration_repository=configurations,
        release_set_repository=releases,
        model_gateway_registry=registry,
    )
    request = SimpleNamespace(app=app)
    selected = model_configuration(request, 'openrouter-gpt4o-mini')
    assert selected is not None
    assert selected.model_identifier == 'openai/gpt-4o-mini'
    assert model_configuration(request, 'missing-profile') is None
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer synthetic-claimant'}
        capabilities = client.get('/api/v1/claims/capabilities', headers=headers)
        assert capabilities.status_code == 200
        body = capabilities.json()
        assert body['default_model_profile_id'] == 'qwen-local'
        assert [item['id'] for item in body['models']] == [
            'qwen-local',
            'openrouter-gpt4o-mini',
        ]
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'gpt-session-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
                'model_profile_id': 'openrouter-gpt4o-mini',
            },
        )
        assert created.status_code == 201
        assert created.json()['session']['model_profile_id'] == 'openrouter-gpt4o-mini'

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

    gpt_default_app = create_app(
        replace(settings, model_profile_id='openrouter-gpt4o-mini'),
        repository=FixtureRepository(),
        configuration_repository=configurations,
        release_set_repository=releases,
        model_gateway_registry=registry,
    )
    with TestClient(gpt_default_app) as client:
        capabilities = client.get(
            '/api/v1/claims/capabilities',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert capabilities.status_code == 200
    assert capabilities.json()['default_model_profile_id'] == 'openrouter-gpt4o-mini'
    assert [item['id'] for item in capabilities.json()['models']] == [
        'openrouter-gpt4o-mini',
        'qwen-local',
    ]


def test_model_catalog_filters_unpublished_and_invalid_profiles_before_bootstrap() -> None:
    configurations = ConfigurationRepository()
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_profile_id='qwen-local',
        model_protocol_adapter='openai_compatible',
        model_base_url='http://model.example.test/v1',
        model_identifier='qwen3.8-27b',
        model_supports_tools=True,
    )
    configurations.create(
        ConfigurationRecord(
            configuration_id='cfg-draft',
            domain='model',
            configuration_key='draft',
            revision=1,
            state=ConfigurationState.DRAFT,
            impact=ConfigurationImpact.HIGH,
            values={},
            author='test',
            reason='Unpublished profile.',
            updated_at=datetime.now(UTC),
        )
    )
    configurations.create(
        ConfigurationRecord(
            configuration_id='cfg-invalid',
            domain='model',
            configuration_key='invalid',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            values={'profile_id': 'invalid'},
            author='test',
            reason='Malformed profile.',
            updated_at=datetime.now(UTC),
        )
    )
    configurations.create(
        ConfigurationRecord(
            configuration_id='cfg-other-domain',
            domain='feature',
            configuration_key='feature',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.NORMAL,
            values={},
            author='test',
            reason='Non-model record.',
            updated_at=datetime.now(UTC),
        )
    )

    with TestClient(
        create_app(
            settings,
            repository=FixtureRepository(),
            configuration_repository=configurations,
        )
    ) as client:
        response = client.get(
            '/api/v1/claims/capabilities',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert response.status_code == 200
    assert response.json()['models'][0]['id'] == 'qwen-local'
    assert response.json()['default_model_profile_id'] == 'qwen-local'


def test_capabilities_returns_no_model_catalog_for_controlled_runtime() -> None:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.CONTROLLED,
    )

    with TestClient(create_app(settings, repository=FixtureRepository())) as client:
        response = client.get(
            '/api/v1/claims/capabilities',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert response.status_code == 200
    assert response.json()['models'] == []
    assert response.json()['default_model_profile_id'] is None


def test_model_catalog_returns_empty_for_controlled_runtime_directly() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    environment='test',
                    identity_mode=IdentityMode.DEVELOPER,
                    agent_runtime_profile=AgentRuntimeProfile.CONTROLLED,
                )
            )
        )
    )

    assert model_catalog(request) == []
    assert select_model_profile(request, 'requested-profile') == 'requested-profile'


def test_model_catalog_raises_when_active_snapshot_is_unavailable() -> None:
    class FailingResolver:
        def snapshot(self) -> RuntimeConfigurationSnapshot:
            raise RuntimeConfigurationResolutionError('invalid active release')

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    environment='test',
                    identity_mode=IdentityMode.DEVELOPER,
                    agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
                    model_base_url='http://model.example.test/v1',
                    model_identifier='qwen3.8-27b',
                ),
                runtime_configuration_resolver=FailingResolver(),
            )
        )
    )

    with pytest.raises(ApiError, match='active Runtime configuration is unavailable'):
        model_catalog(request)


def test_model_catalog_reads_profiles_from_an_active_release_snapshot() -> None:
    qwen = ConfigurationRecord(
        configuration_id='cfg-qwen',
        domain='model',
        configuration_key='model:qwen-local',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values={
            'protocol': 'openai_compatible',
            'provider': 'qwen-local',
            'model_identifier': 'qwen3.8-27b',
            'base_url': 'http://model.example.test/v1',
            'credential_environment_variable': None,
            'profile_id': 'qwen-local',
            'purpose': 'agent_turn',
            'privacy_class': 'synthetic_fnol',
            'prompt_version': 'northwind-fnol-motor-claimant-v4',
            'evaluation_status': 'configured',
            'timeout_seconds': 30.0,
            'structured_output': True,
            'tools': True,
        },
        author='test',
        reason='Published snapshot profile.',
        updated_at=datetime.now(UTC),
    )
    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='release-models',
        configurations={'model:qwen-local': qwen},
        integrations={},
        knowledge={},
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    environment='test',
                    identity_mode=IdentityMode.DEVELOPER,
                    agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
                    model_base_url='http://model.example.test/v1',
                    model_identifier='qwen3.8-27b',
                ),
                runtime_configuration_resolver=SimpleNamespace(snapshot=lambda: snapshot),
            )
        )
    )

    assert model_catalog(request) == [qwen]


def test_model_catalog_does_not_bootstrap_when_model_settings_are_incomplete() -> None:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.CONTROLLED,
        model_base_url='',
        model_identifier='',
    )
    assert _settings_configuration(settings) is None


def test_unknown_runtime_tool_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match='Unknown Agent tool'):
        tool_contract('claim.write')
