from pathlib import Path

import pytest

from backend.core.config import DataRuntimeProfile, ObjectStorageAdapter, Settings
from scripts.check_runtime_profile import (
    inspect_environment,
    inspect_runtime,
    isolated_environment,
    load_environment_example,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'deploy' / 'runtime'


@pytest.mark.parametrize(
    ('filename', 'profile', 'storage'),
    [
        ('fixture.env.example', DataRuntimeProfile.FIXTURE, ObjectStorageAdapter.FIXTURE),
        (
            'local-minio.env.example',
            DataRuntimeProfile.FIXTURE,
            ObjectStorageAdapter.S3_COMPATIBLE,
        ),
        (
            'local-mvp.env.example',
            DataRuntimeProfile.LOCAL_MVP,
            ObjectStorageAdapter.S3_COMPATIBLE,
        ),
        ('mongodb.env.example', DataRuntimeProfile.MONGODB, ObjectStorageAdapter.S3_COMPATIBLE),
        ('cloudflare.env.example', DataRuntimeProfile.CLOUDFLARE, ObjectStorageAdapter.FIXTURE),
        ('aws.env.example', DataRuntimeProfile.AWS, ObjectStorageAdapter.FIXTURE),
    ],
)
def test_each_environment_example_selects_one_explicit_profile(
    filename: str,
    profile: DataRuntimeProfile,
    storage: ObjectStorageAdapter,
) -> None:
    values = load_environment_example(EXAMPLES / filename)

    with isolated_environment(values):
        settings = Settings.from_environment()

    assert settings.data_runtime_profile is profile
    assert settings.object_storage_adapter is storage


def test_fixture_example_passes_the_real_startup_preflight() -> None:
    result, exit_code = inspect_runtime(EXAMPLES / 'fixture.env.example')

    assert exit_code == 0
    assert result['status'] == 'startup_ready'
    assert result['readiness'] == {
        'persistence': 'using_fixture',
        'evidence_storage': 'using_fixture',
        'policy': 'using_fixture',
        'claim_history': 'using_fixture',
        'knowledge_documents': 'using_fixture',
        'knowledge_retrieval': 'using_fixture',
    }


def test_parsed_environment_can_be_inspected_with_a_process_accessible_override() -> None:
    values = load_environment_example(EXAMPLES / 'fixture.env.example')
    values['NORTHWIND_CORS_ALLOW_ORIGINS'] = 'http://localhost:5173'

    result, exit_code = inspect_environment(values)

    assert exit_code == 0
    assert result['status'] == 'startup_ready'


@pytest.mark.parametrize(
    'filename',
    ['mongodb.env.example', 'cloudflare.env.example', 'aws.env.example'],
)
def test_candidate_profiles_fail_before_serving_without_fixture_fallback(
    filename: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fixture_fallback() -> None:
        raise AssertionError('candidate profile attempted to construct fixture persistence')

    monkeypatch.setattr('backend.core.runtime_profiles.FixtureRepository', fixture_fallback)

    result, exit_code = inspect_runtime(EXAMPLES / filename)

    assert exit_code == 2
    assert result['status'] == 'startup_refused'
    assert 'missing or unverified capabilities' in str(result['reason'])


def test_local_minio_example_is_ready_only_with_a_verified_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AvailableMinio:
        def __init__(self, _config: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'configured_service'

    monkeypatch.setattr('backend.core.runtime_profiles.MinioEvidenceStorage', AvailableMinio)

    result, exit_code = inspect_runtime(EXAMPLES / 'local-minio.env.example')

    assert exit_code == 0
    assert result['status'] == 'startup_ready'
    assert result['readiness']['evidence_storage'] == 'configured_service'  # type: ignore[index]


def test_local_minio_example_refuses_startup_when_service_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableMinio:
        def __init__(self, _config: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'unavailable'

    monkeypatch.setattr('backend.core.runtime_profiles.MinioEvidenceStorage', UnavailableMinio)

    result, exit_code = inspect_runtime(EXAMPLES / 'local-minio.env.example')

    assert exit_code == 2
    assert result['status'] == 'startup_refused'
    assert result['readiness']['evidence_storage'] == 'unavailable'  # type: ignore[index]
    assert 'evidence_storage=unavailable' in str(result['reason'])


def test_local_mvp_example_preflights_the_complete_configured_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConnectedRepository:
        @staticmethod
        def connection_status() -> str:
            return 'verified'

        @staticmethod
        def close() -> None:
            return None

    class AvailableAdapter:
        def __init__(self, *_args: object) -> None:
            pass

        @staticmethod
        def connection_status() -> str:
            return 'configured_service'

        @staticmethod
        def get_chunk(_chunk_id: str) -> None:
            return None

        @staticmethod
        def search(_request: object) -> list[object]:
            return []

    monkeypatch.setattr(
        'backend.core.runtime_profiles.connect_mongodb_repository',
        lambda _config: ConnectedRepository(),
    )
    monkeypatch.setattr('backend.core.runtime_profiles.MinioEvidenceStorage', AvailableAdapter)
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeObjectStore.from_config',
        lambda _config: object(),
    )
    monkeypatch.setattr(
        'backend.core.runtime_profiles.S3CompatibleKnowledgeRetriever', AvailableAdapter
    )

    result, exit_code = inspect_runtime(EXAMPLES / 'local-mvp.env.example')

    assert exit_code == 0
    assert result['status'] == 'startup_ready'
    assert result['readiness'] == {
        'persistence': 'verified',
        'evidence_storage': 'configured_service',
        'policy': 'using_fixture',
        'claim_history': 'using_fixture',
        'knowledge_documents': 'configured_service',
        'knowledge_retrieval': 'configured_service',
    }


def test_environment_inspection_does_not_inherit_or_leak_managed_host_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://host-secret.example')
    monkeypatch.setenv('DATA_RUNTIME_PROFILE', 'aws')

    result, exit_code = inspect_runtime(EXAMPLES / 'fixture.env.example')

    assert exit_code == 0
    assert result['profile'] == 'fixture'
    assert 'host-secret' not in str(result)


def test_runtime_environment_loader_rejects_duplicates(tmp_path: Path) -> None:
    environment = tmp_path / 'duplicate.env.example'
    environment.write_text(
        'DATA_RUNTIME_PROFILE=fixture\nDATA_RUNTIME_PROFILE=aws\n', encoding='utf-8'
    )

    with pytest.raises(ValueError, match='invalid setting name'):
        load_environment_example(environment)


def test_backend_image_has_one_environment_selected_entrypoint() -> None:
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')

    assert 'FROM python:3.12-slim' in dockerfile
    assert 'ARG DATA_RUNTIME_PROFILE' not in dockerfile
    assert 'USER northwind' in dockerfile
    assert 'backend.main:app' in dockerfile
