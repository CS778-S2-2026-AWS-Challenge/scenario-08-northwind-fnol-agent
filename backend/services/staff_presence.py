"""Short-lived Workbench staff presence and eligibility."""

from datetime import UTC, datetime, timedelta

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.staff_identity import (
    StaffPresencePage,
    StaffPresenceRecord,
    StaffPresenceUpdate,
)
from backend.repositories.protocols import PersistenceRepository, RevisionConflict
from backend.services.support import paginate


def _now() -> datetime:
    return datetime.now(UTC)


def update_presence(
    repository: PersistenceRepository,
    principal: Principal,
    payload: StaffPresenceUpdate,
) -> StaffPresenceRecord:
    now = _now()
    current = repository.get_staff_presence(principal.subject)
    record = StaffPresenceRecord(
        staff_id=principal.subject,
        online=payload.online,
        available=payload.available if payload.online else False,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=payload.lease_seconds),
        revision=(current.revision + 1) if current is not None else 1,
        updated_at=now,
    )
    try:
        repository.save_staff_presence(record, current.revision if current is not None else None)
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The staff presence changed before it could be updated.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    return record


def mark_staff_online(repository: PersistenceRepository, staff_id: str) -> StaffPresenceRecord:
    """Start a bounded lease when a staff session is authenticated."""
    now = _now()
    current = repository.get_staff_presence(staff_id)
    record = StaffPresenceRecord(
        staff_id=staff_id,
        online=True,
        available=True,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=5),
        revision=(current.revision + 1) if current is not None else 1,
        updated_at=now,
    )
    repository.save_staff_presence(record, current.revision if current is not None else None)
    return record


def read_presence(repository: PersistenceRepository, principal: Principal) -> StaffPresenceRecord:
    record = repository.get_staff_presence(principal.subject)
    if record is None:
        now = _now()
        return StaffPresenceRecord(
            staff_id=principal.subject,
            online=False,
            available=False,
            last_seen_at=now,
            expires_at=now,
            revision=1,
            updated_at=now,
        )
    return record


def list_online_staff(
    repository: PersistenceRepository,
    principal: Principal,
    limit: int = 50,
    cursor: str | None = None,
) -> StaffPresencePage:
    if principal.actor_type != 'staff':
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Staff Workbench access is required.',
        )
    now = _now()
    records = [record for record in repository.list_staff_presence() if record.is_claimable(now)]
    items, page = paginate(records, limit, cursor)
    return StaffPresencePage(items=items, page=page)


def require_claimable_staff(repository: PersistenceRepository, principal: Principal) -> None:
    record = repository.get_staff_presence(principal.subject)
    if record is None or not record.is_claimable(_now()):
        raise ApiError(
            status_code=409,
            code='STAFF_NOT_AVAILABLE',
            message='Staff must be online and available to accept a Claim.',
        )
