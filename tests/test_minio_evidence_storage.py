from hashlib import sha256
from io import BytesIO
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
        'GetObject',
    )


def checksum(payload: bytes) -> str:
    return f'sha256:{sha256(payload).hexdigest()}'


class FakeS3Client:
    def __init__(self) -> None:
        self.presign_calls: list[dict[str, Any]] = []
        self.object_body = b'x' * 2048
        self.get_object_response: dict[str, Any] = {
            'ContentLength': 2048,
            'ContentType': 'image/jpeg',
            'Metadata': {
                'claim-id': 'clm_001',
                'evidence-id': 'evd_001',
            },
        }
        self.head_bucket_error: Exception | None = None
        self.get_object_error: Exception | None = None
        self.presign_error: Exception | None = None
        self.final_objects: dict[str, bytes] = {}
        self.copy_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def head_bucket(self, **_: Any) -> None:
        if self.head_bucket_error is not None:
            raise self.head_bucket_error

    def generate_presigned_url(self, *_: Any, **kwargs: Any) -> str:
        if self.presign_error is not None:
            raise self.presign_error
        self.presign_calls.append(kwargs)
        return 'http://localhost:9000/northwind-evidence/signed'

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.get_object_error is not None:
            raise self.get_object_error
        key = str(kwargs['Key'])
        if '/finalised/' in key:
            if key not in self.final_objects:
                raise not_found_error()
            body = self.final_objects[key]
        else:
            body = self.object_body
        return {
            **self.get_object_response,
            'ContentLength': len(body),
            'Body': BytesIO(body),
        }

    def copy_object(self, **kwargs: Any) -> None:
        self.copy_calls.append(kwargs)
        self.final_objects[str(kwargs['Key'])] = bytes(self.object_body)

    def delete_object(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)


class MissingBodyS3Client(FakeS3Client):
    def get_object(self, **_: Any) -> dict[str, Any]:
        return {'ContentLength': 0, 'ContentType': 'image/jpeg', 'Metadata': {}}


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


def test_environment_contract_hides_credentials_from_representation() -> None:
    settings = S3CompatibleObjectStorageConfig(
        endpoint_url='http://localhost:9000',
        access_key_id='sensitive-access-key',
        secret_access_key='sensitive-secret-key',
        bucket='northwind-evidence',
    )

    representation = repr(settings)

    assert 'sensitive-access-key' not in representation
    assert 'sensitive-secret-key' not in representation


def test_environment_contract_rejects_endpoint_credentials_without_echoing_them() -> None:
    embedded_secret = 'embedded-secret'

    with pytest.raises(ValueError, match='must not contain embedded credentials') as captured:
        S3CompatibleObjectStorageConfig(
            endpoint_url=f'http://user:{embedded_secret}@localhost:9000',
            access_key_id='access-key',
            secret_access_key='runtime-secret',
            bucket='northwind-evidence',
        )

    assert embedded_secret not in str(captured.value)
    assert 'runtime-secret' not in str(captured.value)


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
    assert target.storage_key == 'claims/clm_001/evidence/evd_001/staging'
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
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)

    stored = storage.complete_upload(
        claim_id='clm_001',
        evidence_id='evd_001',
        checksum=checksum(client.object_body),
        media_type='image/jpeg',
        size_bytes=2048,
    )

    assert stored.storage_key.startswith('claims/clm_001/evidence/evd_001/finalised/')
    assert stored.checksum == checksum(client.object_body)
    assert stored.source_id == 's3_compatible_evidence_storage'
    assert client.copy_calls[0]['CopySource']['Key'].endswith('/staging')
    assert client.delete_calls[0]['Key'].endswith('/staging')

    retried = storage.complete_upload(
        claim_id='clm_001',
        evidence_id='evd_001',
        checksum=checksum(client.object_body),
        media_type='image/jpeg',
        size_bytes=2048,
    )
    assert retried == stored
    assert len(client.copy_calls) == 1


def test_reusing_original_put_target_cannot_replace_finalised_evidence() -> None:
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)
    original = bytes(client.object_body)

    stored = storage.complete_upload(
        claim_id='clm_001',
        evidence_id='evd_001',
        checksum=checksum(original),
        media_type='image/jpeg',
        size_bytes=len(original),
    )
    client.object_body = b'y' * len(original)  # old PUT can only recreate staging

    assert client.final_objects[stored.storage_key] == original
    assert client.object_body != client.final_objects[stored.storage_key]


def test_finalised_evidence_can_be_read_only_with_its_claim_scoped_storage_key() -> None:
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)
    stored = storage.complete_upload(
        claim_id='clm_001',
        evidence_id='evd_001',
        checksum=checksum(client.object_body),
        media_type='image/jpeg',
        size_bytes=len(client.object_body),
    )

    assert (
        storage.read_upload(
            claim_id='clm_001', evidence_id='evd_001', storage_key=stored.storage_key
        )
        == client.object_body
    )
    assert (
        storage.read_upload(
            claim_id='clm_other', evidence_id='evd_001', storage_key=stored.storage_key
        )
        is None
    )
    assert storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=None) is None


def test_object_storage_read_rejects_proxy_uploads_missing_objects_and_oversized_bytes() -> None:
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)
    key = f'claims/clm_001/evidence/evd_001/finalised/{"a" * 64}'

    with pytest.raises(EvidenceUploadNotFound):
        storage.put_upload(claim_id='clm_001', evidence_id='evd_001', content=b'fixture-only')

    client.get_object_error = not_found_error('NoSuchKey')
    assert storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=key) is None

    client.get_object_error = None
    client.final_objects[key] = b'x' * (storage.max_size_bytes + 1)
    assert storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=key) is None


def test_object_storage_read_reports_dependency_failures() -> None:
    client = FakeS3Client()
    client.get_object_error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    storage = MinioEvidenceStorage(config(), client=client)
    key = f'claims/clm_001/evidence/evd_001/finalised/{"a" * 64}'

    with pytest.raises(EvidenceStorageUnavailable):
        storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=key)

    client.get_object_error = not_found_error('AccessDenied')
    with pytest.raises(EvidenceStorageUnavailable):
        storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=key)


def test_object_storage_read_rejects_a_response_without_a_readable_body() -> None:
    storage = MinioEvidenceStorage(config(), client=MissingBodyS3Client())
    key = f'claims/clm_001/evidence/evd_001/finalised/{"a" * 64}'

    assert storage.read_upload(claim_id='clm_001', evidence_id='evd_001', storage_key=key) is None


def test_complete_upload_rejects_checksum_that_does_not_match_object_bytes() -> None:
    client = FakeS3Client()
    storage = MinioEvidenceStorage(config(), client=client)

    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_001',
            evidence_id='evd_001',
            checksum='sha256:' + '0' * 64,
            media_type='image/jpeg',
            size_bytes=2048,
        )


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
    client.get_object_response = response
    storage = MinioEvidenceStorage(config(), client=client)

    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_001',
            evidence_id='evd_001',
            checksum=checksum(client.object_body),
            media_type='image/jpeg',
            size_bytes=2048,
        )


def test_connection_and_upload_errors_are_retryable_dependency_failures() -> None:
    client = FakeS3Client()
    client.head_bucket_error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    client.presign_error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    client.get_object_error = not_found_error('NoSuchKey')
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
            checksum=checksum(client.object_body),
            media_type='image/jpeg',
            size_bytes=2048,
        )
