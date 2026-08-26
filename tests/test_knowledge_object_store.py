from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from backend.adapters.knowledge_object_store import (
    KnowledgeObjectStoreUnavailable,
    S3CompatibleKnowledgeConfig,
    S3CompatibleKnowledgeObjectStore,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.error: Exception | None = None
        self.last_put: dict[str, Any] | None = None

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if self.error:
            raise self.error
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        return {'Body': BytesIO(self.objects[Key])}

    def put_object(self, **values: Any) -> None:
        if self.error:
            raise self.error
        self.last_put = values
        self.objects[values['Key']] = values['Body']


def test_s3_compatible_knowledge_store_reads_writes_and_reports_missing() -> None:
    client = FakeS3Client()
    store = S3CompatibleKnowledgeObjectStore(client, 'northwind-knowledge')

    assert store.read('missing') is None
    store.write(
        'knowledge/indexed/doc/v1/chunks.jsonl',
        b'chunk',
        content_type='application/x-ndjson',
        metadata={'document-id': 'doc'},
    )

    assert store.read('knowledge/indexed/doc/v1/chunks.jsonl') == b'chunk'
    assert client.last_put is not None
    assert client.last_put['Bucket'] == 'northwind-knowledge'
    assert client.last_put['ContentType'] == 'application/x-ndjson'


def test_s3_compatible_knowledge_store_hides_provider_failure() -> None:
    client = FakeS3Client()
    client.error = EndpointConnectionError(endpoint_url='http://localhost:9000')
    store = S3CompatibleKnowledgeObjectStore(client, 'northwind-knowledge')

    with pytest.raises(KnowledgeObjectStoreUnavailable, match='unavailable'):
        store.read('knowledge/source.md')
    with pytest.raises(KnowledgeObjectStoreUnavailable, match='unavailable'):
        store.write('key', b'value', content_type='text/plain', metadata={})


def test_knowledge_config_requires_credentials_and_reads_non_secret_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        'NORTHWIND_OBJECT_STORAGE_ENDPOINT',
        'NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID',
        'NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY',
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match='Missing knowledge-storage settings'):
        S3CompatibleKnowledgeConfig.from_environment()

    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://127.0.0.1:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'synthetic-access')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'synthetic-secret')
    monkeypatch.setenv('NORTHWIND_KNOWLEDGE_BUCKET', 'knowledge-test')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_REGION', 'local-test-1')

    config = S3CompatibleKnowledgeConfig.from_environment()

    assert config.bucket == 'knowledge-test'
    assert config.region == 'local-test-1'


def test_knowledge_store_builds_s3_compatible_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client()
    captured: dict[str, Any] = {}

    def build_client(service: str, **values: Any) -> FakeS3Client:
        captured.update({'service': service, **values})
        return client

    monkeypatch.setattr('backend.adapters.knowledge_object_store.boto3.client', build_client)
    store = S3CompatibleKnowledgeObjectStore.from_config(
        S3CompatibleKnowledgeConfig(
            endpoint_url='http://127.0.0.1:9000',
            access_key_id='synthetic-access',
            secret_access_key='synthetic-secret',
            bucket='knowledge-test',
        )
    )

    store.write('key', b'value', content_type='text/plain', metadata={})
    assert captured['service'] == 's3'
    assert captured['endpoint_url'] == 'http://127.0.0.1:9000'
    assert client.last_put is not None
    assert client.last_put['Bucket'] == 'knowledge-test'
