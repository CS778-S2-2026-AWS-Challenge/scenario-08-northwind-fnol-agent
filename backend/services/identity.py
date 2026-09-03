from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.identity import (
    AccountProfile,
    AccountProjection,
    AuthenticatedSession,
    ClaimantAuthSessionRecord,
    CommunicationPreferences,
    CurrentAuthSession,
    LoginRequest,
    PreferencesPatchRequest,
    ProfilePatchRequest,
    RegistrationRequest,
)
from backend.repositories.identity import IdentityRepository


def hash_access_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def login(
    repository: IdentityRepository,
    payload: LoginRequest,
    ttl_minutes: int,
    *,
    development_identity: bool = False,
) -> AuthenticatedSession:
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
        ClaimantAuthSessionRecord(
            token_hash=hash_access_token(token),
            customer_id=account.customer_id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    return AuthenticatedSession(
        customer_id=account.customer_id,
        access_token=token,
        expires_at=expires_at,
        development_identity=development_identity,
    )


def register(
    repository: IdentityRepository,
    payload: RegistrationRequest,
    ttl_minutes: int,
    *,
    development_identity: bool = False,
) -> AuthenticatedSession:
    account = repository.create_account(
        payload.email,
        payload.password,
        payload.display_name,
    )
    if account is None:
        raise ApiError(
            status_code=409,
            code='RESOURCE_CONFLICT',
            message='An account with that email already exists.',
        )
    return login(
        repository,
        LoginRequest(email=account.email, password=payload.password),
        ttl_minutes,
        development_identity=development_identity,
    )


def session_projection(repository: IdentityRepository, principal: Principal) -> CurrentAuthSession:
    return CurrentAuthSession(
        customer_id=principal.subject,
        expires_at=principal.expires_at,
        development_identity=principal.synthetic,
    )


def account_projection(repository: IdentityRepository, principal: Principal) -> AccountProjection:
    account = repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claimant account was not found.',
        )
    return AccountProjection(
        customer_id=account.customer_id,
        profile=AccountProfile(
            display_name=account.display_name,
            email=account.email,
            phone=account.phone,
        ),
        preferences=CommunicationPreferences(**account.communication_preferences),
        development_identity=principal.synthetic,
    )


def update_profile(
    repository: IdentityRepository, principal: Principal, payload: ProfilePatchRequest
) -> AccountProjection:
    account = repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claimant account was not found.',
        )
    account.display_name = payload.display_name.strip()
    account.phone = payload.phone.strip()
    repository.save_account(account)
    return account_projection(repository, principal)


def update_preferences(
    repository: IdentityRepository, principal: Principal, payload: PreferencesPatchRequest
) -> AccountProjection:
    account = repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claimant account was not found.',
        )
    account.communication_preferences = {'email': payload.email, 'sms': payload.sms}
    repository.save_account(account)
    return account_projection(repository, principal)
