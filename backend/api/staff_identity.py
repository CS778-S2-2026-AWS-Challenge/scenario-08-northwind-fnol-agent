from typing import cast

from fastapi import APIRouter, Depends, Header, Request, Response, status

from backend.core.auth import Principal, require_staff
from backend.core.errors import ApiError
from backend.domain.staff_identity import (
    AuthenticatedStaffSession,
    CurrentStaffSession,
    StaffLoginRequest,
    StaffPresenceUpdate,
    StaffProfileProjection,
)
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.staff_identity import (
    hash_staff_access_token,
    login_staff,
    staff_profile_projection,
    staff_session_projection,
)
from backend.services.staff_presence import mark_staff_online, update_presence

router = APIRouter(prefix='/api/v1/staff', tags=['staff identity'])


def repository_for(request: Request) -> StaffIdentityRepository:
    return cast(StaffIdentityRepository, request.app.state.staff_identity_repository)


@router.post(
    '/auth/sessions',
    response_model=AuthenticatedStaffSession,
    status_code=status.HTTP_201_CREATED,
)
def create_staff_auth_session(
    request: Request,
    payload: StaffLoginRequest,
) -> AuthenticatedStaffSession:
    identity_repository = repository_for(request)
    result = login_staff(
        identity_repository,
        payload,
        request.app.state.settings.staff_session_ttl_minutes,
        development_identity=request.app.state.settings.developer_mode,
    )
    try:
        mark_staff_online(
            cast(PersistenceRepository, request.app.state.claim_repository), result.staff_id
        )
    except Exception as error:
        identity_repository.revoke_session(hash_staff_access_token(result.access_token))
        raise ApiError(
            status_code=503,
            code='STAFF_PRESENCE_UNAVAILABLE',
            message='Staff presence could not be established; the session was not created.',
            retryable=True,
        ) from error
    return result


@router.get('/auth/session', response_model=CurrentStaffSession)
def read_staff_auth_session(
    principal: Principal = Depends(require_staff),
) -> CurrentStaffSession:
    return staff_session_projection(principal)


@router.delete('/auth/session', status_code=status.HTTP_204_NO_CONTENT)
def delete_staff_auth_session(
    request: Request,
    authorization: str | None = Header(default=None),
    principal: Principal = Depends(require_staff),
) -> Response:
    token = (authorization or '').removeprefix('Bearer ').strip()
    update_presence(
        cast(PersistenceRepository, request.app.state.claim_repository),
        principal,
        StaffPresenceUpdate(online=False, available=False, lease_seconds=15),
    )
    if not repository_for(request).revoke_session(hash_staff_access_token(token)):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The staff session is no longer active.',
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/me', response_model=StaffProfileProjection)
def read_staff_profile(
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffProfileProjection:
    return staff_profile_projection(repository_for(request), principal)
