from typing import cast

from fastapi import APIRouter, Depends, Query, Request

from backend.core.auth import Principal, require_staff
from backend.domain.staff_identity import (
    StaffPresencePage,
    StaffPresenceRecord,
    StaffPresenceUpdate,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.staff_presence import list_online_staff, read_presence, update_presence

router = APIRouter(prefix='/api/v1/workbench/staff', tags=['workbench staff'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


@router.patch('/presence', response_model=StaffPresenceRecord)
def put_presence(
    payload: StaffPresenceUpdate,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffPresenceRecord:
    return update_presence(repository_for(request), principal, payload)


@router.get('/presence', response_model=StaffPresenceRecord)
def get_presence(
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffPresenceRecord:
    return read_presence(repository_for(request), principal)


@router.get('/online', response_model=StaffPresencePage)
def get_online_staff(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(require_staff),
) -> StaffPresencePage:
    return list_online_staff(repository_for(request), principal, limit, cursor)
