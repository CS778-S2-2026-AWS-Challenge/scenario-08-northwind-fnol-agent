from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from backend.adapters.evidence_storage import (
    EvidenceStorageUnavailable,
    EvidenceUploadNotFound,
    EvidenceUploadTooLarge,
    MinioEvidenceStorage,
    S3CompatibleObjectStorageConfig,
    UnsupportedEvidenceMediaType,
)


def config() -> S3CompatibleObjectStorageConfig:
    return S3CompatibleObjectStorageConfig(
        endpoint_url='http://localhost:9000',
        access_key_id='minioadmin',
        secret_access_key='minioadmin',
        bucket='northwind-evidence',
    )


def not_found_error(code: str = 'NotFound') -> ClientError:
    return ClientError(
        {'Error': {'Code': code, 'Message': 'synthetic object-store error'}},
        'HeadObject',
    )


class FakeS3Client:
    def __init__(self) -> None:
        self.presign_calls: list[dict[str, Any]] = []
        self.head_object_response: dict[str, Any] = {
            'ContentLength': 2048,
            'ContentType': 'image/jpeg',
            'Metadata': {
                'claim-id': 'clm_001',
                'evidence-id': 'evd_001',
            },
        }
        self.head_bucket_error: Exception | None = None
        self.head_object_error: Exception | None = None
        self.presign_error: Exception | None = None

    def head_bucket(self, **_: Any) -> None:
        if self.head_bucket_error is not None:
            raise self.head_bucket_error

    def generate_presigned_url(self, *_: Any, **kwargs: Any) -> str:
        if self.presign_error is not None:
            raise self.presign_error
        self.presign_calls.append(kwargs)
        return 'http://localhost:9000/northwind-evidence/signed'

    def head_object(self, **_: Any) -> dict[str, Any]:
        if self.head_object_error is not None:
            raise self.head_object_error
        return self.head_object_response


def test_environment_contract_requires_runtime_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    monkeypatch.delenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', raising=False)

    with pytest.raises(ValueError, match='Missing object-storage settings'):
        S3CompatibleObjectStorageConfig.from_environment()


def test_environment_contract_parses_bucket_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'minioadmin')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'minioadmin')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_BUCKET', 'northwind-evidence')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS', '600')

    settings = S3CompatibleObjectStorageConfig.from_environment()

    assert settings.bucket == 'northwind-evidence'
    assert settings.presign_expiry_seconds == 600


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('endpoint_url', 'localhost:9000'),
        ('bucket', 'Northwind Evidence'),
        ('presign_expiry_seconds', 0),
    ],
)
def test_environment_contract_rejects_invalid_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        'endpoint_url': config().endpoint_url,
        'access_key_id': config().access_key_id,
        'secret_access_key': config().secret_access_key,
        'bucket': config().bucket,
        'region': config().region,
        'presign_expiry_seconds': config().presign_expiry_seconds,
    }
    values[field] = value

    with pytest.raises(ValueError):
        S3CompatibleObjectStorageConfig(**values)  # type: ignore[arg-type]


def test_create_target_signs_provider_metadata_and_constraints() -> None:
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)

    assert storage.connection_status() == 'configured_service'
    target = storage.create_upload_target(
        claim_id='clm_001',
        evidence_id='evd_001',
        media_type='image/jpeg',
        size_bytes=2048,
    )

    assert target.method == 'PUT'
    assert target.storage_key == 'claims/clm_001/evidence/evd_001'
    assert target.headers['Content-Type'] == 'image/jpeg'
    assert target.headers['x-amz-meta-claim-id'] == 'clm_001'
    assert client.presign_calls[0]['Params']['Metadata']['expected-size'] == '2048'
    assert client.presign_calls[0]['ExpiresIn'] == 900


@pytest.mark.parametrize(
    ('media_type', 'size_bytes', 'error_type'),
    [
        ('text/plain', 100, UnsupportedEvidenceMediaType),
        ('image/jpeg', 10_485_761, EvidenceUploadTooLarge),
    ],
)
def test_create_target_rejects_unsupported_or_oversized_objects(
    media_type: str,
    size_bytes: int,
    error_type: type[Exception],
) -> None:
    storage = MinioEvidenceStorage(config(), client=FakeS3Client())

    with pytest.raises(error_type):
        storage.create_upload_target(
            claim_id='clm_001',
            evidence_id='evd_001',
            media_type=media_type,
            size_bytes=size_bytes,
        )


def test_complete_upload_requires_matching_object_metadata() -> None:
    storage = MinioEvidenceStorage(config(), client=FakeS3Client())

    stored = storage.complete_upload(
        claim_id='clm_001',
        evidence_id='evd_001',
        checksum='sha256:' + 'a' * 64,
        media_type='image/jpeg',
        size_bytes=2048,
    )

    assert stored.storage_key == 'claims/clm_001/evidence/evd_001'


@pytest.mark.parametrize(
    'response',
    [
        {'ContentLength': 2047, 'ContentType': 'image/jpeg', 'Metadata': {}},
        {
            'ContentLength': 2048,
            'ContentType': 'application/pdf',
            'Metadata': {'claim-id': 'clm_001', 'evidence-id': 'evd_001'},
        },
        {
            'ContentLength': 2048,
            'ContentType': 'image/jpeg',
            'Metadata': {'claim-id': 'clm_other', 'evidence-id': 'evd_001'},
        },
    ],
)
def test_complete_upload_rejects_mismatched_object(response: dict[str, Any]) -> None:
    client = FakeS3Client()
    client.head_object_response = response
    storage = MinioEvidenceStorage(config(), client=client)

    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_001',
            evidence_id='evd_001',
            checksum='sha256:' + 'a' * 64,
            media_type='image/jpeg',
            size_bytes=2048,
        )


def test_connection_and_upload_errors_are_retryable_dependency_failures() -> None:
    client = FakeS3Client()
    client.head_bucket_error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    client.presign_error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    client.head_object_error = not_found_error('NoSuchKey')
    storage = MinioEvidenceStorage(config(), client=client)

    assert storage.connection_status() == 'unavailable'

    with pytest.raises(EvidenceStorageUnavailable):
        storage.create_upload_target(
            claim_id='clm_001',
            evidence_id='evd_001',
            media_type='image/jpeg',
            size_bytes=2048,
        )

    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_001',
            evidence_id='evd_001',
            checksum='sha256:' + 'a' * 64,
            media_type='image/jpeg',
            size_bytes=2048,
        )
