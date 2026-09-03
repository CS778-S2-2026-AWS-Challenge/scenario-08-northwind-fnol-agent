from typing import cast

from fastapi import APIRouter, Depends, Header, Request, Response, status

from backend.core.auth import Principal, require_staff
from backend.core.errors import ApiError
from backend.domain.staff_identity import (
    AuthenticatedStaffSession,
    CurrentStaffSession,
    StaffLoginRequest,
    StaffProfileProjection,
)
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.staff_identity import (
    hash_staff_access_token,
    login_staff,
    staff_profile_projection,
    staff_session_projection,
)

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
    return login_staff(
        repository_for(request),
        payload,
        request.app.state.settings.staff_session_ttl_minutes,
        development_identity=request.app.state.settings.developer_mode,
    )


@router.get('/auth/session', response_model=CurrentStaffSession)
def read_staff_auth_session(
    principal: Principal = Depends(require_staff),
) -> CurrentStaffSession:
    return staff_session_projection(principal)


@router.delete('/auth/session', status_code=status.HTTP_204_NO_CONTENT)
def delete_staff_auth_session(
    request: Request,
    authorization: str | None = Header(default=None),
    _: Principal = Depends(require_staff),
) -> Response:
    token = (authorization or '').removeprefix('Bearer ').strip()
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
