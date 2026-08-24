import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import httpx
from botocore.client import Config as BotoClientConfig
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.adapters.evidence_storage import (  # noqa: E402
    S3CompatibleObjectStorageConfig,
)
from backend.app import create_app  # noqa: E402
from backend.core.config import ObjectStorageAdapter, Settings  # noqa: E402

PAYLOAD = b'northwind synthetic MinIO evidence smoke check\n'
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def _local_client(config: S3CompatibleObjectStorageConfig) -> Any:
    if urlparse(config.endpoint_url).hostname not in {'localhost', '127.0.0.1', '::1', 'minio'}:
        raise RuntimeError('The MinIO smoke check refuses to create a bucket on a remote endpoint.')
    return boto3.client(
        's3',
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name=config.region,
        config=BotoClientConfig(signature_version='s3v4'),
    )


def _ensure_local_bucket(config: S3CompatibleObjectStorageConfig, client: Any) -> None:
    try:
        client.head_bucket(Bucket=config.bucket)
    except ClientError as error:
        code = str(error.response.get('Error', {}).get('Code', ''))
        if code not in {'404', 'NoSuchBucket', 'NotFound'}:
            raise
        client.create_bucket(Bucket=config.bucket)


def _cleanup_smoke_objects(
    config: S3CompatibleObjectStorageConfig,
    client: Any,
    claim_id: str | None,
    evidence_id: str | None,
) -> None:
    if claim_id is None or evidence_id is None:
        return
    prefix = f'claims/{claim_id}/evidence/{evidence_id}/'
    response = client.list_objects_v2(Bucket=config.bucket, Prefix=prefix)
    for item in response.get('Contents', []):
        key = item.get('Key')
        if isinstance(key, str) and key.startswith(prefix):
            client.delete_object(Bucket=config.bucket, Key=key)


def _create_claim(client: TestClient, run_id: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': f'{run_id}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    response.raise_for_status()
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def main() -> None:
    settings = Settings.from_environment()
    if settings.object_storage_adapter is not ObjectStorageAdapter.S3_COMPATIBLE:
        raise RuntimeError(
            'Set NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible before running this check.'
        )
    config = S3CompatibleObjectStorageConfig.from_environment()
    object_client = _local_client(config)
    _ensure_local_bucket(config, object_client)

    run_id = f'minio-smoke-{uuid4().hex}'
    checksum = f'sha256:{sha256(PAYLOAD).hexdigest()}'
    claim_id: str | None = None
    evidence_id: str | None = None
    try:
        with TestClient(create_app(settings)) as client:
            claim_id = _create_claim(client, run_id)
            requested = client.post(
                f'/api/v1/claims/{claim_id}/evidence/uploads',
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-upload',
                    'If-Match': '1',
                },
                json={
                    'kind': 'incident_image',
                    'original_filename': 'synthetic-damage.jpg',
                    'media_type': 'image/jpeg',
                    'size_bytes': len(PAYLOAD),
                },
            )
            requested.raise_for_status()
            upload_response = requested.json()
            evidence_id = str(upload_response['evidence_id'])
            upload = cast(dict[str, Any], upload_response['upload'])

            uploaded = httpx.request(
                method=str(upload['method']),
                url=str(upload['url']),
                headers=cast(dict[str, str], upload['headers']),
                content=PAYLOAD,
                timeout=10.0,
            )
            uploaded.raise_for_status()

            completed = client.post(
                f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-complete',
                    'If-Match': str(upload_response['revision']),
                },
                json={'upload_checksum': checksum},
            )
            completed.raise_for_status()

            # The original capability can still be valid, but it addresses only
            # staging. Reusing it must not alter the checksum-bound final object.
            replacement = b'X' * len(PAYLOAD)
            reused = httpx.request(
                method=str(upload['method']),
                url=str(upload['url']),
                headers=cast(dict[str, str], upload['headers']),
                content=replacement,
                timeout=10.0,
            )
            reused.raise_for_status()
            final_key = (
                f'claims/{claim_id}/evidence/{evidence_id}/finalised/'
                f'{checksum.removeprefix("sha256:")}'
            )
            final_response = object_client.get_object(Bucket=config.bucket, Key=final_key)
            final_body = final_response['Body']
            try:
                if final_body.read() != PAYLOAD:
                    raise RuntimeError('Reusing the upload capability changed final evidence.')
            finally:
                final_body.close()

            listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
            listed.raise_for_status()
            readiness = client.get('/health/ready')
            readiness.raise_for_status()

        evidence_items = cast(list[dict[str, Any]], listed.json()['items'])
        if evidence_items[0]['file_status'] != 'processing':
            raise RuntimeError(
                'The persisted evidence did not enter the expected processing state.'
            )
        if readiness.json()['checks']['evidence_storage'] != 'configured_service':
            raise RuntimeError('The configured object store did not report ready after the upload.')

        print(
            json.dumps(
                {
                    'claim_id': claim_id,
                    'evidence_id': evidence_id,
                    'upload_checksum': checksum,
                    'file_status': evidence_items[0]['file_status'],
                    'evidence_storage': readiness.json()['checks']['evidence_storage'],
                },
                indent=2,
            )
        )
    finally:
        _cleanup_smoke_objects(config, object_client, claim_id, evidence_id)


if __name__ == '__main__':
    main()
