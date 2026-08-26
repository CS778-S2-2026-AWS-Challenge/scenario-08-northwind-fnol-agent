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
from backend.adapters.knowledge_retrieval import S3CompatibleKnowledgeRetriever
from backend.domain.knowledge import KnowledgeSearch
from scripts.ingest_knowledge_source import load_approved_sources
from scripts.query_knowledge import required_environment


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify local RAG citations without an Agent.')
    parser.add_argument('evaluation', type=Path)
    arguments = parser.parse_args()
    evaluation: dict[str, Any] = json.loads(arguments.evaluation.read_text(encoding='utf-8'))
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
    retriever = S3CompatibleKnowledgeRetriever(store, load_approved_sources().values())
    failures: list[str] = []
    for case in evaluation['cases']:
        filters = case['filters']
        results = retriever.search(
            KnowledgeSearch(
                text=case['question'],
                jurisdiction=filters['jurisdiction'],
                visibility=filters['visibility'],
                authority=filters['authority'],
                version=filters['version'],
                insurer=filters['insurer'],
                product=filters['product'],
                effective_at=datetime.fromisoformat(filters['effective_at'].replace('Z', '+00:00')),
                limit=5,
            )
        )
        actual = {result.chunk_id for result in results}
        expected = set(case['expected_citations'])
        missing = expected - actual
        unexpected = actual if not expected else set()
        status = 'PASS' if not missing and not unexpected else 'FAIL'
        print(f'{status} {case["case_id"]}: {", ".join(result.chunk_id for result in results)}')
        if missing:
            failures.append(f'{case["case_id"]} missing {sorted(missing)}')
        if unexpected:
            failures.append(
                f'{case["case_id"]} expected no evidence but returned {sorted(unexpected)}'
            )
    if failures:
        raise SystemExit('; '.join(failures))
    print(f'PASS local RAG evaluation: {len(evaluation["cases"])} cases')


if __name__ == '__main__':
    main()
