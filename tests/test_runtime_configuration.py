import pytest

from backend.adapters.model_gateway import default_model_gateway_registry
from backend.app import create_app
from backend.core.config import IdentityMode, ObjectStorageAdapter, Settings
from backend.core.model_gateway import ConfigurationBackedModelGateway
from backend.core.runtime_profiles import (
    RuntimeProfileConfigurationError,
    build_data_runtime_bundle,
)
from backend.domain.configuration import (
    REGISTERED_INTEGRATION_IDS,
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.knowledge_admin import KnowledgeSourceRecord, KnowledgeVersionState
from backend.domain.release import (
    ConfigurationReference,
    KnowledgeReference,
    ReleaseSetRecord,
    ReleaseSetState,
    now_utc,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)


def _configuration(
    configuration_id: str,
    domain: str,
    state: ConfigurationState = ConfigurationState.PUBLISHED,
) -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id=configuration_id,
        domain=domain,
        revision=1,
        state=state,
        impact=ConfigurationImpact.NORMAL,
        values={'value': configuration_id},
        author='test-admin',
        reason='Test runtime resolution.',
        updated_at=now_utc(),
    )


def _resolver(
    configurations: ConfigurationRepository,
    releases: ReleaseSetRepository,
    knowledge: KnowledgeAdminRepository | None = None,
) -> RuntimeConfigurationResolver:
    return RuntimeConfigurationResolver(
        configurations,
        releases,
        knowledge,
        environment='test',
        runtime_profile='fixture',
    )


def _knowledge(
    knowledge_id: str,
    version: str,
    *,
    state: KnowledgeVersionState = KnowledgeVersionState.PUBLISHED,
) -> KnowledgeSourceRecord:
    return KnowledgeSourceRecord(
        knowledge_id=knowledge_id,
        document_id='motor-policy',
        version=version,
        source_key=f'knowledge/policies/{version}.md',
        title='Motor policy',
        document_type='policy',
        source_uri='https://example.invalid/motor-policy',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        state=state,
        revision=1,
        author='test-admin',
        updated_at=now_utc(),
    )


def _model_configuration(
    configuration_id: str = 'cfg_qwen',
    profile_id: str = 'qwen-local',
    *,
    configuration_key: str | None = None,
) -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id=configuration_id,
        domain='model',
        configuration_key=configuration_key or profile_id,
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values={
            'protocol': 'openai_compatible',
            'provider': 'qwen-local',
            'model_identifier': 'qwen3.8-27b',
            'base_url': 'http://model.example/v1',
            'credential_environment_variable': None,
            'profile_id': profile_id,
            'purpose': 'agent_turn',
            'privacy_class': 'synthetic_fnol',
            'prompt_version': 'northwind-fnol-motor-claimant-v4',
            'evaluation_status': 'configured',
            'timeout_seconds': 30.0,
            'structured_output': True,
            'tools': True,
        },
        author='test-admin',
        reason='Test published model profile.',
        updated_at=now_utc(),
    )


def test_resolver_uses_only_referenced_published_records() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    model = _configuration('cfg_model', 'model')
    feature = _configuration('cfg_feature', 'feature')
    configurations.create(model)
    configurations.create(feature)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_runtime',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                'model': ConfigurationReference(
                    configuration_id=model.configuration_id,
                    revision=model.revision,
                )
            },
            author='test-admin',
            reason='Use one model release.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    snapshot = _resolver(configurations, releases).snapshot()

    assert snapshot.release_set_id == 'rel_runtime'
    assert snapshot.get('model') == model
    with pytest.raises(RuntimeConfigurationResolutionError):
        snapshot.get('feature')


def test_resolver_rejects_release_reference_that_is_not_published() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    draft = _configuration('cfg_draft', 'model', ConfigurationState.DRAFT)
    configurations.create(draft)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_invalid',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                'model': ConfigurationReference(
                    configuration_id=draft.configuration_id,
                    revision=draft.revision,
                )
            },
            author='test-admin',
            reason='Exercise invalid references.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError):
        _resolver(configurations, releases).snapshot()


