import argparse
import json
import os
import sys
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
from backend.services.knowledge_ingestion import KnowledgeIngestionService


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def load_source(path: Path) -> KnowledgeSource:
    value: dict[str, Any] = json.loads(path.read_text(encoding='utf-8'))
    return KnowledgeSource(
        document_id=value['document_id'],
        source_key=value['source_key'],
        title=value['title'],
        document_type=value['document_type'],
        version=value['version'],
        source_uri=value['source_uri'],
        jurisdiction=value['jurisdiction'],
        insurer=value.get('insurer'),
        product=value.get('product'),
        effective_from=_optional_datetime(value.get('effective_from')),
        effective_to=_optional_datetime(value.get('effective_to')),
        authority=value['authority'],
        visibility=value['visibility'],
        publication_status=KnowledgePublicationStatus(value['publication_status']),
        expected_checksum=value.get('expected_checksum'),
    )


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
    result = KnowledgeIngestionService(store).ingest(load_source(arguments.request))
    print(
        f'{result.status}: document={result.document_id} version={result.version} '
        f'chunks={result.chunk_count} checksum={result.source_checksum}'
    )


if __name__ == '__main__':
    main()
