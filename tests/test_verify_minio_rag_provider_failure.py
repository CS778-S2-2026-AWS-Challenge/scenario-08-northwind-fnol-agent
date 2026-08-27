from collections.abc import Callable

import pytest

from backend.domain.knowledge import KnowledgeRetrievalUnavailable
from scripts.verify_minio_rag_provider_failure import (
    EXPECTED_ERROR,
    require_local_minio_endpoint,
    verify_provider_failure,
)


@pytest.mark.parametrize(
    'endpoint',
    ['http://localhost:9000', 'http://127.0.0.1:9000', 'http://[::1]:9000'],
)
def test_provider_failure_check_accepts_only_local_minio_endpoint(endpoint: str) -> None:
    require_local_minio_endpoint(endpoint)


@pytest.mark.parametrize(
    'endpoint',
    ['https://localhost:9000', 'http://localhost:9001', 'http://minio:9000'],
)
def test_provider_failure_check_rejects_nonlocal_or_unexpected_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match='local MinIO'):
        require_local_minio_endpoint(endpoint)


def test_provider_failure_check_asserts_safe_error_and_restarts() -> None:
    actions: list[str] = []

    def unavailable_search() -> None:
        actions.append('search')
        raise KnowledgeRetrievalUnavailable(EXPECTED_ERROR)

    verify_provider_failure(
        lambda: actions.append('stop'),
        lambda: actions.append('start'),
        unavailable_search,
    )

    assert actions == ['stop', 'search', 'start']


@pytest.mark.parametrize(
    'search',
    [lambda: [], lambda: (_ for _ in ()).throw(KnowledgeRetrievalUnavailable('provider detail'))],
)
def test_provider_failure_check_restarts_when_assertion_fails(
    search: Callable[[], object],
) -> None:
    actions: list[str] = []

    with pytest.raises(AssertionError):
        verify_provider_failure(
            lambda: actions.append('stop'),
            lambda: actions.append('start'),
            search,
        )

    assert actions == ['stop', 'start']
