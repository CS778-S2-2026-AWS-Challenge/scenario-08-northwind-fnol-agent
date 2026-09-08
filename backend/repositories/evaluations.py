import os
import sqlite3
from copy import deepcopy

from backend.domain.evaluation import EvaluationRecord
from backend.domain.ids import new_id


class EvaluationRepository:
    """Immutable evaluation evidence repository for the Control Plane."""

    def __init__(self) -> None:
        self._records: dict[str, EvaluationRecord] = {}

    def new_evaluation_id(self) -> str:
        return new_id('eval')

    def create(self, record: EvaluationRecord) -> EvaluationRecord:
        if record.evaluation_id in self._records:
            raise ValueError('evaluation_exists')
        self._records[record.evaluation_id] = deepcopy(record)
        return deepcopy(record)

    def get(self, evaluation_id: str) -> EvaluationRecord | None:
        record = self._records.get(evaluation_id)
        return deepcopy(record) if record is not None else None

    def list(
        self,
        *,
        purpose: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[EvaluationRecord]:
        records = list(self._records.values())
        if purpose is not None:
            records = [item for item in records if item.purpose == purpose]
        if state is not None:
            records = [item for item in records if item.state.value == state]
        records.sort(key=lambda item: (item.created_at, item.evaluation_id), reverse=True)
        return deepcopy(records[: min(max(limit, 1), 100)])


class SQLiteEvaluationRepository(EvaluationRepository):
    """Durable immutable evaluation evidence repository."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS control_plane_evaluations '
                '(evaluation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)'
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> EvaluationRecord:
        return EvaluationRecord.model_validate_json(row['payload'])

    def create(self, record: EvaluationRecord) -> EvaluationRecord:
        try:
            with self._connection() as connection:
                connection.execute(
                    'INSERT INTO control_plane_evaluations VALUES (?, ?)',
                    (record.evaluation_id, record.model_dump_json()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError('evaluation_exists') from exc
        return deepcopy(record)

    def get(self, evaluation_id: str) -> EvaluationRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_evaluations WHERE evaluation_id = ?',
                (evaluation_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def list(
        self,
        *,
        purpose: str | None = None,
        state: str | None = None,
        limit: int = 25,
    ) -> list[EvaluationRecord]:
        query = 'SELECT payload FROM control_plane_evaluations'
        conditions: list[str] = []
        parameters: list[object] = []
        if purpose is not None:
            conditions.append("json_extract(payload, '$.purpose') = ?")
            parameters.append(purpose)
        if state is not None:
            conditions.append("json_extract(payload, '$.state') = ?")
            parameters.append(state)
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += " ORDER BY json_extract(payload, '$.created_at') DESC, evaluation_id DESC LIMIT ?"
        parameters.append(min(max(limit, 1), 100))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._record(row) for row in rows]