def test_resolver_keeps_legacy_fallback_when_no_release_exists() -> None:
    configurations = ConfigurationRepository()
    model = _configuration('cfg_model', 'model')
    configurations.create(model)

    resolver = _resolver(configurations, ReleaseSetRepository())

    assert resolver.snapshot().release_set_id is None
    assert resolver.resolve('model') == model
    assert resolver.resolve('feature') is None


def test_resolver_uses_release_selected_knowledge_version() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    selected = _knowledge('knw_selected', '2026.1')
    newer = _knowledge('knw_newer', '2026.2')
    knowledge.create(selected)
    knowledge.create(newer)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_knowledge',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            knowledge_refs={
                'motor': KnowledgeReference(
                    knowledge_id=selected.knowledge_id,
                    revision=selected.revision,
                )
            },
            author='test-admin',
            reason='Pin the knowledge version for this runtime.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    resolver = _resolver(configurations, releases, knowledge)

    assert resolver.resolve_knowledge('motor') == selected


def test_active_release_without_product_knowledge_does_not_fallback() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    knowledge = KnowledgeAdminRepository()
    latest = _knowledge('knw_latest', '2026.2')
    knowledge.create(latest)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_missing_knowledge',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            author='test-admin',
            reason='Exercise missing knowledge selection.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError):
        _resolver(configurations, releases, knowledge).resolve_knowledge('motor')


def test_resolver_uses_only_release_selected_integrations() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    selected = ConfigurationRecord(
        configuration_id='cfg_selected_assessor',
        domain='integration',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={
            'service_id': 'assessor_service',
            'capability': 'assessor_routing',
            'source': 'fixture',
        },
        author='test-admin',
        reason='Select assessor integration.',
        updated_at=now_utc(),
    )
    unselected = selected.model_copy(
        update={
            'configuration_id': 'cfg_unselected_assessor',
            'reason': 'A newer publication outside this release.',
            'updated_at': now_utc(),
        }
    )
    configurations.create(selected)
    configurations.create(unselected)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_integrations',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            integration_refs={
                'assessor_service': ConfigurationReference(
                    configuration_id=selected.configuration_id,
                    revision=selected.revision,
                )
            },
            author='test-admin',
            reason='Pin the integration set.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    assert _resolver(configurations, releases).resolve_integrations() == (selected,)


def test_release_set_model_is_authoritative_over_bootstrap_settings() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    model = ConfigurationRecord(
        configuration_id='cfg_published_model',
        domain='model',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values={
            'protocol': 'openai_compatible',
            'provider': 'published-provider',
            'model_identifier': 'published-model',
            'base_url': 'https://published.example/v1',
            'credential_environment_variable': None,
            'profile_id': 'published-profile',
            'purpose': 'agent_turn',
            'privacy_class': 'synthetic_fnol',
            'prompt_version': 'northwind-fnol-motor-claimant-v4',
            'evaluation_status': 'configured',
            'timeout_seconds': 12.0,
            'structured_output': True,
            'tools': False,
        },
        author='test-admin',
        reason='Publish a model independent of bootstrap settings.',
        updated_at=now_utc(),
    )
    configurations.create(model)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_model',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                'model': ConfigurationReference(
                    configuration_id=model.configuration_id,
                    revision=model.revision,
                )
            },
            author='test-admin',
            reason='Use the published model.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )
    resolver = _resolver(configurations, releases)
    gateway = ConfigurationBackedModelGateway(
        Settings(
            environment='test',
            model_protocol_adapter='openai_compatible',
            model_base_url='https://bootstrap.example/v1',
            model_identifier='bootstrap-model',
            model_supports_structured_output=False,
        ),
        configurations,
        default_model_gateway_registry(),
        runtime_configuration_resolver=resolver,
    )

    assert gateway.capabilities.structured_output is True


def test_published_data_profile_controls_object_storage_selection() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    data_profile = ConfigurationRecord(
        configuration_id='cfg_data_profile',
        domain='data_profile',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values={'data_runtime_profile': 'fixture', 'object_storage_adapter': 'fixture'},
        author='test-admin',
        reason='Select the fixture object store.',
        updated_at=now_utc(),
    )
    configurations.create(data_profile)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_data_profile',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                'data_profile': ConfigurationReference(
                    configuration_id=data_profile.configuration_id,
                    revision=data_profile.revision,
                )
            },
            author='test-admin',
            reason='Use the selected data profile.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )
    bootstrap = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE,
    )
    bundle = build_data_runtime_bundle(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    )

    app = create_app(
        bootstrap,
        data_runtime_bundle=bundle,
        configuration_repository=configurations,
        release_set_repository=releases,
    )
    assert app.state.settings.object_storage_adapter.value == 'fixture'


