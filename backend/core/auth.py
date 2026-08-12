from dataclasses import dataclass

from fastapi import Header, Request

from backend.core.errors import ApiError


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    actor_type: str = 'claimant'


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
    if (
        settings.environment not in {'development', 'test'}
        or token != settings.synthetic_claimant_token
    ):
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
    if (
        settings.environment not in {'development', 'test'}
        or token != settings.synthetic_staff_token
    ):
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The staff identity could not be authenticated.',
        )

    return Principal(subject='stf_demo', actor_type='staff')
