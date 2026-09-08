from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from fastapi import Header, Request

from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.configuration import AccessPolicyConfiguration
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    actor_type: str
    # Internal service/unit-test construction may omit verified metadata, but the defaults
    # deliberately carry no scope authority and are never synthetic. Authentication
    # boundaries below always return fully populated server-verified principals.
    scopes: frozenset[str] = frozenset()
    auth_source: str = 'internal:unverified'
    synthetic: bool = False
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _SyntheticProfile:
    token: str
    principal: Principal


CLAIMANT_SCOPES = frozenset({'claim:read:self', 'claim:write:self'})
STAFF_SCOPES = frozenset({'workbench:read', 'workbench:write'})
ADMIN_SCOPES = frozenset({'admin:read', 'admin:write'})
INTEGRATION_SCOPES = frozenset({'tools:invoke'})


def _synthetic_profiles(settings: Settings) -> tuple[_SyntheticProfile, ...]:
    return (
        _SyntheticProfile(
            token=settings.synthetic_claimant_token,
            principal=Principal(
                subject='cus_demo',
                actor_type='claimant',
                scopes=CLAIMANT_SCOPES,
                auth_source='developer:synthetic_claimant',
                synthetic=True,
            ),
        ),
        _SyntheticProfile(
            token=settings.synthetic_staff_token,
            principal=Principal(
                subject='stf_demo',
                actor_type='staff',
                scopes=STAFF_SCOPES,
                auth_source='developer:synthetic_staff',
                synthetic=True,
            ),
        ),
        _SyntheticProfile(
            token=settings.synthetic_admin_token,
            principal=Principal(
                subject='adm_demo',
                actor_type='administrator',
                scopes=ADMIN_SCOPES,
                auth_source='developer:synthetic_admin',
                synthetic=True,
            ),
        ),
        _SyntheticProfile(
            token=settings.synthetic_release_approver_token,
            principal=Principal(
                subject='apr_demo',
                actor_type='administrator',
                scopes=ADMIN_SCOPES,
                auth_source='developer:synthetic_release_approver',
                synthetic=True,
            ),
        ),
        _SyntheticProfile(
            token=settings.synthetic_integration_token,
            principal=Principal(
                subject='integration_fixture',
                actor_type='integration_service',
                scopes=INTEGRATION_SCOPES,
                auth_source='developer:synthetic_integration',
                synthetic=True,
            ),
        ),
    )


def _authentication_required(message: str) -> ApiError:
    return ApiError(
        status_code=401,
        code='AUTHENTICATION_REQUIRED',
        message=message,
    )


def _access_denied(message: str) -> ApiError:
    return ApiError(
        status_code=403,
        code='ACCESS_DENIED',
        message=message,
    )


def _resolve_principal(
    request: Request,
    authorization: str | None,
    *,
    credential_label: str,
) -> Principal:
    required_message = f'A {credential_label} bearer token is required.'
    failure_message = f'The {credential_label} identity could not be authenticated.'

    if not authorization or not authorization.startswith('Bearer '):
        raise _authentication_required(required_message)

    token = authorization.removeprefix('Bearer ').strip()
    if not token:
        raise _authentication_required(required_message)

    settings: Settings = request.app.state.settings
    session = request.app.state.identity_repository.get_session(sha256(token.encode()).hexdigest())
    principal = (
        Principal(
            subject=session.customer_id,
            actor_type='claimant',
            scopes=CLAIMANT_SCOPES,
            auth_source=(
                'developer:claimant_session'
                if settings.identity_mode is IdentityMode.DEVELOPER
                else 'runtime:claimant_session'
            ),
            synthetic=settings.identity_mode is IdentityMode.DEVELOPER,
            expires_at=session.expires_at,
        )
        if session is not None
        else None
    )

    if principal is None:
        staff_session = request.app.state.staff_identity_repository.get_session(
            sha256(token.encode()).hexdigest()
        )
        if staff_session is not None:
            principal = Principal(
                subject=staff_session.staff_id,
                actor_type='staff',
                scopes=STAFF_SCOPES,
                auth_source=(
                    'developer:staff_session'
                    if settings.identity_mode is IdentityMode.DEVELOPER
                    else 'runtime:staff_session'
                ),
                synthetic=settings.identity_mode is IdentityMode.DEVELOPER,
                expires_at=staff_session.expires_at,
            )

    if settings.identity_mode is IdentityMode.DEVELOPER:
        for profile in _synthetic_profiles(settings):
            if principal is None and profile.token == token:
                principal = profile.principal
                break

    if principal is None:
        raise _authentication_required(failure_message)

    return principal


