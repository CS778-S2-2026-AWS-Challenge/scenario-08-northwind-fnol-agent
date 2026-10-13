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
from backend.domain.knowledge_admin import KnowledgeVersionState
from backend.domain.release import ConfigurationReference, ReleaseSetRecord, ReleaseSetState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.initial_runtime_release import install_initial_runtime_release
from backend.services.knowledge_admin import record_from_source
from backend.services.knowledge_manifest import load_approved_sources
from backend.services.runtime_agent_policy import RuntimeAgentPolicyResolver
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)


def _binding(
    profile_id: str,
    *,
    prompt_version: str = 'northwind-fnol-claimant-v8',
) -> ModelRuntimeBinding:
    is_qwen = profile_id == 'qwen-local'
    is_openrouter = profile_id == 'openrouter-gpt-4o'
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
            else ('google-ai-studio' if is_google else ('qwen-local' if is_qwen else 'openrouter'))
        ),
        model_identifier=(
            'global.amazon.nova-2-lite-v1:0'
            if is_bedrock
            else (
                'gemini-3.5-flash-lite'
                if is_google
                else ('qwen3.8-27b' if is_qwen else 'openai/gpt-4o')
            )
        ),
        base_url=(
            'https://bedrock-runtime.ap-southeast-2.amazonaws.com'
            if is_bedrock
            else (
                'https://generativelanguage.googleapis.com/v1beta'
                if is_google
                else ('http://qwen.test/v1' if is_qwen else 'https://openrouter.ai/api/v1')
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
        document_input=is_openrouter or is_google,
        structured_output_method='json_object' if is_qwen else 'json_schema',
    )


def _settings() -> Settings:
    bindings = (
        _binding('qwen-local'),
        _binding('openrouter-gpt-4o'),
        _binding('bedrock-nova2-lite'),
        _binding('google-gemini35-flash-lite'),
    )
    return Settings(
        business_seed_path='config/business-seed.json',
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='openrouter-gpt-4o',
        model_provider='openrouter',
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
        'model:openrouter-gpt-4o',
        'model:bedrock-nova2-lite',
        'model:google-gemini35-flash-lite',
    }
    assert set(first.knowledge_refs) == {'motor', 'home', 'contents'}
    assert len(releases.list_release_sets('test', 'fixture')) == 1
    assert len(configurations.list_configurations()) == 8
    assert {
        (record.product, record.version, record.state) for record in knowledge.list(limit=100)
    } == {
        ('motor', '2026.2', KnowledgeVersionState.PUBLISHED),
        ('home', '2026.2', KnowledgeVersionState.PUBLISHED),
        ('contents', '2026.2', KnowledgeVersionState.PUBLISHED),
    }
    serialized = json.dumps(
        [record.model_dump(mode='json') for record in configurations.list_configurations()]
    )
    assert 'NORTHWIND_MODEL_API_KEY' in serialized
    assert 'provider-secret' not in serialized
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            knowledge,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    assert policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    assert policy.instruction.composition_mode == 'fragmented'
    assert len(policy.instruction.fragments) == 16
    assert {item.profile_id for item in policy.tool_policy.request_profiles} == {
        'claimant.deep-review.v1',
        'claimant.evidence-history.v1',
        'claimant.lookup.v1',
        'claimant.media.v1',
        'claimant.turn.v1',
    }
    assert set(policy.tool_policy.provider_capabilities) == {
        'qwen-local',
        'openrouter-gpt-4o',
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
    }
    assert {
        str(record.values['profile_id']): record.values['timeout_seconds']
        for record in configurations.list_configurations('model')
    } == {
        'qwen-local': 180.0,
        'openrouter-gpt-4o': 180.0,
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
    openrouter = next(
        record
        for record in configurations.list_configurations('model')
        if record.values['profile_id'] == 'openrouter-gpt-4o'
    )
    assert openrouter.values['document_input'] is True
    qwen = next(
        record
        for record in configurations.list_configurations('model')
        if record.values['profile_id'] == 'qwen-local'
    )
    assert qwen.values['structured_output_method'] == 'json_object'
    assert policy.controlled_rules.context_budget_policy is not None
    assert policy.features.verified_rolling_summary is True
    assert policy.features.isolated_execution is True
    snapshot = RuntimeConfigurationResolver(
        configurations,
        releases,
        environment='test',
        runtime_profile='fixture',
        knowledge_repository=knowledge,
    ).snapshot()
    selected_versions: dict[str, str] = {}
    for product in ('motor', 'home', 'contents'):
        source = snapshot.knowledge_for_product(product)
        assert source is not None
        selected_versions[product] = source.version
    assert selected_versions == {'motor': '2026.2', 'home': '2026.2', 'contents': '2026.2'}


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


def test_fresh_v8_release_publishes_atomic_prompt_schema_and_default_model() -> None:
    settings = _settings()
    bindings = tuple(
        binding.model_copy(update={'prompt_version': 'northwind-fnol-claimant-v8'})
        for binding in settings.model_runtime_bindings
    )
    settings = replace(settings, model_runtime_bindings=bindings)
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    release = install_initial_runtime_release(settings, configurations, releases, knowledge)
    assert release is not None
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            knowledge,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    assert policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    assert policy.instruction.manifest_version == 'northwind-fnol-claimant-v8'
    assert {item.profile_id for item in policy.tool_policy.request_profiles} == {
        'claimant.turn.v1',
        'claimant.media.v1',
        'claimant.lookup.v1',
        'claimant.evidence-history.v1',
        'claimant.deep-review.v1',
    }
    assert 'claimant.turn.v1' in policy.tool_policy.schema_registry
    assert settings.model_profile_id == 'openrouter-gpt-4o'
    model_ref = release.configuration_refs['model:openrouter-gpt-4o']
    model = configurations.get(model_ref.configuration_id, model_ref.revision)
    assert model is not None
    assert model.values['prompt_version'] == 'northwind-fnol-claimant-v8'
    assert model.values['model_identifier'] == 'openai/gpt-4o'
    # Governance labels must track the actual published prompt generation, not a
    # suffix baked in when this composer only ever served v7 releases.
    assert policy.tool_policy.policy_version == 'northwind-fnol-agent-tools-v8'
    assert policy.controlled_rules.rules_version == 'northwind-fnol-controlled-rules-v8'
    assert policy.controlled_rules.route_policy_version == 'northwind-turn-router-v8'
    assert policy.controlled_rules.context_catalogue_version == 'northwind-context-catalogue-v8'
    assert policy.features.feature_version == 'northwind-fnol-agent-features-v8'


def test_v8_startup_preserves_existing_v7_release_for_explicit_publication() -> None:
    settings = _settings()
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    original = install_initial_runtime_release(settings, configurations, releases, knowledge)
    upgraded_settings = replace(
        settings,
        model_runtime_bindings=tuple(
            binding.model_copy(update={'prompt_version': 'northwind-fnol-claimant-v8'})
            for binding in settings.model_runtime_bindings
        ),
    )
    current = install_initial_runtime_release(
        upgraded_settings, configurations, releases, knowledge
    )
    assert current == original
    assert len(releases.list_release_sets('test', 'fixture')) == 1


def test_repository_managed_v7_release_upgrades_to_current_catalogue() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    original = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    assert original is not None
    stale_refs = {
        slot: reference
        for slot, reference in original.configuration_refs.items()
        if slot not in {'model:bedrock-nova2-lite', 'model:google-gemini35-flash-lite'}
    }
    stale = original.model_copy(
        update={
            'revision': original.revision + 1,
            'configuration_refs': stale_refs,
            'updated_at': original.updated_at + timedelta(seconds=1),
        }
    )
    releases.save(stale, original.revision)

    with pytest.raises(RuntimeConfigurationResolutionError, match='model catalogue'):
        RuntimeAgentPolicyResolver(
            RuntimeConfigurationResolver(
                configurations,
                releases,
                knowledge,
                environment='test',
                runtime_profile='fixture',
            )
        ).resolve_for_turn()

    upgraded = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    repeated = install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert upgraded is not None
    assert repeated is not None
    assert upgraded.release_set_id != original.release_set_id
    assert repeated.release_set_id == upgraded.release_set_id
    assert set(upgraded.configuration_refs) == set(original.configuration_refs)
    superseded = releases.get(original.release_set_id)
    assert superseded is not None
    assert superseded.state is ReleaseSetState.SUPERSEDED
    assert len(releases.list_release_sets('test', 'fixture')) == 2
    assert len(configurations.list_configurations()) == 8
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            knowledge,
            environment='test',
            runtime_profile='fixture',
        )
    ).resolve_for_turn()
    assert policy is not None
    assert set(policy.tool_policy.provider_capabilities) == {
        'qwen-local',
        'openrouter-gpt-4o',
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
    }


