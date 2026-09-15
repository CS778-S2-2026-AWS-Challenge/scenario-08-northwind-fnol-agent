import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import (
    AgentRuntimeProfile,
    IdentityMode,
    Settings,
)
from backend.domain.configuration import ModelRuntimeBinding
from backend.domain.release import ReleaseSetRecord, ReleaseSetState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.initial_runtime_release import install_initial_runtime_release


def _binding(profile_id: str) -> ModelRuntimeBinding:
    is_qwen = profile_id == 'qwen-local'
    return ModelRuntimeBinding(
        profile_id=profile_id,
        protocol='openai_compatible',
        provider='qwen-local' if is_qwen else 'nowcoding',
        model_identifier='qwen3.8-27b' if is_qwen else 'gpt-5.5',
        base_url='http://qwen.test/v1' if is_qwen else 'https://nowcoding.ai/v1',
        credential_environment_variable=None if is_qwen else 'NORTHWIND_MODEL_API_KEY',
        purpose='agent_turn',
        privacy_class='synthetic_fnol',
        prompt_version='northwind-fnol-claimant-v6',
        structured_output=True,
        tools=True,
        image_input=False,
        document_input=False,
    )


def _settings() -> Settings:
    bindings = (_binding('qwen-local'), _binding('nowcoding-gpt55'))
    return Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_base_url=bindings[0].base_url,
        model_identifier=bindings[0].model_identifier,
        model_supports_tools=True,
        model_runtime_bindings=bindings,
    )


def test_initial_release_is_complete_idempotent_and_contains_no_provider_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_MODEL_API_KEY', 'provider-secret')
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()

    first = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    second = install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert first is not None
    assert second is not None
    assert second.release_set_id == first.release_set_id
    assert set(first.configuration_refs) == {
        'agent_instruction',
        'agent_tool_policy',
        'agent_rule',
        'feature',
        'model:qwen-local',
        'model:nowcoding-gpt55',
    }
    assert len(releases.list_release_sets('test', 'fixture')) == 1
    assert len(configurations.list_configurations()) == 6
    serialized = json.dumps(
        [record.model_dump(mode='json') for record in configurations.list_configurations()]
    )
    assert 'NORTHWIND_MODEL_API_KEY' in serialized
    assert 'provider-secret' not in serialized


def test_existing_release_history_is_never_repaired_or_overwritten() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_operator_withdrawn',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.WITHDRAWN,
            configuration_refs={},
            author='operator',
            reason='The operator intentionally withdrew this Runtime release.',
            updated_at=datetime.now(UTC),
        )
    )

    result = install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert result is None
    assert configurations.list_configurations() == []
    assert [item.release_set_id for item in releases.list_release_sets()] == [
        'rel_operator_withdrawn'
    ]


def test_capabilities_expose_the_repository_published_dual_model_catalogue() -> None:
    client = TestClient(create_app(_settings()))

    response = client.get(
        '/api/v1/claims/capabilities',
        headers={'Authorization': 'Bearer synthetic-claimant'},
    )

    assert response.status_code == 200
    assert [item['id'] for item in response.json()['models']] == [
        'qwen-local',
        'nowcoding-gpt55',
    ]
    assert response.json()['default_model_profile_id'] == 'qwen-local'
