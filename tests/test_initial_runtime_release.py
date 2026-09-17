import json
from copy import deepcopy
from dataclasses import replace
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
    is_bedrock = profile_id == 'bedrock-nova2-lite'
    is_google = profile_id == 'google-gemini35-flash-lite'
    return ModelRuntimeBinding(
        profile_id=profile_id,
        protocol=(
            'bedrock_converse'
            if is_bedrock
            else ('google_generate_content' if is_google else 'openai_compatible')
        ),
        provider=(
            'amazon-bedrock'
            if is_bedrock
            else ('google-ai-studio' if is_google else ('qwen-local' if is_qwen else 'nowcoding'))
        ),
        model_identifier=(
            'global.amazon.nova-2-lite-v1:0'
            if is_bedrock
            else (
                'gemini-3.5-flash-lite' if is_google else ('qwen3.8-27b' if is_qwen else 'gpt-5.5')
            )
        ),
        base_url=(
            'https://bedrock-runtime.ap-southeast-2.amazonaws.com'
            if is_bedrock
            else (
                'https://generativelanguage.googleapis.com/v1beta'
                if is_google
                else ('http://qwen.test/v1' if is_qwen else 'https://nowcoding.ai/v1')
            )
        ),
        credential_environment_variable=(
            'AWS_BEARER_TOKEN_BEDROCK'
            if is_bedrock
            else (
                'GEMINI_API_KEY' if is_google else (None if is_qwen else 'NORTHWIND_MODEL_API_KEY')
            )
        ),
        purpose='agent_turn',
        privacy_class='synthetic_fnol',
        prompt_version=prompt_version,
        evaluation_status='unavailable' if is_bedrock else 'configured',
        structured_output=True,
        tools=not is_bedrock,
        image_input=is_bedrock or is_google,
        document_input=False,
    )


def _settings() -> Settings:
    bindings = (
        _binding('qwen-local'),
        _binding('nowcoding-gpt55'),
        _binding('bedrock-nova2-lite'),
        _binding('google-gemini35-flash-lite'),
    )
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
        'model:bedrock-nova2-lite',
        'model:google-gemini35-flash-lite',
    }
    assert len(releases.list_release_sets('test', 'fixture')) == 1
    assert len(configurations.list_configurations()) == 8
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
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
    }
    assert {
        str(record.values['profile_id']): record.values['timeout_seconds']
        for record in configurations.list_configurations('model')
    } == {
        'qwen-local': 180.0,
        'nowcoding-gpt55': 180.0,
        'bedrock-nova2-lite': 180.0,
        'google-gemini35-flash-lite': 180.0,
    }
    bedrock = next(
        record
        for record in configurations.list_configurations('model')
        if record.values['profile_id'] == 'bedrock-nova2-lite'
    )
    assert bedrock.values['evaluation_status'] == 'unavailable'
    assert bedrock.values['image_input'] is True
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


def test_initial_release_rejects_missing_or_mixed_model_catalogues() -> None:
    base = _settings()
    missing_model = replace(
        base,
        model_runtime_bindings=tuple(
            binding
            for binding in base.model_runtime_bindings
            if binding.profile_id != 'google-gemini35-flash-lite'
        ),
    )
    with pytest.raises(ValueError, match='google-gemini35-flash-lite'):
        install_initial_runtime_release(
            missing_model,
            ConfigurationRepository(),
            ReleaseSetRepository(),
            KnowledgeAdminRepository(),
        )

    mixed_versions = replace(
        base,
        model_runtime_bindings=(
            _binding('qwen-local'),
            _binding('nowcoding-gpt55', prompt_version='northwind-fnol-claimant-v6'),
        ),
    )
    with pytest.raises(ValueError, match='cannot mix Prompt versions'):
        install_initial_runtime_release(
            mixed_versions,
            ConfigurationRepository(),
            ReleaseSetRepository(),
            KnowledgeAdminRepository(),
        )


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


