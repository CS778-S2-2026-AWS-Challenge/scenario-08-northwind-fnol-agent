import os
import sqlite3
from copy import deepcopy

from backend.domain.ids import new_id
from backend.domain.knowledge_admin import KnowledgeSourceRecord, KnowledgeVersionState


class KnowledgeAdminRepository:
    """Versioned knowledge metadata and lifecycle repository."""

    def __init__(self) -> None:
        self._records: dict[str, KnowledgeSourceRecord] = {}

    def new_knowledge_id(self) -> str:
        return new_id('knw')

    def create(self, record: KnowledgeSourceRecord) -> KnowledgeSourceRecord:
        if record.knowledge_id in self._records:
            raise ValueError('knowledge_exists')
        if any(
            item.document_id == record.document_id and item.version == record.version
            for item in self._records.values()
        ):
            raise ValueError('knowledge_version_exists')
        self._records[record.knowledge_id] = deepcopy(record)
        return deepcopy(record)

    def get(self, knowledge_id: str) -> KnowledgeSourceRecord | None:
        record = self._records.get(knowledge_id)
        return deepcopy(record) if record is not None else None

    def save(self, record: KnowledgeSourceRecord, expected_revision: int) -> KnowledgeSourceRecord:
        current = self._records.get(record.knowledge_id)
        if current is None or current.revision != expected_revision:
            raise ValueError('stale_revision')
        self._records[record.knowledge_id] = deepcopy(record)
        return deepcopy(record)

    def list(
        self,
        *,
        state: KnowledgeVersionState | None = None,
        document_id: str | None = None,
        limit: int = 25,
    ) -> list[KnowledgeSourceRecord]:
        records = list(self._records.values())
        if state is not None:
            records = [item for item in records if item.state is state]
        if document_id is not None:
            records = [item for item in records if item.document_id == document_id]
        records.sort(key=lambda item: (item.updated_at, item.knowledge_id), reverse=True)
        return deepcopy(records[: min(max(limit, 1), 100)])

    def active(self, document_id: str) -> KnowledgeSourceRecord | None:
        records = [
            item
            for item in self._records.values()
            if item.document_id == document_id and item.state is KnowledgeVersionState.PUBLISHED
        ]
        return deepcopy(max(records, key=lambda item: item.updated_at)) if records else None

    def published_for_product(self, product: str) -> KnowledgeSourceRecord | None:
        records = [
            item
            for item in self._records.values()
            if item.state is KnowledgeVersionState.PUBLISHED and item.product == product
        ]
        return deepcopy(max(records, key=lambda item: item.updated_at)) if records else None


class SQLiteKnowledgeAdminRepository(KnowledgeAdminRepository):
    """Durable knowledge metadata repository in the Control Plane database."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS control_plane_knowledge_sources '
                '(knowledge_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version TEXT NOT NULL, '
                'payload TEXT NOT NULL, UNIQUE(document_id, version))'
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> KnowledgeSourceRecord:
        return KnowledgeSourceRecord.model_validate_json(row['payload'])

    def create(self, record: KnowledgeSourceRecord) -> KnowledgeSourceRecord:
        try:
            with self._connection() as connection:
                connection.execute(
                    'INSERT INTO control_plane_knowledge_sources '
                    '(knowledge_id, document_id, version, payload) VALUES (?, ?, ?, ?)',
                    (
                        record.knowledge_id,
                        record.document_id,
                        record.version,
                        record.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError('knowledge_version_exists') from exc
        return deepcopy(record)

    def get(self, knowledge_id: str) -> KnowledgeSourceRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_knowledge_sources WHERE knowledge_id = ?',
                (knowledge_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def save(self, record: KnowledgeSourceRecord, expected_revision: int) -> KnowledgeSourceRecord:
        with self._connection() as connection:
            current = connection.execute(
                'SELECT payload FROM control_plane_knowledge_sources WHERE knowledge_id = ?',
                (record.knowledge_id,),
            ).fetchone()
            if current is None:
                raise ValueError('stale_revision')
            stored = self._record(current)
            if stored.revision != expected_revision:
                raise ValueError('stale_revision')
            connection.execute(
                'UPDATE control_plane_knowledge_sources SET payload = ? WHERE knowledge_id = ?',
                (record.model_dump_json(), record.knowledge_id),
            )
        return deepcopy(record)

    def list(
        self,
        *,
        state: KnowledgeVersionState | None = None,
        document_id: str | None = None,
        limit: int = 25,
    ) -> list[KnowledgeSourceRecord]:
        query = 'SELECT payload FROM control_plane_knowledge_sources'
        conditions: list[str] = []
        parameters: list[object] = []
        if state is not None:
            conditions.append("json_extract(payload, '$.state') = ?")
            parameters.append(state.value)
        if document_id is not None:
            conditions.append('document_id = ?')
            parameters.append(document_id)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += " ORDER BY json_extract(payload, '$.updated_at') DESC, knowledge_id DESC LIMIT ?"
        parameters.append(min(max(limit, 1), 100))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._record(row) for row in rows]

    def active(self, document_id: str) -> KnowledgeSourceRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_knowledge_sources '
                "WHERE document_id = ? AND json_extract(payload, '$.state') = 'published' "
                "ORDER BY json_extract(payload, '$.updated_at') DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def published_for_product(self, product: str) -> KnowledgeSourceRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_knowledge_sources '
                "WHERE json_extract(payload, '$.product') = ? "
                "AND json_extract(payload, '$.state') = 'published' "
                "ORDER BY json_extract(payload, '$.updated_at') DESC LIMIT 1",
                (product,),
            ).fetchone()
        return self._record(row) if row is not None else None
