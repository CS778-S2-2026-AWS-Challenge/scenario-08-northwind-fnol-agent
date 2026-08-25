import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from backend.domain.knowledge import KnowledgePublicationStatus, KnowledgeSource
from backend.services.knowledge_ingestion import (
    KnowledgeIngestionError,
    KnowledgeIngestionService,
    KnowledgeSourceNotFound,
)


class MemoryObjectStore:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.writes: list[str] = []

    def read(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def write(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> None:
        assert content_type
        assert metadata['document-id']
        self.objects[key] = data
        self.writes.append(key)


POLICY = b"""# Northwind Motor Policy

## MTR-COV-01 - Collision cover

Collision damage may be covered.

## MTR-EXC-01 - Excess

The schedule supplies the excess.
"""


def source(**changes: object) -> KnowledgeSource:
    value = KnowledgeSource(
        document_id='nw-motor-2026-1',
        source_key='knowledge/policies/MVP-2026.1/motor.md',
        title='Northwind Motor Policy',
        document_type='synthetic_policy_wording',
        version='MVP-2026.1',
        source_uri='northwind://synthetic-policy/motor/MVP-2026.1',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        publication_status=KnowledgePublicationStatus.APPROVED,
        expected_checksum=sha256(POLICY).hexdigest(),
    )
    return replace(value, **changes)  # type: ignore[arg-type]


def test_approved_source_is_indexed_once_with_traceable_chunks() -> None:
    store = MemoryObjectStore({source().source_key: POLICY})
    service = KnowledgeIngestionService(store)

    first = service.ingest(source())
    second = service.ingest(source())

    assert first.status == 'indexed'
    assert second.status == 'unchanged'
    assert first.chunk_count == 3
    assert len(store.writes) == 3
    chunks_key = 'knowledge/indexed/nw-motor-2026-1/MVP-2026.1/chunks.jsonl'
    chunks = [json.loads(line) for line in store.objects[chunks_key].splitlines()]
    assert chunks[1]['chunk_id'] == 'nw-motor-2026-1#mtr-cov-01'
    assert chunks[1]['section_path'] == 'MTR-COV-01 - Collision cover'
    assert chunks[1]['checksum'] == sha256(POLICY).hexdigest()
    assert chunks[1]['jurisdiction'] == 'NZ'


def test_missing_source_and_version_fail_explicitly() -> None:
    service = KnowledgeIngestionService(MemoryObjectStore())
    with pytest.raises(KnowledgeSourceNotFound, match='not found'):
        service.ingest(source())
    with pytest.raises(KnowledgeIngestionError, match='version is required'):
        service.ingest(source(version=''))


def test_unapproved_or_checksum_mismatched_source_is_rejected() -> None:
    store = MemoryObjectStore({source().source_key: POLICY})
    service = KnowledgeIngestionService(store)
    with pytest.raises(KnowledgeIngestionError, match='Only approved'):
        service.ingest(source(publication_status=KnowledgePublicationStatus.DRAFT))
    with pytest.raises(KnowledgeIngestionError, match='checksum'):
        service.ingest(source(expected_checksum='0' * 64))


def test_changed_content_cannot_replace_an_existing_version() -> None:
    store = MemoryObjectStore({source().source_key: POLICY})
    service = KnowledgeIngestionService(store)
    service.ingest(source())
    store.objects[source().source_key] = POLICY + b'changed'
    with pytest.raises(KnowledgeIngestionError, match='immutable'):
        service.ingest(source(expected_checksum=None))