def test_published_data_profile_must_match_process_runtime_profile() -> None:
    configurations = ConfigurationRepository()
    releases = ReleaseSetRepository()
    data_profile = _configuration('cfg_wrong_profile', 'data_profile')
    data_profile = data_profile.model_copy(
        update={
            'values': {
                'data_runtime_profile': 'local_mvp',
                'object_storage_adapter': 's3_compatible',
            }
        }
    )
    configurations.create(data_profile)
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_wrong_profile',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={
                'data_profile': ConfigurationReference(
                    configuration_id=data_profile.configuration_id,
                    revision=data_profile.revision,
                )
            },
            author='test-admin',
            reason='Exercise profile mismatch.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    with pytest.raises(RuntimeProfileConfigurationError):
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            configuration_repository=configurations,
            release_set_repository=releases,
        )


def test_snapshot_model_selects_profile_key_and_legacy_fallback() -> None:
    qwen = _model_configuration()
    snapshot = _resolver(ConfigurationRepository(), ReleaseSetRepository()).snapshot()

    profile_snapshot = snapshot.__class__(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel-models',
        configurations={'model:qwen-local': qwen},
        integrations={},
        knowledge={},
    )

    assert profile_snapshot.model('qwen-local') == qwen
    assert profile_snapshot.model() == qwen
    with pytest.raises(RuntimeConfigurationResolutionError):
        profile_snapshot.model('missing-profile')
    assert snapshot.model() is None
    assert snapshot.model('missing-profile') is None


def test_resolver_fallback_selects_profile_and_published_knowledge() -> None:
    configurations = ConfigurationRepository()
    qwen = _model_configuration()
    default_model = _model_configuration(
        configuration_id='cfg_default',
        profile_id='default-model',
        configuration_key='default',
    )
    configurations.create(qwen)
    configurations.create(default_model)
    knowledge = KnowledgeAdminRepository()
    selected = _knowledge('knw_fallback', '2026.1')
    knowledge.create(selected)
    resolver = _resolver(configurations, ReleaseSetRepository(), knowledge)

    assert resolver.resolve_model('qwen-local') == qwen
    assert resolver.resolve_model() == default_model
    assert resolver.resolve_knowledge('motor') == selected
    assert _resolver(configurations, ReleaseSetRepository()).resolve_knowledge('motor') is None


def test_release_snapshot_rejects_missing_knowledge_repository_and_invalid_records() -> None:
    releases = ReleaseSetRepository()
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel-invalid-knowledge',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            knowledge_refs={'motor': KnowledgeReference(knowledge_id='missing', revision=1)},
            author='test-admin',
            reason='Exercise invalid knowledge references.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    with pytest.raises(RuntimeConfigurationResolutionError, match='no knowledge repository'):
        _resolver(ConfigurationRepository(), releases).snapshot()

    knowledge = KnowledgeAdminRepository()
    knowledge.create(_knowledge('knw_draft', '2026.1', state=KnowledgeVersionState.DRAFT))
    with pytest.raises(RuntimeConfigurationResolutionError, match='published knowledge'):
        _resolver(ConfigurationRepository(), releases, knowledge).snapshot()


def test_resolver_fallback_and_release_integrations_are_explicit() -> None:
    configurations = ConfigurationRepository()
    integration = ConfigurationRecord(
        configuration_id='cfg_assessor',
        domain='integration',
        configuration_key=REGISTERED_INTEGRATION_IDS[0],
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.NORMAL,
        values={'service_id': REGISTERED_INTEGRATION_IDS[0]},
        author='test-admin',
        reason='Test fallback integration.',
        updated_at=now_utc(),
    )
    configurations.create(integration)

    resolver = _resolver(configurations, ReleaseSetRepository())

    assert resolver.resolve_integrations() == (integration,)