def test_repository_managed_release_adds_missing_approved_knowledge_refs() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    original = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    assert original is not None
    legacy = original.model_copy(
        update={
            'revision': original.revision + 1,
            'knowledge_refs': {},
            'updated_at': original.updated_at + timedelta(seconds=1),
        }
    )
    releases.save(legacy, original.revision)

    upgraded = install_initial_runtime_release(_settings(), configurations, releases, knowledge)
    repeated = install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert upgraded is not None
    assert repeated is not None
    assert upgraded.release_set_id != original.release_set_id
    assert repeated.release_set_id == upgraded.release_set_id
    assert set(upgraded.knowledge_refs) == {'motor', 'home', 'contents'}
    superseded = releases.get(original.release_set_id)
    assert superseded is not None
    assert superseded.state is ReleaseSetState.SUPERSEDED


def test_initial_release_rejects_mismatched_manifest_knowledge_record() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    source = next(
        source for source in load_approved_sources().values() if source.product == 'motor'
    )
    record = record_from_source(knowledge, source, 'operator', content=None).model_copy(
        update={
            'title': 'Different published wording',
            'state': KnowledgeVersionState.PUBLISHED,
        }
    )
    knowledge.create(record)

    with pytest.raises(ValueError, match='does not match the repository-approved manifest'):
        install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert releases.list_release_sets() == []


