import json
import os
import sqlite3
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass

from backend.domain.ids import new_id
from backend.domain.release import ReleaseSetAuditEvent, ReleaseSetRecord, ReleaseSetState


@dataclass(frozen=True, slots=True)
class ReleaseSetIdempotencyRecord:
    actor: str
    route: str
    key: str
    fingerprint: str
    response: dict[str, object]
    status_code: int


class ReleaseSetRepository:
    """Provider-neutral Release Set repository used by the current fixture profile."""

    def __init__(self) -> None:
        self._records: dict[str, list[ReleaseSetRecord]] = {}
        self._audits: list[ReleaseSetAuditEvent] = []
        self._idempotency: dict[tuple[str, str, str], ReleaseSetIdempotencyRecord] = {}

    def create(self, record: ReleaseSetRecord) -> ReleaseSetRecord:
        self._records.setdefault(record.release_set_id, []).append(deepcopy(record))
        return deepcopy(record)

    def get(self, release_set_id: str, revision: int | None = None) -> ReleaseSetRecord | None:
        records = self._records.get(release_set_id, [])
        if revision is None:
            return deepcopy(records[-1]) if records else None
        return deepcopy(next((item for item in records if item.revision == revision), None))

    def list_release_sets(
        self, environment: str | None = None, runtime_profile: str | None = None
    ) -> list[ReleaseSetRecord]:
        records = [items[-1] for items in self._records.values() if items]
        if environment is not None:
            records = [item for item in records if item.environment == environment]
        if runtime_profile is not None:
            records = [item for item in records if item.runtime_profile == runtime_profile]
        return deepcopy(sorted(records, key=lambda item: (item.updated_at, item.release_set_id)))

    def save(self, record: ReleaseSetRecord, expected_revision: int) -> ReleaseSetRecord:
        current = self.get(record.release_set_id)
        if current is None or current.revision != expected_revision:
            raise ValueError('stale_revision')
        self._records[record.release_set_id].append(deepcopy(record))
        return deepcopy(record)

    def active(self, environment: str, runtime_profile: str) -> ReleaseSetRecord | None:
        candidates: list[ReleaseSetRecord] = []
        for records in self._records.values():
            if not records:
                continue
            item = records[-1]
            if (
                item.environment == environment
                and item.runtime_profile == runtime_profile
                and item.state is ReleaseSetState.PUBLISHED
            ):
                candidates.append(item)
        return deepcopy(max(candidates, key=lambda item: item.updated_at)) if candidates else None

    def replace_active(
        self,
        previous: ReleaseSetRecord,
        superseded: ReleaseSetRecord,
        published: ReleaseSetRecord,
        expected_revision: int,
        audit_events: Sequence[ReleaseSetAuditEvent],
    ) -> ReleaseSetRecord:
        records_snapshot = deepcopy(self._records)
        audits_snapshot = deepcopy(self._audits)
        try:
            self.save(superseded, previous.revision)
            saved = self.save(published, expected_revision)
            for event in audit_events:
                self.add_audit(event)
            return saved
        except Exception:
            self._records = records_snapshot
            self._audits = audits_snapshot
            raise

    def replace_active_with_new(
        self,
        previous: ReleaseSetRecord,
        superseded: ReleaseSetRecord,
        published: ReleaseSetRecord,
        audit_events: Sequence[ReleaseSetAuditEvent],
    ) -> ReleaseSetRecord:
        records_snapshot = deepcopy(self._records)
        audits_snapshot = deepcopy(self._audits)
        try:
            self.save(superseded, previous.revision)
            saved = self.create(published)
            for event in audit_events:
                self.add_audit(event)
            return saved
        except Exception:
            self._records = records_snapshot
            self._audits = audits_snapshot
            raise

    def add_audit(self, event: ReleaseSetAuditEvent) -> None:
        self._audits.append(deepcopy(event))

    def audits(self, release_set_id: str) -> list[ReleaseSetAuditEvent]:
        return deepcopy([item for item in self._audits if item.release_set_id == release_set_id])

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> ReleaseSetIdempotencyRecord | None:
        return deepcopy(self._idempotency.get((actor, route, key)))

    def save_idempotency(self, record: ReleaseSetIdempotencyRecord) -> None:
        lookup = (record.actor, record.route, record.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.fingerprint != record.fingerprint:
            raise ValueError('idempotency_conflict')
        self._idempotency[lookup] = deepcopy(record)

    def new_release_set_id(self) -> str:
        return new_id('rel')

    def new_event_id(self) -> str:
        return new_id('aud')


class SQLiteReleaseSetRepository(ReleaseSetRepository):
    """Durable Release Set repository for the normal local/runtime path."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS release_set_records (
                    release_set_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (release_set_id, revision)
                );
                CREATE TABLE IF NOT EXISTS release_set_audits (
                    event_id TEXT PRIMARY KEY,
                    release_set_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS release_set_idempotency (
                    actor TEXT NOT NULL,
                    route TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (actor, route, idempotency_key)
                );
                """
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> ReleaseSetRecord:
        return ReleaseSetRecord.model_validate_json(row['payload'])

    @staticmethod
    def _audit_event(row: sqlite3.Row) -> ReleaseSetAuditEvent:
        return ReleaseSetAuditEvent.model_validate_json(row['payload'])

    def create(self, record: ReleaseSetRecord) -> ReleaseSetRecord:
        with self._connection() as connection:
            connection.execute(
                'INSERT INTO release_set_records VALUES (?, ?, ?)',
                (record.release_set_id, record.revision, record.model_dump_json()),
            )
        return deepcopy(record)

    def get(self, release_set_id: str, revision: int | None = None) -> ReleaseSetRecord | None:
        query = 'SELECT payload FROM release_set_records WHERE release_set_id = ? ' + (
            'AND revision = ?' if revision is not None else 'ORDER BY revision DESC LIMIT 1'
        )
        parameters: tuple[object, ...] = (
            (release_set_id, revision) if revision is not None else (release_set_id,)
        )
        with self._connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._record(row) if row is not None else None

    def list_release_sets(
        self, environment: str | None = None, runtime_profile: str | None = None
    ) -> list[ReleaseSetRecord]:
        query = (
            'SELECT r.payload FROM release_set_records r '
            'JOIN (SELECT release_set_id, MAX(revision) revision '
            'FROM release_set_records GROUP BY release_set_id) latest '
            'ON latest.release_set_id = r.release_set_id AND latest.revision = r.revision'
        )
        clauses: list[str] = []
        parameters: list[object] = []
        if environment is not None:
            clauses.append("json_extract(r.payload, '$.environment') = ?")
            parameters.append(environment)
        if runtime_profile is not None:
            clauses.append("json_extract(r.payload, '$.runtime_profile') = ?")
            parameters.append(runtime_profile)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        records = [self._record(row) for row in rows]
        return sorted(records, key=lambda item: (item.updated_at, item.release_set_id))

    def save(self, record: ReleaseSetRecord, expected_revision: int) -> ReleaseSetRecord:
        with self._connection() as connection:
            self._save_connection(connection, record, expected_revision)
        return deepcopy(record)

    @staticmethod
    def _save_connection(
        connection: sqlite3.Connection, record: ReleaseSetRecord, expected_revision: int
    ) -> None:
        current = connection.execute(
            'SELECT revision FROM release_set_records '
            'WHERE release_set_id = ? ORDER BY revision DESC LIMIT 1',
            (record.release_set_id,),
        ).fetchone()
        if current is None or current['revision'] != expected_revision:
            raise ValueError('stale_revision')
        connection.execute(
            'INSERT INTO release_set_records VALUES (?, ?, ?)',
            (record.release_set_id, record.revision, record.model_dump_json()),
        )

    def replace_active(
        self,
        previous: ReleaseSetRecord,
        superseded: ReleaseSetRecord,
        published: ReleaseSetRecord,
        expected_revision: int,
        audit_events: Sequence[ReleaseSetAuditEvent],
    ) -> ReleaseSetRecord:
        with self._connection() as connection:
            try:
                connection.execute('BEGIN')
                self._save_connection(connection, superseded, previous.revision)
                self._save_connection(connection, published, expected_revision)
                for event in audit_events:
                    self._add_audit_connection(connection, event)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return deepcopy(published)

    def replace_active_with_new(
        self,
        previous: ReleaseSetRecord,
        superseded: ReleaseSetRecord,
        published: ReleaseSetRecord,
        audit_events: Sequence[ReleaseSetAuditEvent],
    ) -> ReleaseSetRecord:
        with self._connection() as connection:
            try:
                connection.execute('BEGIN')
                self._save_connection(connection, superseded, previous.revision)
                connection.execute(
                    'INSERT INTO release_set_records VALUES (?, ?, ?)',
                    (published.release_set_id, published.revision, published.model_dump_json()),
                )
                for event in audit_events:
                    self._add_audit_connection(connection, event)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return deepcopy(published)

    def add_audit(self, event: ReleaseSetAuditEvent) -> None:
        with self._connection() as connection:
            self._add_audit_connection(connection, event)

    @staticmethod
    def _add_audit_connection(connection: sqlite3.Connection, event: ReleaseSetAuditEvent) -> None:
        connection.execute(
            'INSERT INTO release_set_audits VALUES (?, ?, ?)',
            (event.event_id, event.release_set_id, event.model_dump_json()),
        )

    def audits(self, release_set_id: str) -> list[ReleaseSetAuditEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT payload FROM release_set_audits WHERE release_set_id = ?',
                (release_set_id,),
            ).fetchall()
        return [self._audit_event(row) for row in rows]

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> ReleaseSetIdempotencyRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM release_set_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (actor, route, key),
            ).fetchone()
        if row is None:
            return None
        return ReleaseSetIdempotencyRecord(**json.loads(row['payload']))

    def save_idempotency(self, record: ReleaseSetIdempotencyRecord) -> None:
        with self._connection() as connection:
            existing = connection.execute(
                'SELECT payload FROM release_set_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (record.actor, record.route, record.key),
            ).fetchone()
            if existing is not None:
                prior = json.loads(existing['payload'])
                if prior['fingerprint'] != record.fingerprint:
                    raise ValueError('idempotency_conflict')
                return
            connection.execute(
                'INSERT INTO release_set_idempotency VALUES (?, ?, ?, ?)',
                (record.actor, record.route, record.key, json.dumps(asdict(record))),
            )

    def active(self, environment: str, runtime_profile: str) -> ReleaseSetRecord | None:
        candidates = self.list_release_sets(environment, runtime_profile)
        published = [item for item in candidates if item.state is ReleaseSetState.PUBLISHED]
        return deepcopy(max(published, key=lambda item: item.updated_at)) if published else None
