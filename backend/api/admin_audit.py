from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Query, Request

from backend.core.auth import Principal, require_administrator
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import paginate

router = APIRouter(prefix='/internal/v1/admin/audit', tags=['administration'])


def persistence_repo(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.data_runtime_bundle.repository)


@router.get('', response_model=dict)
def list_audit_events(
    request: Request,
    event_type: str | None = Query(default=None, min_length=1, max_length=100),
    subject_type: str | None = Query(default=None, min_length=1, max_length=50),
    actor_id: str | None = Query(default=None, min_length=1, max_length=200),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    events = persistence_repo(request).list_audit_events_admin(
        event_type=event_type,
        subject_type=subject_type,
        actor_id=actor_id,
        start_at=start_at,
        end_at=end_at,
    )
    items, page = paginate(events, limit, cursor)
    return {
        'items': [event.model_dump(mode='json') for event in items],
        'page': page.model_dump(mode='json'),
    }


__all__ = ['router']
