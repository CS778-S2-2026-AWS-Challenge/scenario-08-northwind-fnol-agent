from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.adapters.knowledge import (
    FixtureKnowledgeDocumentStore,
    FixtureKnowledgeRetriever,
)
from backend.adapters.policy_history import MockPolicyHistoryAdapter
from backend.app import create_app
from backend.core.config import DataRuntimeProfile, ObjectStorageAdapter, Settings
from backend.core.runtime_profiles import (
    RUNTIME_CAPABILITIES,
    DataRuntimeBundle,
    RuntimeCapabilityStatus,
    RuntimeProfileConfigurationError,
    build_data_runtime_bundle,
    missing_runtime_capabilities,
    runtime_capability_statuses,
    validate_data_runtime_bundle,
)
from backend.domain.knowledge import KnowledgeChunk, KnowledgeSearch
from backend.repositories.fixture import FixtureRepository


def knowledge_search(
    *,
    jurisdiction: str = 'NZ',
    visibility: str = 'claimant',
    authority: str | None = 'synthetic_demo',
    version: str | None = '1.0',
    insurer: str | None = 'Northwind',
    product: str | None = 'motor',
    effective_at: datetime | None = datetime(2026, 8, 21, tzinfo=UTC),
) -> KnowledgeSearch:
    return KnowledgeSearch(
        text='excess',
        jurisdiction=jurisdiction,
        visibility=visibility,
        authority=authority,
        version=version,
        insurer=insurer,
        product=product,
        effective_at=effective_at,
    )


def test_environment_selects_exactly_one_known_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DATA_RUNTIME_PROFILE', 'mongodb')

    settings = Settings.from_environment()

    assert settings.data_runtime_profile is DataRuntimeProfile.MONGODB


