from typing import cast

from fastapi import APIRouter, Depends, Header, Request, Response, status

from backend.core.auth import Principal, require_claimant_session
from backend.core.errors import ApiError
from backend.domain.identity import (
    AccountProjection,
    AuthenticatedSession,
    CurrentAuthSession,
    LoginRequest,
    PreferencesPatchRequest,
    ProfilePatchRequest,
)
from backend.repositories.identity import IdentityRepository
from backend.services.identity import (
    account_projection,
    hash_access_token,
    login,
    session_projection,
    update_preferences,
    update_profile,
)

router = APIRouter(prefix='/api/v1', tags=['claimant identity'])


def identity_repository_for(request: Request) -> IdentityRepository:
    return cast(IdentityRepository, request.app.state.identity_repository)


@router.post(
    '/auth/sessions', response_model=AuthenticatedSession, status_code=status.HTTP_201_CREATED
)
def create_auth_session(request: Request, payload: LoginRequest) -> AuthenticatedSession:
    if not request.app.state.settings.developer_mode:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='The development claimant identity provider is not enabled.',
        )
    return login(
        identity_repository_for(request),
        payload,
        request.app.state.settings.claimant_session_ttl_minutes,
    )


@router.get('/auth/session', response_model=CurrentAuthSession)
def read_auth_session(
    request: Request, principal: Principal = Depends(require_claimant_session)
) -> CurrentAuthSession:
    return session_projection(identity_repository_for(request), principal)


@router.delete('/auth/session', status_code=status.HTTP_204_NO_CONTENT)
def delete_auth_session(
    request: Request,
    authorization: str | None = Header(default=None),
    principal: Principal = Depends(require_claimant_session),
) -> Response:
    del principal
    token = (authorization or '').removeprefix('Bearer ').strip()
    if not identity_repository_for(request).revoke_session(hash_access_token(token)):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The claimant session is not active.',
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/account', response_model=AccountProjection)
def read_account(
    request: Request, principal: Principal = Depends(require_claimant_session)
) -> AccountProjection:
    return account_projection(identity_repository_for(request), principal)


@router.patch('/account/profile', response_model=AccountProjection)
def patch_account_profile(
    request: Request,
    payload: ProfilePatchRequest,
    principal: Principal = Depends(require_claimant_session),
) -> AccountProjection:
    return update_profile(identity_repository_for(request), principal, payload)


@router.patch('/account/preferences', response_model=AccountProjection)
def patch_account_preferences(
    request: Request,
    payload: PreferencesPatchRequest,
    principal: Principal = Depends(require_claimant_session),
) -> AccountProjection:
    return update_preferences(identity_repository_for(request), principal, payload)
