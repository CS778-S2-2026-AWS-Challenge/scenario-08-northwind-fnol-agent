from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.staff_identity import (
    AuthenticatedStaffSession,
    CurrentStaffSession,
    StaffAuthSessionRecord,
    StaffLoginRequest,
    StaffProfileProjection,
)
from backend.repositories.staff_identity import StaffIdentityRepository


def hash_staff_access_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def login_staff(
    repository: StaffIdentityRepository,
    payload: StaffLoginRequest,
    ttl_minutes: int,
    *,
    development_identity: bool = False,
) -> AuthenticatedStaffSession:
    account = repository.authenticate(payload.email, payload.password)
    if account is None:
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='The email or password was not recognised.',
        )
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=ttl_minutes)
    token = token_urlsafe(32)
    repository.save_session(
        StaffAuthSessionRecord(
            token_hash=hash_staff_access_token(token),
            staff_id=account.staff_id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    return AuthenticatedStaffSession(
        staff_id=account.staff_id,
        access_token=token,
        expires_at=expires_at,
        development_identity=development_identity,
    )


def staff_session_projection(principal: Principal) -> CurrentStaffSession:
    return CurrentStaffSession(
        staff_id=principal.subject,
        expires_at=principal.expires_at,
        development_identity=principal.synthetic,
    )


def staff_profile_projection(
    repository: StaffIdentityRepository,
    principal: Principal,
) -> StaffProfileProjection:
    account = repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The staff account was not found.',
        )
    return StaffProfileProjection(
        staff_id=account.staff_id,
        display_name=account.display_name,
        email=account.email,
        roles=list(account.roles),
        development_identity=principal.synthetic,
    )
