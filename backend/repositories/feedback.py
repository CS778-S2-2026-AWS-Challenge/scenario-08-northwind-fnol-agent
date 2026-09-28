import json
import os
import sqlite3
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from backend.domain.feedback import FeedbackRecord
from backend.domain.ids import new_id


class FeedbackIdempotencyConflict(ValueError):
    """An idempotency key was reused for a different feedback message."""


@dataclass(frozen=True, slots=True)
class FeedbackIdempotencyRecord:
    actor: str
    key: str
    fingerprint: str
    feedback_id: str
    expires_at: str


def _is_expired(record: FeedbackIdempotencyRecord) -> bool:
    return datetime.fromisoformat(record.expires_at) <= datetime.now(UTC)


def _idempotency_record(
    record: FeedbackRecord,
    *,
    actor: str,
    key: str,
    fingerprint: str,
) -> FeedbackIdempotencyRecord:
    return FeedbackIdempotencyRecord(
        actor=actor,
        key=key,
        fingerprint=fingerprint,
        feedback_id=record.feedback_id,
        expires_at=(record.created_at + timedelta(hours=24)).isoformat(),
    )


class FeedbackRepository:
    """Append-only staff feedback repository used by the fixture profile."""

    def __init__(self) -> None:
        self._records: dict[str, FeedbackRecord] = {}
        self._idempotency: dict[tuple[str, str], FeedbackIdempotencyRecord] = {}
        self._lock = RLock()

    def new_feedback_id(self) -> str:
        return new_id('fdb')

    def submit(
        self,
        record: FeedbackRecord,
        *,
        actor: str,
        key: str,
        fingerprint: str,
    ) -> FeedbackRecord:
        with self._lock:
            existing = self._idempotency.get((actor, key))
            if existing is not None:
                if _is_expired(existing):
                    del self._idempotency[(actor, key)]
                else:
                    if existing.fingerprint != fingerprint:
                        raise FeedbackIdempotencyConflict('idempotency_conflict')
                    return deepcopy(self._records[existing.feedback_id])
            if record.feedback_id in self._records:
                raise ValueError('feedback_exists')
            self._records[record.feedback_id] = deepcopy(record)
            self._idempotency[(actor, key)] = _idempotency_record(
                record,
                actor=actor,
                key=key,
                fingerprint=fingerprint,
            )
            return deepcopy(record)

    def get(self, feedback_id: str) -> FeedbackRecord | None:
        record = self._records.get(feedback_id)
        return deepcopy(record) if record is not None else None

    def list(
        self,
        *,
        staff_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FeedbackRecord]:
        records = list(self._records.values())
        if staff_id is not None:
            records = [item for item in records if item.submitted_by_staff_id == staff_id]
        records.sort(key=lambda item: (item.created_at, item.feedback_id), reverse=True)
        bounded_limit = min(max(limit, 1), 101)
        bounded_offset = max(offset, 0)
        return deepcopy(records[bounded_offset : bounded_offset + bounded_limit])


class SQLiteFeedbackRepository(FeedbackRepository):
    """Durable append-only feedback repository for the normal runtime path."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS control_plane_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_plane_feedback_idempotency (
                    actor TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (actor, idempotency_key)
                );
                """
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> FeedbackRecord:
        return FeedbackRecord.model_validate_json(row['payload'])

    def submit(
        self,
        record: FeedbackRecord,
        *,
        actor: str,
        key: str,
        fingerprint: str,
    ) -> FeedbackRecord:
        try:
            with self._connection() as connection:
                connection.execute('BEGIN IMMEDIATE')
                existing = connection.execute(
                    'SELECT payload FROM control_plane_feedback_idempotency '
                    'WHERE actor = ? AND idempotency_key = ?',
                    (actor, key),
                ).fetchone()
                if existing is not None:
                    replay = self._replay(connection, existing, fingerprint)
                    if replay is not None:
                        return replay
                connection.execute(
                    'INSERT INTO control_plane_feedback VALUES (?, ?)',
                    (record.feedback_id, record.model_dump_json()),
                )
                idempotency = _idempotency_record(
                    record,
                    actor=actor,
                    key=key,
                    fingerprint=fingerprint,
                )
                connection.execute(
                    'INSERT INTO control_plane_feedback_idempotency '
                    '(actor, idempotency_key, payload) VALUES (?, ?, ?)',
                    (actor, key, json.dumps(asdict(idempotency))),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError('feedback_exists') from error
        return deepcopy(record)

    def _replay(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        fingerprint: str,
    ) -> FeedbackRecord | None:
        idempotency = FeedbackIdempotencyRecord(**json.loads(row['payload']))
        if _is_expired(idempotency):
            connection.execute(
                'DELETE FROM control_plane_feedback_idempotency '
                'WHERE actor = ? AND idempotency_key = ?',
                (idempotency.actor, idempotency.key),
            )
            return None
        if idempotency.fingerprint != fingerprint:
            raise FeedbackIdempotencyConflict('idempotency_conflict')
        prior = connection.execute(
            'SELECT payload FROM control_plane_feedback WHERE feedback_id = ?',
            (idempotency.feedback_id,),
        ).fetchone()
        if prior is None:
            raise RuntimeError('Feedback idempotency record has no matching feedback.')
        return self._record(prior)

    def get(self, feedback_id: str) -> FeedbackRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM control_plane_feedback WHERE feedback_id = ?',
                (feedback_id,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def list(
        self,
        *,
        staff_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FeedbackRecord]:
        query = 'SELECT payload FROM control_plane_feedback'
        parameters: list[object] = []
        if staff_id is not None:
            query += " WHERE json_extract(payload, '$.submitted_by_staff_id') = ?"
            parameters.append(staff_id)
        query += (
            " ORDER BY json_extract(payload, '$.created_at') DESC, feedback_id DESC "
            'LIMIT ? OFFSET ?'
        )
        parameters.extend((min(max(limit, 1), 101), max(offset, 0)))
        with self._connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._record(row) for row in rows]
