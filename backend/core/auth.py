from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from fastapi import Header, Request

from backend.core.errors import ApiError


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    actor_type: str = 'claimant'
    expires_at: datetime | None = None


def require_claimant(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.startswith('Bearer '):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='A claimant bearer token is required.',
        )

    token = authorization.removeprefix('Bearer ').strip()
    settings = request.app.state.settings
    if settings.environment not in {'development', 'test'}:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The claimant identity could not be authenticated.',
        )
    if token in {settings.synthetic_staff_token, settings.synthetic_integration_token}:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Staff and integration credentials cannot access claimant APIs.',
        )
    session = request.app.state.identity_repository.get_session(sha256(token.encode()).hexdigest())
    if session is not None:
        return Principal(subject=session.customer_id, expires_at=session.expires_at)
    if token != settings.synthetic_claimant_token:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The claimant identity could not be authenticated.',
        )

    return Principal(subject='cus_demo')


def require_staff(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.startswith('Bearer '):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='A staff bearer token is required.',
        )

    token = authorization.removeprefix('Bearer ').strip()
    settings = request.app.state.settings
    if settings.environment not in {'development', 'test'}:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The staff identity could not be authenticated.',
        )
    if token in {settings.synthetic_claimant_token, settings.synthetic_integration_token}:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Claimant and integration credentials cannot access the staff workbench.',
        )
    if token != settings.synthetic_staff_token:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The staff identity could not be authenticated.',
        )

    return Principal(subject='stf_demo', actor_type='staff')


def require_integration_service(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.startswith('Bearer '):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='An integration-service bearer token is required.',
        )

    token = authorization.removeprefix('Bearer ').strip()
    settings = request.app.state.settings
    if settings.environment not in {'development', 'test'}:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The integration-service identity could not be authenticated.',
        )
    if token in {settings.synthetic_claimant_token, settings.synthetic_staff_token}:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Claimant and staff credentials cannot access integration-service APIs.',
        )
    if token != settings.synthetic_integration_token:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The integration-service identity could not be authenticated.',
        )

    return Principal(subject='integration_fixture', actor_type='integration_service')
