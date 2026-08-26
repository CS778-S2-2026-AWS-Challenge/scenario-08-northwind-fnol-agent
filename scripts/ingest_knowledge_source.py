import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.knowledge_object_store import S3CompatibleKnowledgeObjectStore
from backend.domain.knowledge import (
    KnowledgePublicationStatus,
    KnowledgeSource,
)
from backend.services.knowledge_ingestion import (
    KnowledgeIngestionService,
    KnowledgeManifestError,
    validate_manifest_source,
)

APPROVED_MANIFEST = Path(__file__).resolve().parents[1] / 'config' / 'knowledge-sources.json'


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    document_id: str
    version: str


def load_request(path: Path) -> IngestionRequest:
    value: Any = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != {'document_id', 'version'}:
        raise ValueError('Ingestion request must contain only document_id and version.')
    if not all(isinstance(value[field], str) and value[field].strip() for field in value):
        raise ValueError('Ingestion request document_id and version must be non-empty strings.')
    return IngestionRequest(document_id=value['document_id'], version=value['version'])


def resolve_source(
    request: IngestionRequest,
    approved_sources: dict[tuple[str, str], KnowledgeSource],
) -> KnowledgeSource:
    source = approved_sources.get((request.document_id, request.version))
    if source is None:
        raise ValueError('Knowledge source is not registered in the approved manifest.')
    return source


def load_approved_sources(path: Path = APPROVED_MANIFEST) -> dict[tuple[str, str], KnowledgeSource]:
    try:
        value: Any = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise KnowledgeManifestError('Knowledge source manifest cannot be read.') from None
    if not isinstance(value, dict) or not isinstance(value.get('documents'), list):
        raise KnowledgeManifestError('Knowledge source manifest must contain a documents list.')
    sources: dict[tuple[str, str], KnowledgeSource] = {}
    for position, entry in enumerate(value['documents'], start=1):
        if not isinstance(entry, dict):
            raise KnowledgeManifestError(
                f'Knowledge source manifest entry {position} must be an object.'
            )
        try:
            source = KnowledgeSource(
                document_id=entry['document_id'],
                source_key=entry['source_key'],
                title=entry['title'],
                document_type=entry['document_type'],
                version=entry['version'],
                source_uri=entry['source_uri'],
                jurisdiction=entry['jurisdiction'],
                insurer=entry.get('insurer'),
                product=entry.get('product'),
                effective_from=_optional_datetime(entry.get('effective_from')),
                effective_to=_optional_datetime(entry.get('effective_to')),
                authority=entry['authority'],
                visibility=entry['visibility'],
                publication_status=KnowledgePublicationStatus(entry['publication_status']),
                expected_checksum=entry.get('checksum_sha256'),
            )
            validate_manifest_source(source)
        except KnowledgeManifestError:
            raise
        except (KeyError, TypeError, ValueError):
            raise KnowledgeManifestError(
                f'Knowledge source manifest entry {position} is invalid.'
            ) from None
        identity = (source.document_id, source.version)
        if identity in sources:
            raise KnowledgeManifestError('Knowledge source manifest contains a duplicate identity.')
        sources[identity] = source
    return sources


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f'Missing required setting: {name}')
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description='Ingest one approved knowledge source.')
    parser.add_argument('request', type=Path, help='Path to a non-secret ingestion request JSON.')
    arguments = parser.parse_args()
    client = boto3.client(
        's3',
        endpoint_url=required_environment('NORTHWIND_OBJECT_STORAGE_ENDPOINT'),
        aws_access_key_id=required_environment('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'),
        aws_secret_access_key=required_environment('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'),
        region_name=os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1'),
    )
    store = S3CompatibleKnowledgeObjectStore(
        client,
        os.getenv('NORTHWIND_KNOWLEDGE_BUCKET', 'northwind-knowledge'),
    )
    approved_sources = load_approved_sources()
    source = resolve_source(load_request(arguments.request), approved_sources)
    result = KnowledgeIngestionService(store, approved_sources).ingest(source)
    print(
        f'{result.status}: document={result.document_id} version={result.version} '
        f'chunks={result.chunk_count} checksum={result.source_checksum}'
    )


if __name__ == '__main__':
    main()
