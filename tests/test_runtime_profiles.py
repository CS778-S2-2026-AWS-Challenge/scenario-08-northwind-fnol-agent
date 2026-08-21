from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.adapters.knowledge import (
    FixtureKnowledgeDocumentStore,
    FixtureKnowledgeRetriever,
    KnowledgeChunk,
    KnowledgeSearch,
)
from backend.app import create_app
from backend.core.config import DataRuntimeProfile, Settings
from backend.core.runtime_profiles import (
    RuntimeProfileConfigurationError,
    build_data_runtime_bundle,
)
from backend.repositories.fixture import FixtureRepository


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
    store = FixtureKnowledgeDocumentStore((applicable, wrong_product))
    retriever = FixtureKnowledgeRetriever(store)

    results = retriever.search(
        KnowledgeSearch(
            text='excess',
            jurisdiction='NZ',
            visibility='claimant',
            insurer='Northwind',
            product='motor',
            effective_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert results == [applicable]


@pytest.mark.parametrize(
    'profile',
    [DataRuntimeProfile.CLOUDFLARE, DataRuntimeProfile.MONGODB, DataRuntimeProfile.AWS],
)
def test_unimplemented_profile_fails_without_fixture_fallback(
    profile: DataRuntimeProfile,
) -> None:
    with pytest.raises(RuntimeProfileConfigurationError, match='no fixture'):
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


def test_partial_dependency_injection_cannot_mask_non_fixture_profile() -> None:
    with pytest.raises(ValueError, match='fixture profile'):
        create_app(
            Settings(data_runtime_profile=DataRuntimeProfile.MONGODB),
            evidence_storage=MockEvidenceStorage(),
        )
