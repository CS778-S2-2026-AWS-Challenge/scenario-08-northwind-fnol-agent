import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import (
    AgentRuntimeProfile,
    IdentityMode,
    Settings,
)
from backend.domain.configuration import ModelRuntimeBinding
from backend.domain.release import ConfigurationReference, ReleaseSetRecord, ReleaseSetState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.initial_runtime_release import install_initial_runtime_release
from backend.services.runtime_agent_policy import RuntimeAgentPolicyResolver
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)


def _binding(
    profile_id: str,
    *,
    prompt_version: str = 'northwind-fnol-claimant-v7',
) -> ModelRuntimeBinding:
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
        prompt_version=prompt_version,
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
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    assert policy.instruction.prompt_version == 'northwind-fnol-claimant-v7'
    assert policy.instruction.composition_mode == 'fragmented'
    assert len(policy.instruction.fragments) == 23
    assert len(policy.tool_policy.request_profiles) == 9
    assert set(policy.tool_policy.provider_capabilities) == {
        'qwen-local',
        'nowcoding-gpt55',
    }
    assert policy.controlled_rules.context_budget_policy is not None
    assert policy.features.verified_rolling_summary is True
    assert policy.features.isolated_execution is True


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


def test_incomplete_v7_release_set_is_rejected_at_runtime_resolution() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    valid = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    assert valid is not None
    tool_reference = valid.configuration_refs['agent_tool_policy']
    tool_record = configurations.get(tool_reference.configuration_id, tool_reference.revision)
    assert tool_record is not None
    values = deepcopy(tool_record.values)
    schema_registry = dict(cast(dict[str, object], values['schema_registry']))
    schema_registry.pop('claimant.sourced-summary.v1')
    values['schema_registry'] = schema_registry
    incomplete = tool_record.model_copy(
        update={
            'configuration_id': 'cfg_agent_tool_policy_incomplete_v7',
            'revision': 1,
            'values': values,
            'updated_at': valid.updated_at + timedelta(seconds=1),
        }
    )
    configurations.create(incomplete)
    references = dict(valid.configuration_refs)
    references['agent_tool_policy'] = ConfigurationReference(
        configuration_id=incomplete.configuration_id,
        revision=incomplete.revision,
    )
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_incomplete_v7',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs=references,
            author='test',
            reason='Prove incomplete v7 publication fails closed.',
            updated_at=valid.updated_at + timedelta(seconds=1),
        )
    )
    resolver = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError, match='schema registry'):
        resolver.resolve_for_turn()


@pytest.mark.parametrize(
    ('mutation', 'expected_error'),
    [
        ('provider_capability', 'model binding'),
        ('request_profile', 'Request Profile'),
    ],
)
def test_v7_release_rejects_versioned_registry_drift(
    mutation: str,
    expected_error: str,
) -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    valid = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    assert valid is not None
    tool_reference = valid.configuration_refs['agent_tool_policy']
    tool_record = configurations.get(tool_reference.configuration_id, tool_reference.revision)
    assert tool_record is not None
    values = deepcopy(tool_record.values)
    if mutation == 'provider_capability':
        capabilities = deepcopy(cast(dict[str, object], values['provider_capabilities']))
        qwen = cast(dict[str, object], capabilities['qwen-local'])
        qwen['tool_call_support'] = False
        values['provider_capabilities'] = capabilities
    else:
        profiles = deepcopy(cast(list[dict[str, object]], values['request_profiles']))
        profiles[0]['output_limit'] = int(cast(int, profiles[0]['output_limit'])) + 1
        values['request_profiles'] = profiles
    incompatible = tool_record.model_copy(
        update={
            'configuration_id': f'cfg_agent_tool_policy_{mutation}_drift',
            'revision': 1,
            'values': values,
            'updated_at': valid.updated_at + timedelta(seconds=1),
        }
    )
    configurations.create(incompatible)
    references = dict(valid.configuration_refs)
    references['agent_tool_policy'] = ConfigurationReference(
        configuration_id=incompatible.configuration_id,
        revision=incompatible.revision,
    )
    releases.create(
        ReleaseSetRecord(
            release_set_id=f'rel_{mutation}_drift_v7',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs=references,
            author='test',
            reason='Prove provider capability drift fails closed.',
            updated_at=valid.updated_at + timedelta(seconds=1),
        )
    )
    resolver = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError, match=expected_error):
        resolver.resolve_for_turn()


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


def test_v6_binding_manifest_installs_a_real_manual_rollback_release() -> None:
    bindings = (
        _binding('qwen-local', prompt_version='northwind-fnol-claimant-v6'),
        _binding('nowcoding-gpt55', prompt_version='northwind-fnol-claimant-v6'),
    )
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_base_url=bindings[0].base_url,
        model_identifier=bindings[0].model_identifier,
        model_supports_tools=True,
        model_runtime_bindings=bindings,
    )
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    release = install_initial_runtime_release(
        settings,
        configurations,
        releases,
        KnowledgeAdminRepository(),
    )

    assert release is not None
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    assert policy.instruction.prompt_version == 'northwind-fnol-claimant-v6'
    assert policy.instruction.composition_mode == 'single'
    assert policy.features.verified_rolling_summary is False
