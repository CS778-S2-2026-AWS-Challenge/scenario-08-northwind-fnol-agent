from typing import Any

import mongomock
import pytest

from backend.repositories.mongodb import MongoDBConnectionConfig, MongoDBRepository
from scripts.verify_mongodb_persistence import verify_mongodb_persistence


def test_verifier_uses_isolated_collection_and_cleans_up() -> None:
    client: Any = mongomock.MongoClient()
    created_collections: list[str] = []
    cleaned_collections: list[str] = []

    def repository_factory(config: MongoDBConnectionConfig) -> MongoDBRepository:
        created_collections.append(config.collection_name)
        repository = MongoDBRepository(
            client,
            config.database_name,
            collection_name=config.collection_name,
        )
        repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        return repository

    def cleanup(config: MongoDBConnectionConfig) -> None:
        cleaned_collections.append(config.collection_name)
        client[config.database_name].drop_collection(config.collection_name)

    result = verify_mongodb_persistence(
        MongoDBConnectionConfig(
            uri='mongodb://example.invalid',
            database_name='northwind_test',
            collection_name='must_not_be_used',
        ),
        repository_factory=repository_factory,
        cleanup=cleanup,
    )

    assert result.status == 'verified'
    assert result.claims == 1
    assert result.sessions == 1
    assert result.messages == 1
    assert result.evidence == 1
    assert result.staff_actions == 1
    assert result.reconnect_verified is True
    assert result.ownership_verified is True
    assert len(created_collections) == 2
    assert created_collections[0] == created_collections[1]
    assert created_collections[0].startswith('northwind_verify_')
    assert created_collections[0] != 'must_not_be_used'
    assert cleaned_collections == [created_collections[0]]
    assert client['northwind_test'].list_collection_names() == []


def test_verifier_preserves_initial_connection_failure_without_cleanup() -> None:
    cleanup_called = False

    def failing_factory(config: MongoDBConnectionConfig) -> MongoDBRepository:
        raise RuntimeError(f'connection failed for {config.database_name}')

    def cleanup(config: MongoDBConnectionConfig) -> None:
        nonlocal cleanup_called
        cleanup_called = True

    with pytest.raises(RuntimeError, match='connection failed for northwind_test'):
        verify_mongodb_persistence(
            MongoDBConnectionConfig(
                uri='mongodb://example.invalid',
                database_name='northwind_test',
            ),
            repository_factory=failing_factory,
            cleanup=cleanup,
        )

    assert cleanup_called is False
