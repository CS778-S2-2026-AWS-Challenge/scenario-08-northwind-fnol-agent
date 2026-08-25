from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from typing import Any, cast

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MinioEvidenceStorage
from backend.app import create_app
from backend.core.config import ObjectStorageAdapter
from backend.services.support import now_utc

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
PAYLOAD = b'northwind-minio-fastapi-smoke'


class FastApiS3Client:
    def __init__(self) -> None:
        self.presigned_params: dict[str, Any] | None = None
        self.head_bucket_error: Exception | None = None
        self.presign_error: Exception | None = None
        self.object_body = PAYLOAD
        self.object_reads = 0
        self.presign_count = 0
        self.final_body: bytes | None = None

    def head_bucket(self, **_: Any) -> None:
        if self.head_bucket_error is not None:
            raise self.head_bucket_error

    def generate_presigned_url(self, *_: Any, **kwargs: Any) -> str:
        if self.presign_error is not None:
            raise self.presign_error
        self.presign_count += 1
        self.presigned_params = cast(dict[str, Any], kwargs['Params'])
        return f'http://localhost:9000/northwind-evidence/signed-{self.presign_count}'

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        assert self.presigned_params is not None
        if '/finalised/' in str(kwargs['Key']) and self.final_body is None:
            from botocore.exceptions import ClientError

            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        self.object_reads += 1
        body = self.final_body if '/finalised/' in str(kwargs['Key']) else self.object_body
        assert body is not None
        return {
            'ContentLength': len(body),
            'ContentType': self.presigned_params['ContentType'],
            'Metadata': self.presigned_params['Metadata'],
            'Body': BytesIO(body),
        }

    def copy_object(self, **_: Any) -> None:
        self.final_body = bytes(self.object_body)

    def delete_object(self, **_: Any) -> None:
        return None


def configure_minio_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ADAPTER', 's3_compatible')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'local-access-key')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'local-secret-key')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_BUCKET', 'northwind-evidence')


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def test_environment_composes_minio_through_the_fastapi_evidence_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_minio_environment(monkeypatch)
    s3_client = FastApiS3Client()
    monkeypatch.setattr(
        'backend.adapters.evidence_storage.boto3.client',
        lambda *_args, **_kwargs: s3_client,
    )

    app = create_app()
    assert app.state.settings.object_storage_adapter is ObjectStorageAdapter.S3_COMPATIBLE
    assert isinstance(app.state.evidence_storage, MinioEvidenceStorage)

    with TestClient(app) as client:
        claim_id = create_claim(client, 'minio-fastapi-claim')
        requested = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'minio-fastapi-upload',
                'If-Match': '1',
            },
            json={
                'kind': 'incident_image',
                'original_filename': 'damage.jpg',
                'media_type': 'image/jpeg',
                'size_bytes': len(PAYLOAD),
            },
        )
        assert requested.status_code == 201
        upload = requested.json()
        evidence_id = str(upload['evidence_id'])
        assert upload['upload']['url'].startswith('http://localhost:9000/')
        assert upload['upload']['headers']['x-amz-meta-claim-id'] == claim_id

        completed = client.post(
            f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'minio-fastapi-complete',
                'If-Match': str(upload['revision']),
            },
            json={'upload_checksum': f'sha256:{sha256(PAYLOAD).hexdigest()}'},
        )
        listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
        readiness = client.get('/health/ready')

    assert completed.status_code == 202
    assert s3_client.object_reads == 2
    assert listed.status_code == 200
    assert listed.json()['items'][0]['file_status'] == 'processing'
    assert readiness.status_code == 200
    assert readiness.json()['status'] == 'degraded'
    assert readiness.json()['checks']['evidence_storage'] == 'configured_service'
    public_payload = f'{requested.text}{completed.text}{listed.text}{readiness.text}'
    assert 'local-access-key' not in public_payload
    assert 'local-secret-key' not in public_payload
    assert '/finalised/' not in public_payload


def test_expired_idempotent_replay_resigns_without_duplicate_or_revision_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_minio_environment(monkeypatch)
    s3_client = FastApiS3Client()
    monkeypatch.setattr(
        'backend.adapters.evidence_storage.boto3.client',
        lambda *_args, **_kwargs: s3_client,
    )
    app = create_app()

    with TestClient(app) as client:
        claim_id = create_claim(client, 'expired-replay-claim')
        headers = {
            **CLAIMANT_AUTH,
            'Idempotency-Key': 'expired-replay-upload',
            'If-Match': '1',
        }
        payload = {
            'kind': 'incident_image',
            'original_filename': 'damage.jpg',
            'media_type': 'image/jpeg',
            'size_bytes': len(PAYLOAD),
        }
        first = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads', headers=headers, json=payload
        )
        monkeypatch.setattr(
            'backend.services.evidence.now_utc', lambda: now_utc() + timedelta(hours=1)
        )
        replay = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads', headers=headers, json=payload
        )
        claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
        evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)

    assert first.status_code == replay.status_code == 201
    assert replay.json()['evidence_id'] == first.json()['evidence_id']
    assert replay.json()['revision'] == first.json()['revision'] == 2
    assert replay.json()['upload']['url'] != first.json()['upload']['url']
    assert claim.json()['revision'] == 2
    assert len(evidence.json()['items']) == 1


def test_real_presign_exposes_only_short_lived_addressing_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_minio_environment(monkeypatch)
    app = create_app()

    with TestClient(app) as client:
        claim_id = create_claim(client, 'real-presign-claim')
        response = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'real-presign-upload',
                'If-Match': '1',
            },
            json={
                'kind': 'incident_image',
                'original_filename': 'damage.jpg',
                'media_type': 'image/jpeg',
                'size_bytes': len(PAYLOAD),
            },
        )
        listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)

    assert response.status_code == 201
    capability = response.json()['upload']['url']
    assert 'northwind-evidence' in capability
    assert 'X-Amz-Credential=local-access-key' in capability
    assert 'local-secret-key' not in response.text
    assert '/staging' in capability
    assert '/finalised/' not in response.text
    assert '/staging' not in listed.text


def test_configured_minio_outage_is_visible_and_keeps_claim_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_minio_environment(monkeypatch)
    s3_client = FastApiS3Client()
    outage = EndpointConnectionError(endpoint_url='http://localhost:9000')
    s3_client.head_bucket_error = outage
    s3_client.presign_error = outage
    monkeypatch.setattr(
        'backend.adapters.evidence_storage.boto3.client',
        lambda *_args, **_kwargs: s3_client,
    )
    app = create_app()

    with TestClient(app) as client:
        claim_id = create_claim(client, 'minio-outage-claim')
        failed = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'minio-outage-upload',
                'If-Match': '1',
            },
            json={
                'kind': 'incident_image',
                'original_filename': 'damage.jpg',
                'media_type': 'image/jpeg',
                'size_bytes': len(PAYLOAD),
            },
        )
        claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
        readiness = client.get('/health/ready')

    assert failed.status_code == 503
    assert failed.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert failed.json()['error']['retryable'] is True
    assert claim.status_code == 200
    assert claim.json()['revision'] == 1
    assert readiness.json()['status'] == 'unavailable'
    assert readiness.json()['checks']['evidence_storage'] == 'unavailable'


def test_s3_compatible_selection_fails_startup_when_credentials_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ADAPTER', 's3_compatible')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    monkeypatch.delenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', raising=False)

    with pytest.raises(ValueError, match='Missing object-storage settings'):
        create_app()
