from copy import deepcopy

from backend.domain.configuration import (
    AuditEvent,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.ids import new_id


class ConfigurationRepository:
    """Provider-neutral configuration repository used by the fixture profile."""

    def __init__(self) -> None:
        self._records: dict[str, list[ConfigurationRecord]] = {}
        self._audits: list[AuditEvent] = []

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

    def add_audit(self, event: AuditEvent) -> None:
        self._audits.append(deepcopy(event))

    def audits(self, configuration_id: str) -> list[AuditEvent]:
        return deepcopy(
            [item for item in self._audits if item.configuration_id == configuration_id]
        )

    def new_configuration_id(self) -> str:
        return new_id('cfg')

    def new_event_id(self) -> str:
        return new_id('aud')

    def active(self, domain: str) -> ConfigurationRecord | None:
        candidates = [
            item
            for items in self._records.values()
            for item in items
            if item.domain == domain and item.state is ConfigurationState.PUBLISHED
        ]
        return deepcopy(max(candidates, key=lambda item: item.updated_at)) if candidates else None
