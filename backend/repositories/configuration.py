import json
import os
import sqlite3
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass

from backend.domain.configuration import (
    AuditEvent,
    ConfigurationApprovalRecord,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.ids import new_id


@dataclass(frozen=True, slots=True)
class ConfigurationIdempotencyRecord:
    actor: str
    route: str
    key: str
    fingerprint: str
    response: dict[str, object]
    status_code: int


class ConfigurationRepository:
    """Provider-neutral configuration repository used by the fixture profile."""

    def __init__(self) -> None:
        self._records: dict[str, list[ConfigurationRecord]] = {}
        self._audits: list[AuditEvent] = []
        self._approvals: list[ConfigurationApprovalRecord] = []
        self._idempotency: dict[tuple[str, str, str], ConfigurationIdempotencyRecord] = {}

    def create(self, record: ConfigurationRecord) -> ConfigurationRecord:
        self._records.setdefault(record.configuration_id, []).append(deepcopy(record))
        return deepcopy(record)

    def get(self, configuration_id: str, revision: int | None = None) -> ConfigurationRecord | None:
        records = self._records.get(configuration_id, [])
        if revision is None:
            return deepcopy(records[-1]) if records else None
        return deepcopy(next((item for item in records if item.revision == revision), None))

    def list_configurations(self, domain: str | None = None) -> list[ConfigurationRecord]:
        records = [items[-1] for items in self._records.values() if items]
        if domain:
            records = [item for item in records if item.domain == domain]
        return deepcopy(records)

    def save(self, record: ConfigurationRecord, expected_revision: int) -> ConfigurationRecord:
        current = self.get(record.configuration_id)
        if current is None or current.revision != expected_revision:
            raise ValueError('stale_revision')
        self._records[record.configuration_id].append(deepcopy(record))
        return deepcopy(record)

    def replace_active(
        self,
        previous: ConfigurationRecord,
        superseded: ConfigurationRecord,
        published: ConfigurationRecord,
        expected_revision: int,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord:
        """Atomically replace the active publication and append its audit events.

        Args:
            previous: The currently published record to supersede.
            superseded: The next immutable revision for ``previous``.
            published: The new published record.
            expected_revision: Expected current revision for ``published``.
            audit_events: Events committed with the state transition.

        Returns:
            The committed published record.

        Raises:
            Exception: Propagates a failed write after restoring all state.
        """
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
        previous: ConfigurationRecord,
        superseded: ConfigurationRecord,
        published: ConfigurationRecord,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord:
        """Atomically supersede an active record and create a new publication.

        Args:
            previous: The currently published record to supersede.
            superseded: The next immutable revision for ``previous``.
            published: The new publication with a new configuration identity.
            audit_events: Events committed with the state transition.

        Returns:
            The committed new publication.

        Raises:
            Exception: Propagates a failed write after restoring all state.
        """
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

    def add_audit(self, event: AuditEvent) -> None:
        self._audits.append(deepcopy(event))

    def add_approval(self, approval: ConfigurationApprovalRecord) -> None:
        existing = next(
            (
                item
                for item in self._approvals
                if item.configuration_id == approval.configuration_id
                and item.configuration_revision == approval.configuration_revision
            ),
            None,
        )
        if existing is not None:
            raise ValueError('approval_exists')
        self._approvals.append(deepcopy(approval))

    def save_approval_transition(
        self,
        approval: ConfigurationApprovalRecord,
        updated: ConfigurationRecord | None,
        expected_revision: int | None,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord | None:
        records_snapshot = deepcopy(self._records)
        audits_snapshot = deepcopy(self._audits)
        approvals_snapshot = deepcopy(self._approvals)
        try:
            self.add_approval(approval)
            saved = (
                self.save(updated, expected_revision)
                if updated is not None and expected_revision is not None
                else None
            )
            for event in audit_events:
                self.add_audit(event)
            return saved
        except Exception:
            self._records = records_snapshot
            self._audits = audits_snapshot
            self._approvals = approvals_snapshot
            raise

    def approvals(
        self, configuration_id: str, revision: int | None = None
    ) -> list[ConfigurationApprovalRecord]:
        return deepcopy(
            [
                item
                for item in self._approvals
                if item.configuration_id == configuration_id
                and (revision is None or item.configuration_revision == revision)
            ]
        )

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> ConfigurationIdempotencyRecord | None:
        return deepcopy(self._idempotency.get((actor, route, key)))

    def save_idempotency(self, record: ConfigurationIdempotencyRecord) -> None:
        lookup = (record.actor, record.route, record.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.fingerprint != record.fingerprint:
            raise ValueError('idempotency_conflict')
        self._idempotency[lookup] = deepcopy(record)

    def audits(self, configuration_id: str) -> list[AuditEvent]:
        return deepcopy(
            [item for item in self._audits if item.configuration_id == configuration_id]
        )

    def new_configuration_id(self) -> str:
        return new_id('cfg')

    def new_event_id(self) -> str:
        return new_id('aud')

    def new_approval_id(self) -> str:
        return new_id('apr')

    def active(
        self,
        domain: str,
        configuration_key: str = 'default',
    ) -> ConfigurationRecord | None:
        candidates: list[ConfigurationRecord] = []
        for items in self._records.values():
            if not items:
                continue
            item = items[-1]
            if (
                item.domain == domain
                and item.configuration_key == configuration_key
                and item.state is ConfigurationState.PUBLISHED
            ):
                candidates.append(item)
        return deepcopy(max(candidates, key=lambda item: item.updated_at)) if candidates else None


class SQLiteConfigurationRepository(ConfigurationRepository):
    """Durable configuration repository for the normal local/runtime path."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS configuration_records (
                    configuration_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (configuration_id, revision)
                );
                CREATE TABLE IF NOT EXISTS configuration_audits (
                    event_id TEXT PRIMARY KEY,
                    configuration_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS configuration_approvals (
                    approval_id TEXT PRIMARY KEY,
                    configuration_id TEXT NOT NULL,
                    configuration_revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (configuration_id, configuration_revision)
                );
                CREATE TABLE IF NOT EXISTS configuration_idempotency (
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
    def _record(row: sqlite3.Row) -> ConfigurationRecord:
        return ConfigurationRecord.model_validate_json(row['payload'])

    @staticmethod
    def _audit_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent.model_validate_json(row['payload'])

    @staticmethod
    def _approval(row: sqlite3.Row) -> ConfigurationApprovalRecord:
        return ConfigurationApprovalRecord.model_validate_json(row['payload'])

    def create(self, record: ConfigurationRecord) -> ConfigurationRecord:
        with self._connection() as connection:
            connection.execute(
                'INSERT INTO configuration_records VALUES (?, ?, ?)',
                (record.configuration_id, record.revision, record.model_dump_json()),
            )
        return deepcopy(record)

    def get(self, configuration_id: str, revision: int | None = None) -> ConfigurationRecord | None:
        query = 'SELECT payload FROM configuration_records WHERE configuration_id = ? ' + (
            'AND revision = ?' if revision is not None else 'ORDER BY revision DESC LIMIT 1'
        )
        parameters: tuple[object, ...] = (
            (configuration_id, revision) if revision is not None else (configuration_id,)
        )
        with self._connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._record(row) if row is not None else None

    def list_configurations(self, domain: str | None = None) -> list[ConfigurationRecord]:
        query = (
            'SELECT r.payload FROM configuration_records r '
            'JOIN (SELECT configuration_id, MAX(revision) revision '
            'FROM configuration_records GROUP BY configuration_id) latest '
            'ON latest.configuration_id = r.configuration_id AND latest.revision = r.revision'
        )
        parameters: tuple[object, ...] = ()
        if domain:
            query += " WHERE json_extract(r.payload, '$.domain') = ?"
            parameters = (domain,)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._record(row) for row in rows]

    def save(self, record: ConfigurationRecord, expected_revision: int) -> ConfigurationRecord:
        with self._connection() as connection:
            current = connection.execute(
                'SELECT revision FROM configuration_records '
                'WHERE configuration_id = ? ORDER BY revision DESC LIMIT 1',
                (record.configuration_id,),
            ).fetchone()
            if current is None or current['revision'] != expected_revision:
                raise ValueError('stale_revision')
            connection.execute(
                'INSERT INTO configuration_records VALUES (?, ?, ?)',
                (record.configuration_id, record.revision, record.model_dump_json()),
            )
        return deepcopy(record)

    def replace_active(
        self,
        previous: ConfigurationRecord,
        superseded: ConfigurationRecord,
        published: ConfigurationRecord,
        expected_revision: int,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord:
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
        previous: ConfigurationRecord,
        superseded: ConfigurationRecord,
        published: ConfigurationRecord,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord:
        with self._connection() as connection:
            try:
                connection.execute('BEGIN')
                self._save_connection(connection, superseded, previous.revision)
                connection.execute(
                    'INSERT INTO configuration_records VALUES (?, ?, ?)',
                    (published.configuration_id, published.revision, published.model_dump_json()),
                )
                for event in audit_events:
                    self._add_audit_connection(connection, event)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return deepcopy(published)

    @staticmethod
    def _save_connection(
        connection: sqlite3.Connection, record: ConfigurationRecord, expected_revision: int
    ) -> None:
        current = connection.execute(
            'SELECT revision FROM configuration_records '
            'WHERE configuration_id = ? ORDER BY revision DESC LIMIT 1',
            (record.configuration_id,),
        ).fetchone()
        if current is None or current['revision'] != expected_revision:
            raise ValueError('stale_revision')
        connection.execute(
            'INSERT INTO configuration_records VALUES (?, ?, ?)',
            (record.configuration_id, record.revision, record.model_dump_json()),
        )

    def add_audit(self, event: AuditEvent) -> None:
        with self._connection() as connection:
            self._add_audit_connection(connection, event)

    def add_approval(self, approval: ConfigurationApprovalRecord) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    'INSERT INTO configuration_approvals '
                    '(approval_id, configuration_id, configuration_revision, payload) '
                    'VALUES (?, ?, ?, ?)',
                    (
                        approval.approval_id,
                        approval.configuration_id,
                        approval.configuration_revision,
                        approval.model_dump_json(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError('approval_exists') from exc

    def save_approval_transition(
        self,
        approval: ConfigurationApprovalRecord,
        updated: ConfigurationRecord | None,
        expected_revision: int | None,
        audit_events: Sequence[AuditEvent],
    ) -> ConfigurationRecord | None:
        with self._connection() as connection:
            try:
                connection.execute('BEGIN')
                connection.execute(
                    'INSERT INTO configuration_approvals '
                    '(approval_id, configuration_id, configuration_revision, payload) '
                    'VALUES (?, ?, ?, ?)',
                    (
                        approval.approval_id,
                        approval.configuration_id,
                        approval.configuration_revision,
                        approval.model_dump_json(),
                    ),
                )
                if updated is not None and expected_revision is not None:
                    self._save_connection(connection, updated, expected_revision)
                for event in audit_events:
                    self._add_audit_connection(connection, event)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError('approval_exists') from exc
            except Exception:
                connection.rollback()
                raise
        return deepcopy(updated)

    def approvals(
        self, configuration_id: str, revision: int | None = None
    ) -> list[ConfigurationApprovalRecord]:
        query = (
            'SELECT payload FROM configuration_approvals WHERE configuration_id = ? '
            'ORDER BY configuration_revision, approval_id'
        )
        parameters: tuple[object, ...] = (configuration_id,)
        if revision is not None:
            query = (
                'SELECT payload FROM configuration_approvals '
                'WHERE configuration_id = ? AND configuration_revision = ? '
                'ORDER BY approval_id'
            )
            parameters = (configuration_id, revision)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._approval(row) for row in rows]

    @staticmethod
    def _add_audit_connection(connection: sqlite3.Connection, event: AuditEvent) -> None:
        connection.execute(
            'INSERT INTO configuration_audits VALUES (?, ?, ?)',
            (event.event_id, event.configuration_id, event.model_dump_json()),
        )

    def find_idempotency(
        self, actor: str, route: str, key: str
    ) -> ConfigurationIdempotencyRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT payload FROM configuration_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (actor, route, key),
            ).fetchone()
        if row is None:
            return None
        return ConfigurationIdempotencyRecord(**json.loads(row['payload']))

    def save_idempotency(self, record: ConfigurationIdempotencyRecord) -> None:
        with self._connection() as connection:
            existing = connection.execute(
                'SELECT payload FROM configuration_idempotency '
                'WHERE actor = ? AND route = ? AND idempotency_key = ?',
                (record.actor, record.route, record.key),
            ).fetchone()
            if existing is not None:
                prior = json.loads(existing['payload'])
                if prior['fingerprint'] != record.fingerprint:
                    raise ValueError('idempotency_conflict')
                return
            connection.execute(
                'INSERT INTO configuration_idempotency VALUES (?, ?, ?, ?)',
                (record.actor, record.route, record.key, json.dumps(asdict(record))),
            )

    def audits(self, configuration_id: str) -> list[AuditEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT payload FROM configuration_audits WHERE configuration_id = ?',
                (configuration_id,),
            ).fetchall()
        return [self._audit_event(row) for row in rows]

    def active(
        self,
        domain: str,
        configuration_key: str = 'default',
    ) -> ConfigurationRecord | None:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT r.payload FROM configuration_records r '
                'JOIN (SELECT configuration_id, MAX(revision) revision '
                'FROM configuration_records GROUP BY configuration_id) latest '
                'ON latest.configuration_id = r.configuration_id AND latest.revision = r.revision '
                "WHERE json_extract(r.payload, '$.domain') = ? "
                'AND COALESCE('
                "json_extract(r.payload, '$.configuration_key'), "
                "CASE WHEN json_extract(r.payload, '$.domain') = 'integration' "
                "THEN json_extract(r.payload, '$.values.service_id') ELSE 'default' END, "
                "'default') = ? "
                "AND json_extract(r.payload, '$.state') = 'published'",
                (domain, configuration_key),
            ).fetchall()
        records = [self._record(row) for row in rows]
        return deepcopy(max(records, key=lambda item: item.updated_at)) if records else None
