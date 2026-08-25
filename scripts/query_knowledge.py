import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.knowledge_object_store import S3CompatibleKnowledgeObjectStore
from backend.adapters.knowledge_retrieval import S3CompatibleKnowledgeRetriever
from backend.domain.knowledge import KnowledgeSearch

DOCUMENTS = {
    ('motor', 'MVP-2026.1'): 'nw-policy-motor-standard-mvp-2026-1',
    ('home', 'MVP-2026.1'): 'nw-policy-home-standard-mvp-2026-1',
    ('contents', 'MVP-2026.1'): 'nw-policy-contents-standard-mvp-2026-1',
}


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f'Missing required setting: {name}')
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description='Query the local Northwind knowledge corpus.')
    parser.add_argument('product', choices=('motor', 'home', 'contents'))
    parser.add_argument('question')
    parser.add_argument('--limit', type=int, default=3)
    arguments = parser.parse_args()
    client = boto3.client(
        's3',
        endpoint_url=required_environment('NORTHWIND_OBJECT_STORAGE_ENDPOINT'),
        aws_access_key_id=required_environment('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'),
        aws_secret_access_key=required_environment('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'),
        region_name=os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1'),
    )
    store = S3CompatibleKnowledgeObjectStore(
        client, os.getenv('NORTHWIND_KNOWLEDGE_BUCKET', 'northwind-knowledge')
    )
    results = S3CompatibleKnowledgeRetriever(store, DOCUMENTS).search(
        KnowledgeSearch(
            text=arguments.question,
            jurisdiction='NZ',
            visibility='customer_and_staff',
            authority='northwind_synthetic_demo',
            version='MVP-2026.1',
            insurer='Northwind Insurance',
            product=arguments.product,
            effective_at=datetime.now(UTC),
            limit=arguments.limit,
        )
    )
    if not results:
        print('No applicable knowledge found; the question requires a limitation or staff review.')
        return
    for result in results:
        print(f'{result.chunk_id} | {result.section_path} | {result.source_uri}')


if __name__ == '__main__':
    main()
