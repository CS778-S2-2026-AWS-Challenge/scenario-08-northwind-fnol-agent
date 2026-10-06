"""Opt-in MongoDB and MinIO acceptance for automatic PDF Evidence recovery."""

from __future__ import annotations

import os
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from threading import Event
from time import monotonic
from typing import Any, cast

import boto3
import httpx
import pytest
from botocore.client import Config as BotoClientConfig
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.config import (
    AgentRuntimeProfile,
    DataRuntimeProfile,
    IdentityMode,
    ObjectStorageAdapter,
    Settings,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelRequest,
    ModelResponse,
)

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
PDF = b'%PDF-1.4\nSynthetic police reference NZP-INTEGRATION-1129\n%%EOF\n'


class DeterministicPdfGateway:
    capabilities = ModelCapabilities(structured_output=True, document_input=True)

    def __init__(self) -> None:
        self.called = Event()
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        self.called.set()
        return ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            provider_model='openai/gpt-4o',
            provider_request_id='synthetic-pdf-integration-1129',
            structured_output={
                'facts': [
                    {
                        'field_code': 'authorities.police_report_reference',
                        'value': 'NZP-INTEGRATION-1129',
                        'confidence': 0.99,
                    }
                ]
            },
        )


def _settings(profile: AgentRuntimeProfile) -> Settings:
    return Settings(
        business_seed_path='config/business-seed.json',
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        data_runtime_profile=DataRuntimeProfile.LOCAL_MVP,
        object_storage_adapter=ObjectStorageAdapter.S3_COMPATIBLE,
        agent_runtime_profile=profile,
        model_base_url='https://openrouter.invalid/v1',
        model_profile_id='openrouter-gpt-4o',
        model_provider='openrouter',
        model_identifier='openai/gpt-4o',
        model_supports_document_input=True,
    )


@pytest.mark.integration
def test_mongodb_minio_restart_recovers_pdf_to_source_linked_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.getenv('NORTHWIND_PDF_INTEGRATION') != '1':
        pytest.skip('set NORTHWIND_PDF_INTEGRATION=1 for real MongoDB and MinIO acceptance')

    mongo_uri = os.getenv(
        'NORTHWIND_MONGODB_TEST_URI',
        'mongodb://localhost:27017/?directConnection=true&replicaSet=rs0',
    )
    database_name = f'northwind_pdf_1129_{datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")}'
    endpoint = os.getenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    access_key = os.getenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'minioadmin')
    secret_key = os.getenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'minioadmin')
    evidence_bucket = os.getenv('NORTHWIND_OBJECT_STORAGE_BUCKET', 'northwind-evidence')
    region = os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1')
    claim_id = ''
    evidence_id = ''
    mongo_client: MongoClient[Any] = MongoClient(mongo_uri, serverSelectionTimeoutMS=1_000)
    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=BotoClientConfig(signature_version='s3v4'),
    )
    try:
        try:
            hello = mongo_client.admin.command('hello')
            s3.head_bucket(Bucket=evidence_bucket)
        except Exception as error:
            pytest.skip(f'local MongoDB/MinIO unavailable: {type(error).__name__}')
        if not hello.get('isWritablePrimary', False):
            pytest.skip('local MongoDB replica set has no writable primary')

        monkeypatch.setenv('NORTHWIND_MONGODB_URI', mongo_uri)
        monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', database_name)
        monkeypatch.setenv('NORTHWIND_MONGODB_COLLECTION', 'northwind_records')
        monkeypatch.setenv('NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS', '1000')
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', endpoint)
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_PRESIGN_ENDPOINT', endpoint)
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', access_key)
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', secret_key)
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_BUCKET', evidence_bucket)
        monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_REGION', region)
        monkeypatch.setenv('NORTHWIND_KNOWLEDGE_BUCKET', 'northwind-knowledge')

        app = create_app(_settings(AgentRuntimeProfile.CONTROLLED))
        with TestClient(app) as client:
            created = client.post(
                '/api/v1/claims',
                headers={**AUTH, 'Idempotency-Key': 'pdf-integration-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            )
            assert created.status_code == 201, created.text
            claim_id = str(created.json()['claim']['claim_id'])
            requested = client.post(
                f'/api/v1/claims/{claim_id}/evidence/uploads',
                headers={
                    **AUTH,
                    'Idempotency-Key': 'pdf-integration-upload',
                    'If-Match': '1',
                },
                json={
                    'kind': 'police_report',
                    'original_filename': 'police-report.pdf',
                    'media_type': 'application/pdf',
                    'size_bytes': len(PDF),
                },
            )
            assert requested.status_code == 201, requested.text
            evidence_id = str(requested.json()['evidence_id'])
            upload = requested.json()['upload']
            uploaded = httpx.put(
                str(upload['url']),
                headers=cast(dict[str, str], upload['headers']),
                content=PDF,
                timeout=10,
            )
            assert uploaded.status_code == 200, uploaded.text
            completed = client.post(
                f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
                headers={
                    **AUTH,
                    'Idempotency-Key': 'pdf-integration-complete',
                    'If-Match': str(requested.json()['revision']),
                },
                json={'upload_checksum': f'sha256:{sha256(PDF).hexdigest()}'},
            )
            assert completed.status_code == 202, completed.text
            assert completed.json()['evidence']['file_status'] == 'processing'

        gateway = DeterministicPdfGateway()
        registry = ModelGatewayRegistry()
        registry.register('openai_compatible', lambda config: gateway)
        recovered = create_app(
            _settings(AgentRuntimeProfile.MODEL_GATEWAY),
            model_gateway_registry=registry,
        )
        with TestClient(recovered) as client:
            assert gateway.called.wait(10)
            deadline = monotonic() + 10
            pause = Event()
            while True:
                response = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=AUTH)
                assert response.status_code == 200, response.text
                item = next(
                    item for item in response.json()['items'] if item['evidence_id'] == evidence_id
                )
                if item['file_status'] == 'ready' or monotonic() >= deadline:
                    break
                pause.wait(0.1)
            assert item['file_status'] == 'ready'
            repository = recovered.state.data_runtime_bundle.repository
            claim = repository.get_claim_internal(claim_id)
            assert claim is not None
            proposal = claim.form['authorities.police_report_reference']
            assert proposal.status.value == 'proposed'
            assert proposal.source_refs == [evidence_id, f'evidence:{evidence_id}:material:1']

        readback = create_app(_settings(AgentRuntimeProfile.CONTROLLED))
        with TestClient(readback) as client:
            response = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=AUTH)
            assert response.status_code == 200, response.text
            assert response.json()['items'][0]['file_status'] == 'ready'
            claim = readback.state.data_runtime_bundle.repository.get_claim_internal(claim_id)
            assert claim is not None
            assert claim.form['authorities.police_report_reference'].value == 'NZP-INTEGRATION-1129'
        assert len(gateway.requests) == 1
    finally:
        if claim_id:
            prefix = f'claims/{claim_id}/'
            listed = s3.list_objects_v2(Bucket=evidence_bucket, Prefix=prefix)
            for value in listed.get('Contents', []):
                s3.delete_object(Bucket=evidence_bucket, Key=str(value['Key']))
        with suppress(PyMongoError):
            mongo_client.drop_database(database_name)
        mongo_client.close()
