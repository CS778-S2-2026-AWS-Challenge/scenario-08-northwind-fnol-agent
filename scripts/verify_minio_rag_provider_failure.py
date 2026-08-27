import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.knowledge_object_store import (
    S3CompatibleKnowledgeConfig,
    S3CompatibleKnowledgeObjectStore,
)
from backend.adapters.knowledge_retrieval import S3CompatibleKnowledgeRetriever
from backend.domain.knowledge import KnowledgeRetrievalUnavailable, KnowledgeSearch
from scripts.ingest_knowledge_source import load_approved_sources

EXPECTED_ERROR = 'The knowledge service is unavailable.'
LOCAL_ENDPOINT_HOSTS = {'127.0.0.1', '::1', 'localhost'}


def require_local_minio_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != 'http'
        or parsed.hostname not in LOCAL_ENDPOINT_HOSTS
        or parsed.port != 9000
    ):
        raise ValueError(
            'Provider-failure verification requires local MinIO at http://localhost:9000.'
        )


def verify_provider_failure(
    stop_minio: Callable[[], None],
    start_minio: Callable[[], None],
    search: Callable[[], object],
) -> None:
    try:
        stop_minio()
        try:
            search()
        except KnowledgeRetrievalUnavailable as error:
            if str(error) != EXPECTED_ERROR:
                raise AssertionError(f'Unexpected safe error: {error}') from error
        else:
            raise AssertionError('Stopped MinIO returned evidence instead of failing closed.')
    finally:
        start_minio()


def compose(*arguments: str) -> None:
    subprocess.run(
        ['docker', 'compose', *arguments],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )


def main() -> None:
    config = S3CompatibleKnowledgeConfig.from_environment()
    require_local_minio_endpoint(config.endpoint_url)
    retriever = S3CompatibleKnowledgeRetriever(
        S3CompatibleKnowledgeObjectStore.from_config(config),
        load_approved_sources().values(),
    )
    request = KnowledgeSearch(
        text='What policy wording applies to collision damage to my insured car?',
        jurisdiction='NZ',
        visibility='customer_and_staff',
        authority='northwind_synthetic_demo',
        version='MVP-2026.1',
        insurer='Northwind Insurance',
        product='motor',
        effective_at=datetime(2026, 8, 27, tzinfo=UTC),
        limit=3,
    )

    verify_provider_failure(
        lambda: compose('stop', 'minio'),
        lambda: compose('up', '-d', '--wait', 'minio'),
        lambda: retriever.search(request),
    )
    print(f'PASS stopped local MinIO returned no evidence and raised: {EXPECTED_ERROR}')


if __name__ == '__main__':
    main()
