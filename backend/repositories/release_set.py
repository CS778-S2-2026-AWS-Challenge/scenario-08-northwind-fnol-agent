from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass

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
        candidates = [
            item
            for records in self._records.values()
            for item in records
            if item.environment == environment
            and item.runtime_profile == runtime_profile
            and item.state is ReleaseSetState.PUBLISHED
        ]
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