@pytest.mark.parametrize(
    ('mutation', 'expected_error'),
    [
        ('prompt_mode', 'Prompt Pack'),
        ('fragment_budget', 'exceeds budget'),
        ('schema_contract', 'schema registry'),
        ('provider_catalogue', 'model catalogue'),
        ('model_prompt_version', 'model binding'),
        ('route_policy', 'route or budget policy'),
        ('feature_set', 'feature and cache set'),
    ],
)
def test_v7_atomic_release_rejects_each_incomplete_published_component(
    mutation: str,
    expected_error: str,
) -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    valid = install_initial_runtime_release(
        _settings(),
        configurations,
        releases,
        KnowledgeAdminRepository(),
    )
    assert valid is not None
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    snapshot = policy.runtime_snapshot
    instruction = policy.instruction
    tool_policy = policy.tool_policy
    controlled_rules = policy.controlled_rules
    features = policy.features

    if mutation == 'prompt_mode':
        instruction = instruction.model_copy(update={'composition_mode': 'single'})
    elif mutation == 'fragment_budget':
        fragments = list(instruction.fragments)
        fragments[0] = fragments[0].model_copy(update={'content': 'oversized ' * 1000})
        instruction = instruction.model_copy(update={'fragments': fragments})
    elif mutation == 'schema_contract':
        schemas = deepcopy(tool_policy.schema_registry)
        schemas['claimant.answer.v1'] = {'type': 'object'}
        tool_policy = tool_policy.model_copy(update={'schema_registry': schemas})
    elif mutation == 'provider_catalogue':
        tool_policy = tool_policy.model_copy(update={'provider_capabilities': {}})
    elif mutation == 'model_prompt_version':
        configurations_by_slot = dict(snapshot.configurations)
        model = configurations_by_slot['model:qwen-local']
        configurations_by_slot['model:qwen-local'] = model.model_copy(
            update={'values': {**model.values, 'prompt_version': 'northwind-fnol-claimant-v6'}}
        )
        snapshot = replace(snapshot, configurations=configurations_by_slot)
    elif mutation == 'route_policy':
        controlled_rules = controlled_rules.model_copy(update={'route_policy_version': None})
    else:
        features = features.model_copy(update={'fragmented_prompt': False})

    with pytest.raises(RuntimeConfigurationResolutionError, match=expected_error):
        RuntimeAgentPolicyResolver._validate_complete_v7_release(
            snapshot,
            instruction,
            tool_policy,
            controlled_rules,
            features,
        )


def test_published_prompt_content_is_runtime_authority_not_a_container_file_mirror() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    valid = install_initial_runtime_release(
        _settings(),
        configurations,
        releases,
        KnowledgeAdminRepository(),
    )
    assert valid is not None
    instruction_reference = valid.configuration_refs['agent_instruction']
    instruction = configurations.get(
        instruction_reference.configuration_id,
        instruction_reference.revision,
    )
    assert instruction is not None
    values = deepcopy(instruction.values)
    fragments = deepcopy(cast(list[dict[str, object]], values['fragments']))
    response_style = next(
        item for item in fragments if item['fragment_id'] == 'core.response-style'
    )
    response_style['content'] = 'Use concise claimant-facing language from this published release.'
    values['fragments'] = fragments
    published_instruction = instruction.model_copy(
        update={
            'configuration_id': 'cfg_published_prompt_authority',
            'revision': 1,
            'values': values,
            'updated_at': valid.updated_at + timedelta(seconds=1),
        }
    )
    configurations.create(published_instruction)
    references = dict(valid.configuration_refs)
    references['agent_instruction'] = ConfigurationReference(
        configuration_id=published_instruction.configuration_id,
        revision=published_instruction.revision,
    )
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_published_prompt_authority',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs=references,
            author='test',
            reason='Prove immutable published Prompt content is the Runtime authority.',
            updated_at=valid.updated_at + timedelta(seconds=1),
        )
    )

    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()

    assert policy is not None
    assert any(
        item.fragment_id == 'core.response-style' and item.content == response_style['content']
        for item in policy.instruction.fragments
    )


def test_capabilities_expose_the_repository_published_model_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only-gemini-key')
    client = TestClient(create_app(_settings()))

    response = client.get(
        '/api/v1/claims/capabilities',
        headers={'Authorization': 'Bearer synthetic-claimant'},
    )

    assert response.status_code == 200
    assert [item['id'] for item in response.json()['models']] == [
        'qwen-local',
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
        'nowcoding-gpt55',
    ]
    assert response.json()['default_model_profile_id'] == 'qwen-local'
    bedrock = next(item for item in response.json()['models'] if item['id'] == 'bedrock-nova2-lite')
    assert bedrock['availability'] == 'unavailable'
    assert bedrock['image_input'] is True
    gemini = next(
        item for item in response.json()['models'] if item['id'] == 'google-gemini35-flash-lite'
    )
    assert gemini['availability'] == 'available'
    assert gemini['published'] is True
    assert gemini['runtime_ready'] is True
    assert gemini['healthy'] is None
    assert gemini['structured_output'] is True
    assert gemini['tools'] is True
    assert gemini['image_input'] is True

    selection = client.post(
        '/api/v1/claims',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': 'unavailable-bedrock-profile',
        },
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
            'model_profile_id': 'bedrock-nova2-lite',
        },
    )
    assert selection.status_code == 422
    assert selection.json()['error']['code'] == 'MODEL_PROFILE_UNAVAILABLE'


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
