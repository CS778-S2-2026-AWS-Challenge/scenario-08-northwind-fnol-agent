import os
import sqlite3
from copy import deepcopy

from backend.domain.ids import new_id
from backend.domain.integration_health import IntegrationHealthCheckRecord


class IntegrationHealthRepository:
    """Provider-neutral health-check history repository for tests and fixtures."""

    def __init__(self) -> None:
        self._records: list[IntegrationHealthCheckRecord] = []

    def create(self, record: IntegrationHealthCheckRecord) -> IntegrationHealthCheckRecord:
        self._records.append(deepcopy(record))
        return deepcopy(record)

    def list(self, integration_id: str, limit: int = 25) -> list[IntegrationHealthCheckRecord]:
        records = [item for item in self._records if item.integration_id == integration_id]
        return deepcopy(sorted(records, key=lambda item: item.checked_at, reverse=True)[:limit])

    def new_check_id(self) -> str:
        return new_id('ihc')


class SQLiteIntegrationHealthRepository(IntegrationHealthRepository):
    """Durable health-check history repository for the normal local/runtime path."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS integration_health_checks '
                '(check_id TEXT PRIMARY KEY, integration_id TEXT NOT NULL, payload TEXT NOT NULL)'
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, record: IntegrationHealthCheckRecord) -> IntegrationHealthCheckRecord:
        with self._connection() as connection:
            connection.execute(
                'INSERT INTO integration_health_checks VALUES (?, ?, ?)',
                (record.check_id, record.integration_id, record.model_dump_json()),
            )
        return deepcopy(record)

    def list(self, integration_id: str, limit: int = 25) -> list[IntegrationHealthCheckRecord]:
        bounded_limit = min(max(limit, 1), 100)
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT payload FROM integration_health_checks '
                "WHERE integration_id = ? ORDER BY json_extract(payload, '$.checked_at') DESC "
                'LIMIT ?',
                (integration_id, bounded_limit),
            ).fetchall()
        return [IntegrationHealthCheckRecord.model_validate_json(row['payload']) for row in rows]
