import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.knowledge_object_store import S3CompatibleKnowledgeObjectStore
from backend.domain.knowledge import KnowledgeSource
from backend.services.knowledge_ingestion import KnowledgeIngestionService
from backend.services.knowledge_manifest import load_approved_sources


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