@pytest.mark.parametrize('value', ['', 'fixture,mongodb', 'unknown'])
def test_environment_rejects_empty_mixed_and_unknown_profiles(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv('DATA_RUNTIME_PROFILE', value)

    with pytest.raises(ValueError, match='must be exactly one of'):
        Settings.from_environment()


def test_fixture_profile_builds_one_coherent_bundle() -> None:
    bundle = build_data_runtime_bundle(Settings())

    assert bundle.profile is DataRuntimeProfile.FIXTURE
    assert isinstance(bundle.repository, FixtureRepository)
    assert bundle.readiness_checks() == {
        'persistence': 'using_fixture',
        'evidence_storage': 'using_fixture',
        'policy': 'using_fixture',
        'claim_history': 'using_fixture',
        'knowledge_documents': 'using_fixture',
        'knowledge_retrieval': 'using_fixture',
    }


def test_app_lifespan_closes_an_injected_repository() -> None:
    class ClosableFixtureRepository(FixtureRepository):
        closed = False

        def close(self) -> None:
            self.closed = True

    repository = ClosableFixtureRepository()

    with TestClient(create_app(Settings(), repository=repository)):
        assert not repository.closed

    assert repository.closed


def test_bundle_reports_repository_connection_status() -> None:
    class ConnectedFixtureRepository(FixtureRepository):
        @staticmethod
        def connection_status() -> str:
            return 'verified'

    fixture_bundle = build_data_runtime_bundle(Settings())
    bundle = replace(fixture_bundle, repository=ConnectedFixtureRepository())

    assert bundle.readiness_checks()['persistence'] == 'verified'


def test_capability_table_is_complete_and_local_mvp_is_explicitly_hybrid() -> None:
    for profile in DataRuntimeProfile:
        statuses = runtime_capability_statuses(profile)
        assert tuple(statuses) == RUNTIME_CAPABILITIES

    assert set(missing_runtime_capabilities(DataRuntimeProfile.FIXTURE)) == set()
    assert set(missing_runtime_capabilities(DataRuntimeProfile.LOCAL_MVP)) == set()
    assert set(missing_runtime_capabilities(DataRuntimeProfile.MONGODB)) == set(
        RUNTIME_CAPABILITIES
    )
    assert set(missing_runtime_capabilities(DataRuntimeProfile.CLOUDFLARE)) == set(
        RUNTIME_CAPABILITIES
    )
    assert set(missing_runtime_capabilities(DataRuntimeProfile.AWS)) == set(RUNTIME_CAPABILITIES)
    assert runtime_capability_statuses(DataRuntimeProfile.MONGODB)['persistence'] == (
        'pending_confirmation'
    )
    assert runtime_capability_statuses(DataRuntimeProfile.LOCAL_MVP) == {
        'persistence': 'verified',
        'evidence_storage': 'verified',
        'policy': 'using_fixture',
        'claim_history': 'using_fixture',
        'knowledge_documents': 'verified',
        'knowledge_retrieval': 'verified',
    }


def test_local_mvp_builds_mongodb_minio_and_synthetic_lookup_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConnectedRepository(FixtureRepository):
        closed = False

        @staticmethod
        def connection_status() -> str:
            return 'verified'

        def close(self) -> None:
            self.closed = True

    class AvailableEvidenceStorage:
        def __init__(self, _config: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'configured_service'

    class AvailableKnowledge:
        def __init__(self, _store: object, _sources: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'configured_service'

        @staticmethod
        def get_chunk(_chunk_id: str) -> None:
            return None

        @staticmethod
        def search(_request: KnowledgeSearch) -> list[KnowledgeChunk]:
            return []

    repository = ConnectedRepository()
    monkeypatch.setattr(
        'backend.core.runtime_profiles.connect_mongodb_repository', lambda _config: repository
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.MinioEvidenceStorage', AvailableEvidenceStorage
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeObjectStore.from_config',
        lambda _config: object(),
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeRetriever', AvailableKnowledge
    )
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://unused')
    monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', 'northwind_test')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://minio:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'local-access')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'local-secret')

    bundle = build_data_runtime_bundle(
        Settings(
            data_runtime_profile=DataRuntimeProfile.LOCAL_MVP,
            object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE,
        )
    )

    assert bundle.repository is repository
    assert isinstance(bundle.policy_history, MockPolicyHistoryAdapter)
    assert id(bundle.knowledge_documents) == id(bundle.knowledge_retrieval)
    assert bundle.readiness_checks() == {
        'persistence': 'verified',
        'evidence_storage': 'configured_service',
        'policy': 'using_fixture',
        'claim_history': 'using_fixture',
        'knowledge_documents': 'configured_service',
        'knowledge_retrieval': 'configured_service',
    }


def test_local_mvp_requires_explicit_minio_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'backend.core.runtime_profiles.connect_mongodb_repository',
        lambda _config: pytest.fail('MongoDB must not connect for an invalid local bundle.'),
    )

    with pytest.raises(RuntimeProfileConfigurationError, match='requires'):
        build_data_runtime_bundle(Settings(data_runtime_profile=DataRuntimeProfile.LOCAL_MVP))


def test_local_mvp_fails_closed_when_a_selected_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConnectedRepository(FixtureRepository):
        closed = False

        @staticmethod
        def connection_status() -> str:
            return 'verified'

        def close(self) -> None:
            self.closed = True

    class UnavailableEvidenceStorage:
        def __init__(self, _config: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'unavailable'

    class AvailableKnowledge:
        def __init__(self, _store: object, _sources: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'configured_service'

        @staticmethod
        def get_chunk(_chunk_id: str) -> None:
            return None

        @staticmethod
        def search(_request: KnowledgeSearch) -> list[KnowledgeChunk]:
            return []

    repository = ConnectedRepository()
    monkeypatch.setattr(
        'backend.core.runtime_profiles.connect_mongodb_repository', lambda _config: repository
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.MinioEvidenceStorage', UnavailableEvidenceStorage
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeObjectStore.from_config',
        lambda _config: object(),
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeRetriever', AvailableKnowledge
    )
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://unused')
    monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', 'northwind_test')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://minio:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'local-access')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'local-secret')

    with pytest.raises(RuntimeProfileConfigurationError, match='unavailable capabilities'):
        build_data_runtime_bundle(
            Settings(
                data_runtime_profile=DataRuntimeProfile.LOCAL_MVP,
                object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE,
            )
        )

    assert repository.closed


def test_fixture_profile_fails_closed_when_explicit_s3_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableEvidenceStorage:
        def __init__(self, _config: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'unavailable'

    monkeypatch.setattr(
        'backend.core.runtime_profiles.MinioEvidenceStorage', UnavailableEvidenceStorage
    )
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://minio:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'local-access')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'local-secret')

    with pytest.raises(RuntimeProfileConfigurationError, match='unavailable capabilities'):
        build_data_runtime_bundle(
            Settings(object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE)
        )


def test_injected_bundle_is_readiness_checked_before_application_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_bundle = build_data_runtime_bundle(Settings())

    class UnavailableEvidenceStorage(MockEvidenceStorage):
        @staticmethod
        def connection_status() -> str:
            return 'unavailable'

    unavailable_bundle = replace(
        fixture_bundle,
        evidence_storage=UnavailableEvidenceStorage(),
    )

    with pytest.raises(RuntimeProfileConfigurationError, match='unavailable capabilities'):
        validate_data_runtime_bundle(Settings(), unavailable_bundle)


def test_local_mvp_allows_only_explicit_start_capable_provider_states() -> None:
    from backend.core.runtime_profiles import _START_CAPABLE_CONNECTION_STATES

    assert {'using_fixture', 'verified', 'configured_service'} == (_START_CAPABLE_CONNECTION_STATES)


def test_capability_status_table_is_returned_as_a_copy() -> None:
    statuses = runtime_capability_statuses(DataRuntimeProfile.FIXTURE)
    statuses['persistence'] = 'tampered'

    assert runtime_capability_statuses(DataRuntimeProfile.FIXTURE)['persistence'] == 'using_fixture'


def test_verified_non_fixture_capability_is_start_capable_without_fixture_label() -> None:
    assert RuntimeCapabilityStatus.USING_FIXTURE.start_capable
    assert RuntimeCapabilityStatus.VERIFIED.start_capable
    assert RuntimeCapabilityStatus.VERIFIED.value == 'verified'
    assert not RuntimeCapabilityStatus.PENDING_CONFIRMATION.start_capable
    assert not RuntimeCapabilityStatus.UNAVAILABLE.start_capable


def test_fixture_knowledge_retrieval_filters_metadata_before_text_matching() -> None:
    applicable = KnowledgeChunk(
        document_id='doc_motor_v1',
        chunk_id='chk_motor_excess',
        title='Motor excess',
        document_type='synthetic_policy_wording',
        version='1.0',
        section_path='Excess',
        page=4,
        source_uri='northwind://synthetic/motor-v1',
        jurisdiction='NZ',
        insurer='Northwind',
        product='motor',
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        authority='synthetic_demo',
        visibility='claimant',
        checksum='sha256:synthetic',
        ingested_at=datetime(2026, 8, 21, tzinfo=UTC),
        text='A standard excess may apply to accidental damage.',
    )
    wrong_product = replace(
        applicable,
        document_id='doc_home_v1',
        chunk_id='chk_home_excess',
        product='home',
    )
    unscoped_global = replace(
        applicable,
        document_id='doc_global_v1',
        chunk_id='chk_global_excess',
        insurer=None,
        product=None,
    )
    store = FixtureKnowledgeDocumentStore((applicable, wrong_product, unscoped_global))
    retriever = FixtureKnowledgeRetriever(store)

    results = retriever.search(knowledge_search())

    assert results == [applicable]


@pytest.mark.parametrize(
    'search_request',
    [
        knowledge_search(authority='unapproved'),
        knowledge_search(version='2.0'),
        knowledge_search(jurisdiction='AU'),
        knowledge_search(visibility='internal_only'),
        knowledge_search(insurer='Other Insurer'),
        knowledge_search(product='home'),
        knowledge_search(effective_at=datetime(2025, 12, 31, tzinfo=UTC)),
        knowledge_search(effective_at=datetime(2027, 1, 1, tzinfo=UTC)),
        knowledge_search(authority=None),
        knowledge_search(version=None),
        knowledge_search(insurer=None),
        knowledge_search(product=None),
        knowledge_search(effective_at=None),
    ],
)
def test_fixture_knowledge_retrieval_fails_closed_for_inapplicable_or_missing_scope(
    search_request: KnowledgeSearch,
) -> None:
    chunk = KnowledgeChunk(
        document_id='doc_motor_v1',
        chunk_id='chk_motor_excess',
        title='Motor excess',
        document_type='synthetic_policy_wording',
        version='1.0',
        section_path='Excess',
        page=4,
        source_uri='northwind://synthetic/motor-v1',
        jurisdiction='NZ',
        insurer='Northwind',
        product='motor',
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        authority='synthetic_demo',
        visibility='claimant',
        checksum='sha256:synthetic',
        ingested_at=datetime(2026, 8, 21, tzinfo=UTC),
        text='A standard excess may apply to accidental damage.',
    )
    retriever = FixtureKnowledgeRetriever(FixtureKnowledgeDocumentStore((chunk,)))

    assert retriever.search(search_request) == []


@pytest.mark.parametrize(
    'profile',
    [DataRuntimeProfile.CLOUDFLARE, DataRuntimeProfile.MONGODB, DataRuntimeProfile.AWS],
)
def test_unimplemented_profile_fails_without_fixture_fallback(
    profile: DataRuntimeProfile,
) -> None:
    with pytest.raises(
        RuntimeProfileConfigurationError,
        match='missing or unverified capabilities: persistence',
    ):
        build_data_runtime_bundle(Settings(data_runtime_profile=profile))


def test_app_rejects_bundle_and_partial_data_dependency_mix() -> None:
    bundle = build_data_runtime_bundle(Settings())

    with pytest.raises(ValueError, match='either data_runtime_bundle'):
        create_app(
            Settings(),
            repository=FixtureRepository(),
            data_runtime_bundle=bundle,
        )


def test_app_rejects_a_bundle_that_does_not_match_selected_profile() -> None:
    fixture_bundle = build_data_runtime_bundle(Settings())

    with pytest.raises(ValueError, match='does not match DATA_RUNTIME_PROFILE'):
        create_app(
            Settings(data_runtime_profile=DataRuntimeProfile.MONGODB),
            data_runtime_bundle=fixture_bundle,
        )


def test_app_rejects_a_bundle_that_does_not_match_selected_object_storage() -> None:
    fixture_bundle = build_data_runtime_bundle(Settings())

    with pytest.raises(
        RuntimeProfileConfigurationError,
        match='does not match NORTHWIND_OBJECT_STORAGE_ADAPTER',
    ):
        create_app(
            Settings(object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE),
            data_runtime_bundle=fixture_bundle,
        )


def test_matching_non_fixture_label_cannot_hide_fixture_or_mixed_dependencies() -> None:
    fixture_bundle = build_data_runtime_bundle(Settings())
    mislabeled_bundle = DataRuntimeBundle(
        profile=DataRuntimeProfile.MONGODB,
        repository=FixtureRepository(),
        evidence_storage=MockEvidenceStorage(),
        policy_history=MockPolicyHistoryAdapter(),
        knowledge_documents=fixture_bundle.knowledge_documents,
        knowledge_retrieval=fixture_bundle.knowledge_retrieval,
    )

    with pytest.raises(RuntimeProfileConfigurationError, match='not supported'):
        create_app(
            Settings(data_runtime_profile=DataRuntimeProfile.MONGODB),
            data_runtime_bundle=mislabeled_bundle,
        )


def test_partial_dependency_injection_cannot_mask_non_fixture_profile() -> None:
    with pytest.raises(ValueError, match='fixture profile'):
        create_app(
            Settings(data_runtime_profile=DataRuntimeProfile.MONGODB),
            evidence_storage=MockEvidenceStorage(),
        )
