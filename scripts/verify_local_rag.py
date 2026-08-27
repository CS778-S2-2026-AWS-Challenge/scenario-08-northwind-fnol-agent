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

ALLOWED_STRUCTURED_DATA = {
    'policy_schedule.endorsements.hidden_water_damage',
    'policy_schedule.excesses',
}


def retrieval_limit(case: dict[str, Any]) -> int:
    value = case.get('retrieval_limit')
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise ValueError(f'{case["case_id"]} retrieval_limit must be an integer from 1 to 5')
    return value


def evaluate_case(case: dict[str, Any], actual_citations: set[str]) -> list[str]:
    case_id = case['case_id']
    expected_citations = set(case['expected_citations'])
    failures: list[str] = []

    allowed_values = case.get('allowed_citations', [])
    if not isinstance(allowed_values, list) or any(
        not isinstance(citation, str) or not citation for citation in allowed_values
    ):
        return [f'{case_id} allowed_citations must be a list of non-empty strings']
    allowed_citations = set(allowed_values)
    overlap = expected_citations & allowed_citations
    if overlap:
        failures.append(f'{case_id} duplicates required citations as allowed {sorted(overlap)}')

    missing = expected_citations - actual_citations
    unexpected = actual_citations - expected_citations - allowed_citations
    if missing:
        failures.append(f'{case_id} missing {sorted(missing)}')
    if unexpected:
        failures.append(f'{case_id} returned unexpected evidence {sorted(unexpected)}')

    required_structured_data = case.get('required_structured_data', [])
    if not isinstance(required_structured_data, list) or not required_structured_data:
        if 'required_structured_data' in case:
            failures.append(f'{case_id} required_structured_data must be a non-empty list')
        return failures

    invalid_fields = [
        field
        for field in required_structured_data
        if not isinstance(field, str) or field not in ALLOWED_STRUCTURED_DATA
    ]
    if invalid_fields:
        failures.append(f'{case_id} has unsupported structured data {invalid_fields}')

    return failures


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
                limit=retrieval_limit(case),
            )
        )
        actual = {result.chunk_id for result in results}
        case_failures = evaluate_case(case, actual)
        status = 'FAIL' if case_failures else 'PASS'
        print(f'{status} {case["case_id"]}: {", ".join(result.chunk_id for result in results)}')
        required_structured_data = case.get('required_structured_data')
        if required_structured_data:
            print(
                f'BOUNDARY {case["case_id"]}: exact answer requires '
                f'{", ".join(required_structured_data)}'
            )
        failures.extend(case_failures)
    if failures:
        raise SystemExit('; '.join(failures))
    print(f'PASS local RAG evaluation: {len(evaluation["cases"])} cases')


if __name__ == '__main__':
    main()