def test_operator_owned_active_release_is_not_replaced() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_operator_active',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            author='operator',
            reason='The operator owns this active release.',
            updated_at=datetime.now(UTC),
        )
    )

    result = install_initial_runtime_release(_settings(), configurations, releases, knowledge)

    assert result is not None
    assert result.release_set_id == 'rel_operator_active'
    assert configurations.list_configurations() == []
    assert len(releases.list_release_sets('test', 'fixture')) == 1


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
        model_runtime_bindings=tuple(
            binding.model_copy(update={'prompt_version': 'northwind-fnol-claimant-v6'})
            if binding.profile_id == 'openrouter-gpt-4o'
            else binding
            for binding in base.model_runtime_bindings
        ),
    )
    with pytest.raises(ValueError, match='superseded prompt versions are archived'):
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
            knowledge,
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
            knowledge,
            environment='test',
            runtime_profile='fixture',
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError, match=expected_error):
        resolver.resolve_for_turn()


@pytest.mark.parametrize(
    ('mutation', 'expected_error'),
    [
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
    knowledge = KnowledgeAdminRepository()
    valid = install_initial_runtime_release(
        _settings(),
        configurations,
        releases,
        knowledge,
    )
    assert valid is not None
    policy = RuntimeAgentPolicyResolver(
        RuntimeConfigurationResolver(
            configurations,
            releases,
            knowledge,
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

    if mutation == 'fragment_budget':
        fragments = list(instruction.fragments)
        fragments[0] = fragments[0].model_copy(update={'content': 'oversized ' * 1000})
        instruction = instruction.model_copy(update={'fragments': fragments})
    elif mutation == 'schema_contract':
        schemas = deepcopy(tool_policy.schema_registry)
        schemas['claimant.evidence-action.v1'] = {'type': 'object'}
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
        RuntimeAgentPolicyResolver._validate_complete_release(
            snapshot,
            instruction,
            tool_policy,
            controlled_rules,
            features,
        )


def test_published_prompt_content_is_runtime_authority_not_a_container_file_mirror() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    valid = install_initial_runtime_release(
        _settings(),
        configurations,
        releases,
        knowledge,
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
            knowledge,
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
    monkeypatch.setenv('NORTHWIND_MODEL_API_KEY', 'test-only-openrouter-key')
    client = TestClient(create_app(_settings()))

    response = client.get(
        '/api/v1/claims/capabilities',
        headers={'Authorization': 'Bearer synthetic-claimant'},
    )

    assert response.status_code == 200
    model_ids = [item['id'] for item in response.json()['models']]
    assert model_ids == [
        'openrouter-gpt-4o',
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
        'qwen-local',
    ]
    assert response.json()['default_model_profile_id'] == 'openrouter-gpt-4o'
    openrouter = next(
        item for item in response.json()['models'] if item['id'] == 'openrouter-gpt-4o'
    )
    assert openrouter['document_input'] is True
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


@pytest.mark.parametrize('superseded', ['northwind-fnol-claimant-v6', 'northwind-fnol-claimant-v7'])
def test_superseded_prompt_bindings_cannot_be_published(superseded: str) -> None:
    base = _settings()
    archived = replace(
        base,
        model_runtime_bindings=tuple(
            binding.model_copy(update={'prompt_version': superseded})
            for binding in base.model_runtime_bindings
        ),
    )

    with pytest.raises(ValueError, match='superseded prompt versions are archived'):
        install_initial_runtime_release(
            archived,
            ConfigurationRepository(),
            ReleaseSetRepository(),
            KnowledgeAdminRepository(),
        )
