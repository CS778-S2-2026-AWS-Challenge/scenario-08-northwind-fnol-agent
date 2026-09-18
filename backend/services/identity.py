from dataclasses import replace
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
from backend.repositories.protocols import RevisionConflict
from backend.services.support import parse_if_match


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
            legal_name=account.legal_name or account.display_name,
            preferred_name=account.preferred_name,
            date_of_birth=account.date_of_birth,
            email=account.email,
            phone=account.phone,
            residential_address=account.residential_address,
        ),
        preferences=CommunicationPreferences(**account.communication_preferences),
        revision=account.revision,
        updated_at=account.updated_at,
        development_identity=principal.synthetic,
    )


def update_profile(
    repository: IdentityRepository,
    principal: Principal,
    payload: ProfilePatchRequest,
    if_match: str | None,
) -> AccountProjection:
    account = repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claimant account was not found.',
        )
    # Legacy profile clients predate optimistic headers; projections now expose revision so
    # upgraded clients can use If-Match without breaking the existing personal interface.
    expected_revision = parse_if_match(if_match) if if_match is not None else account.revision
    if account.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The account changed after this page was loaded.',
            retryable=True,
            current_revision=account.revision,
        )
    changes = payload.model_dump(exclude_unset=True, exclude={'display_name'})
    legacy_name = payload.display_name.strip() if payload.display_name is not None else None
    legal_name = str(changes.pop('legal_name', legacy_name or account.legal_name)).strip()
    preferred_name = changes.get('preferred_name', account.preferred_name)
    if isinstance(preferred_name, str):
        preferred_name = preferred_name.strip()
    phone = changes.get('phone', account.phone)
    if isinstance(phone, str):
        phone = phone.strip()
    address = changes.get('residential_address', account.residential_address)
    if isinstance(address, str):
        address = address.strip()
    updated = replace(
        account,
        legal_name=legal_name,
        preferred_name=preferred_name,
        date_of_birth=changes.get('date_of_birth', account.date_of_birth),
        display_name=preferred_name or legal_name,
        phone=phone,
        residential_address=address,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    try:
        repository.save_account(updated, expected_revision)
    except RevisionConflict as error:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The account changed after this page was loaded.',
            retryable=True,
            current_revision=error.current_revision,
        ) from error
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
    updated = replace(
        account,
        communication_preferences={'email': payload.email, 'sms': payload.sms},
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, account.revision)
    return account_projection(repository, principal)
