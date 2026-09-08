import json
import os
import sqlite3
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass

from backend.domain.ids import new_id
from backend.domain.operations import OperationRecord


@dataclass(frozen=True, slots=True)
class OperationIdempotencyRecord:
    actor: str
    route: str
    key: str
    fingerprint: str
    response: dict[str, object]
    status_code: int


class OperationRepository:
    """Provider-neutral operation status repository for Control Plane work."""

    def __init__(self) -> None:
        self._records: dict[str, OperationRecord] = {}
        self._idempotency: dict[tuple[str, str, str], OperationIdempotencyRecord] = {}

    def create(self, record: OperationRecord) -> OperationRecord:
        if record.operation_id in self._records:
            raise ValueError('operation_exists')
        self._records[record.operation_id] = deepcopy(record)
        return deepcopy(record)

    def get(self, operation_id: str) -> OperationRecord | None:
        record = self._records.get(operation_id)
        return deepcopy(record) if record is not None else None

    def save(self, record: OperationRecord, expected_revision: int) -> OperationRecord:
        current = self._records.get(record.operation_id)
        if current is None or current.revision != expected_revision:
            raise ValueError('stale_revision')
        self._records[record.operation_id] = deepcopy(record)
        return deepcopy(record)

    def list(
        self,
        *,
        kind: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[OperationRecord]:
        records = list(self._records.values())
        if kind is not None:
            records = [item for item in records if item.kind.value == kind]
        if state is not None:
            records = [item for item in records if item.state.value == state]
        records.sort(key=lambda item: (item.created_at, item.operation_id), reverse=True)
        return deepcopy(records[: min(max(limit, 1), 100)])

    def new_operation_id(self) -> str:
        return new_id('opr')

    def metrics_records(self) -> Sequence[OperationRecord]:
        """Return a detached snapshot of the complete operation ledger.

        Returns:
            Operation records available for aggregate metrics.
        """

        return deepcopy(list(self._records.values()))

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> OperationIdempotencyRecord | None:
        return deepcopy(self._idempotency.get((actor, route, key)))

    def save_idempotency(self, record: OperationIdempotencyRecord) -> None:
        lookup = (record.actor, record.route, record.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.fingerprint != record.fingerprint:
            raise ValueError('idempotency_conflict')
        self._idempotency[lookup] = deepcopy(record)


class SQLiteOperationRepository(OperationRepository):
    """Durable operation repository for the normal local/runtime path."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS control_plane_operations '
                '(operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS control_plane_operation_idempotency '
                '(actor TEXT NOT NULL, route TEXT NOT NULL, idempotency_key TEXT NOT NULL, '
                'payload TEXT NOT NULL, PRIMARY KEY (actor, route, idempotency_key))'
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord.model_validate_json(row['payload'])

    def create(self, record: OperationRecord) -> OperationRecord:
        try:
            with self._connection() as connection:
                connection.execute(
                    'INSERT INTO control_plane_operations VALUES (?, ?)',
                    (record.operation_id, record.model_dump_json()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError('operation_exists') from exc
        return deepcopy(record)

    def get(self, operation_id: str) -> OperationRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_operations WHERE operation_id = ?',
                (operation_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def save(self, record: OperationRecord, expected_revision: int) -> OperationRecord:
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE control_plane_operations SET payload = ? '
                "WHERE operation_id = ? AND json_extract(payload, '$.revision') = ?",
                (record.model_dump_json(), record.operation_id, expected_revision),
            ).rowcount
        if updated != 1:
            raise ValueError('stale_revision')
        return deepcopy(record)

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> OperationIdempotencyRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_operation_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (actor, route, key),
            ).fetchone()
        return OperationIdempotencyRecord(**json.loads(row['payload'])) if row is not None else None

    def save_idempotency(self, record: OperationIdempotencyRecord) -> None:
        with self._connection() as connection:
            existing = connection.execute(
                'SELECT payload FROM control_plane_operation_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (record.actor, record.route, record.key),
            ).fetchone()
            if existing is not None:
                prior = json.loads(existing['payload'])
                if prior['fingerprint'] != record.fingerprint:
                    raise ValueError('idempotency_conflict')
                return
            connection.execute(
                'INSERT INTO control_plane_operation_idempotency '
                '(actor, route, idempotency_key, payload) VALUES (?, ?, ?, ?)',
                (record.actor, record.route, record.key, json.dumps(asdict(record))),
            )

    def list(
        self,
        *,
        kind: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[OperationRecord]:
        query = 'SELECT payload FROM control_plane_operations'
        conditions: list[str] = []
        parameters: list[object] = []
        if kind is not None:
            conditions.append("json_extract(payload, '$.kind') = ?")
            parameters.append(kind)
        if state is not None:
            conditions.append("json_extract(payload, '$.state') = ?")
            parameters.append(state)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += " ORDER BY json_extract(payload, '$.created_at') DESC, operation_id DESC LIMIT ?"
        parameters.append(min(max(limit, 1), 100))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._record(row) for row in rows]

    def metrics_records(self) -> Sequence[OperationRecord]:
        """Return a detached snapshot of the complete operation ledger.

        Returns:
            Operation records available for aggregate metrics.
        """

        with self._connection() as connection:
            rows = connection.execute(
                'SELECT payload FROM control_plane_operations '
                "ORDER BY json_extract(payload, '$.created_at'), operation_id"
            ).fetchall()
        return [self._record(row) for row in rows]