def _verify_principal(
    request: Request,
    authorization: str | None,
    *,
    required_actor: str,
    required_scopes: frozenset[str],
    credential_label: str,
) -> Principal:
    principal = _resolve_principal(
        request,
        authorization,
        credential_label=credential_label,
    )
    actor_mismatch = principal.actor_type != required_actor
    effective_scopes = _effective_scopes(request, principal)
    scope_mismatch = not required_scopes.issubset(effective_scopes)
    if actor_mismatch or scope_mismatch:
        denied_message = f'Access denied for the {credential_label} boundary.'
        raise _access_denied(denied_message)

    return principal


def _effective_scopes(request: Request, principal: Principal) -> frozenset[str]:
    """Apply published access-policy restrictions without granting new authority.

    Args:
        request: Request carrying the composed configuration repository.
        principal: Authenticated principal whose static scopes are being checked.

    Returns:
        The principal's static scopes intersected with any published policy for its actor type.

    Raises:
        ApiError: If a published access policy is malformed or unavailable.
    """
    repository = getattr(request.app.state, 'configuration_repository', None)
    if repository is None:
        return principal.scopes
    resolver = getattr(request.app.state, 'runtime_configuration_resolver', None)
    if resolver is None:
        policies = repository.list_configurations('access')
    else:
        try:
            snapshot = resolver.snapshot()
        except RuntimeConfigurationResolutionError as error:
            raise _access_denied('The active access policy is unavailable.') from error
        selected = (
            snapshot.configurations.get('access') if snapshot.release_set_id is not None else None
        )
        policies = [selected] if selected is not None else repository.list_configurations('access')
    matching: list[AccessPolicyConfiguration] = []
    for record in policies:
        try:
            policy = AccessPolicyConfiguration.model_validate(record.values)
        except ValueError as error:
            raise _access_denied('The configured access policy is invalid.') from error
        if policy.actor_type == principal.actor_type:
            matching.append(policy)
    if not matching:
        return principal.scopes
    allowed = frozenset(scope for policy in matching if policy.active for scope in policy.scopes)
    return principal.scopes.intersection(allowed)


def require_claimant(
    request: Request,
    authorization: str | None = Header(default=None),
    anonymous_session: str | None = Header(default=None, alias='X-Northwind-Anonymous-Session'),
) -> Principal:
    # Anonymous claimant sessions are deliberately limited to the claimant API. They let a
    # visitor start a report before authentication; the browser must generate and retain the
    # high-entropy session identifier. Account and staff boundaries still require real auth.
    if not authorization and anonymous_session:
        try:
            UUID(anonymous_session)
        except (ValueError, AttributeError):
            raise _authentication_required('The anonymous claimant session is invalid.') from None
        return Principal(
            subject=f'anonymous:{anonymous_session}',
            actor_type='claimant',
            scopes=CLAIMANT_SCOPES,
            auth_source='anonymous:browser_session',
            synthetic=True,
        )
    return _verify_principal(
        request,
        authorization,
        required_actor='claimant',
        required_scopes=CLAIMANT_SCOPES,
        credential_label='claimant',
    )


def require_claimant_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    principal = _verify_principal(
        request,
        authorization,
        required_actor='claimant',
        required_scopes=CLAIMANT_SCOPES,
        credential_label='claimant',
    )
    if principal.auth_source not in {'developer:claimant_session', 'runtime:claimant_session'}:
        raise _authentication_required('An active claimant session is required.')
    return principal


def require_staff(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    return _verify_principal(
        request,
        authorization,
        required_actor='staff',
        required_scopes=STAFF_SCOPES,
        credential_label='staff',
    )


def require_administrator(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    return _verify_principal(
        request,
        authorization,
        required_actor='administrator',
        required_scopes=ADMIN_SCOPES,
        credential_label='administrator',
    )


def require_integration_service(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    return _verify_principal(
        request,
        authorization,
        required_actor='integration_service',
        required_scopes=INTEGRATION_SCOPES,
        credential_label='integration-service',
    )
