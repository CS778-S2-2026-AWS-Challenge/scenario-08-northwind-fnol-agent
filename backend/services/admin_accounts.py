from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TypeVar

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.admin_identity import (
    AdminAccountSessionPage,
    AdminAccountSessionProjection,
    AdminSessionState,
)
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditVisibility,
)
from backend.domain.identity import (
    AdminCustomerAccountCreate,
    AdminCustomerAccountPage,
    AdminCustomerAccountPatch,
    AdminCustomerAccountProjection,
    ClaimantAuthSessionRecord,
    CustomerAccountRecord,
)
from backend.domain.ids import new_id
from backend.domain.models import PageInfo
from backend.domain.staff_identity import (
    AdminStaffAccountCreate,
    AdminStaffAccountPage,
    AdminStaffAccountPatch,
    AdminStaffAccountProjection,
    StaffAccountRecord,
    StaffAuthSessionRecord,
)
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.admin_action_projection import (
    account_session_projection,
    customer_account_projection,
    staff_account_projection,
)
from backend.services.support import decode_cursor, encode_cursor

RecordT = TypeVar('RecordT')


def _page[T](
    items: Sequence[T],
    limit: int,
    cursor: str | None,
    project: Callable[[T], object],
) -> tuple[list[object], PageInfo]:
    offset = decode_cursor(cursor)
    bounded_limit = min(limit, 100)
    selected = list(items)[offset : offset + bounded_limit]
    next_offset = offset + len(selected)
    next_cursor = encode_cursor(next_offset) if next_offset < len(items) else None
    return [project(item) for item in selected], PageInfo(next_cursor=next_cursor)


def list_customers(
    repository: IdentityRepository, limit: int, cursor: str | None
) -> AdminCustomerAccountPage:
    items, page = _page(
        repository.list_accounts(),
        limit,
        cursor,
        lambda item: customer_account_projection(customer_projection(item)),
    )
    return AdminCustomerAccountPage(items=items, page=page)


def list_staff(
    repository: StaffIdentityRepository, limit: int, cursor: str | None
) -> AdminStaffAccountPage:
    items, page = _page(
        repository.list_accounts(),
        limit,
        cursor,
        lambda item: staff_account_projection(staff_projection(item)),
    )
    return AdminStaffAccountPage(items=items, page=page)


def update_customer(
    repository: IdentityRepository,
    customer_id: str,
    payload: AdminCustomerAccountPatch,
    expected_revision: int,
) -> AdminCustomerAccountProjection:
    account = repository.get_account(customer_id)
    if account is None:
        raise ApiError(
            status_code=404, code='ACCOUNT_NOT_FOUND', message='The customer account was not found.'
        )
    if account.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The customer account revision is stale.',
            current_revision=account.revision,
        )
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='At least one account field must change.',
        )
    updated = replace(
        account,
        **updates,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, expected_revision)
    return customer_account_projection(customer_projection(updated))


def update_staff(
    repository: StaffIdentityRepository,
    staff_id: str,
    payload: AdminStaffAccountPatch,
    expected_revision: int,
) -> AdminStaffAccountProjection:
    account = repository.get_account(staff_id)
    if account is None:
        raise ApiError(
            status_code=404, code='ACCOUNT_NOT_FOUND', message='The staff account was not found.'
        )
    if account.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The staff account revision is stale.',
            current_revision=account.revision,
        )
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='At least one account field must change.',
        )
    if 'roles' in updates:
        roles = tuple(role.strip() for role in updates['roles'] if role.strip())
        if not roles:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='At least one staff role is required.',
            )
        updates['roles'] = roles
    updated = replace(
        account,
        **updates,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, expected_revision)
    return staff_account_projection(staff_projection(updated))


def create_customer(
    repository: IdentityRepository,
    payload: AdminCustomerAccountCreate,
) -> AdminCustomerAccountProjection:
    account = repository.create_account(
        payload.email,
        payload.initial_password,
        payload.display_name,
        payload.phone,
    )
    if account is None:
        raise ApiError(
            status_code=409,
            code='RESOURCE_CONFLICT',
            message='A customer account with that email already exists.',
        )
    return customer_account_projection(customer_projection(account))


def create_staff(
    repository: StaffIdentityRepository,
    payload: AdminStaffAccountCreate,
) -> AdminStaffAccountProjection:
    roles = tuple(role.strip() for role in payload.roles if role.strip())
    if not roles:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='At least one staff role is required.',
        )
    account = repository.create_account(
        payload.email,
        payload.initial_password,
        payload.display_name,
        roles,
    )
    if account is None:
        raise ApiError(
            status_code=409,
            code='RESOURCE_CONFLICT',
            message='A staff account with that email already exists.',
        )
    return staff_account_projection(staff_projection(account))


def _session_projection(
    record: ClaimantAuthSessionRecord | StaffAuthSessionRecord,
) -> AdminAccountSessionProjection:
    revoked_at = record.revoked_at
    expires_at = record.expires_at
    state = (
        AdminSessionState.REVOKED
        if revoked_at is not None
        else AdminSessionState.EXPIRED
        if expires_at <= datetime.now(UTC)
        else AdminSessionState.ACTIVE
    )
    projection = AdminAccountSessionProjection(
        session_id=record.session_id,
        state=state,
        revision=record.revision,
        created_at=record.created_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
        updated_at=record.updated_at,
    )
    return account_session_projection(projection)


def list_customer_sessions(
    repository: IdentityRepository, customer_id: str, limit: int, cursor: str | None
) -> AdminAccountSessionPage:
    if repository.get_account(customer_id) is None:
        raise ApiError(
            status_code=404,
            code='ACCOUNT_NOT_FOUND',
            message='The customer account was not found.',
        )
    items, page = _page(repository.list_sessions(customer_id), limit, cursor, _session_projection)
    return AdminAccountSessionPage(items=items, page=page)


def list_staff_sessions(
    repository: StaffIdentityRepository, staff_id: str, limit: int, cursor: str | None
) -> AdminAccountSessionPage:
    if repository.get_account(staff_id) is None:
        raise ApiError(
            status_code=404,
            code='ACCOUNT_NOT_FOUND',
            message='The staff account was not found.',
        )
    items, page = _page(repository.list_sessions(staff_id), limit, cursor, _session_projection)
    return AdminAccountSessionPage(items=items, page=page)


def revoke_customer_session(
    repository: IdentityRepository,
    customer_id: str,
    session_id: str,
    expected_revision: int,
) -> AdminAccountSessionProjection:
    record = repository.get_session_by_id(session_id)
    if record is None or record.customer_id != customer_id:
        raise ApiError(
            status_code=404,
            code='SESSION_NOT_FOUND',
            message='The customer session was not found.',
        )
    if record.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The customer session revision is stale.',
            current_revision=record.revision,
        )
    try:
        return _session_projection(repository.revoke_session_by_id(session_id, expected_revision))
    except ValueError as error:
        if str(error) == 'session_not_active':
            raise ApiError(
                status_code=409,
                code='SESSION_NOT_ACTIVE',
                message='The customer session is not active.',
            ) from error
        raise


def revoke_staff_session(
    repository: StaffIdentityRepository,
    staff_id: str,
    session_id: str,
    expected_revision: int,
) -> AdminAccountSessionProjection:
    record = repository.get_session_by_id(session_id)
    if record is None or record.staff_id != staff_id:
        raise ApiError(
            status_code=404,
            code='SESSION_NOT_FOUND',
            message='The staff session was not found.',
        )
    if record.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The staff session revision is stale.',
            current_revision=record.revision,
        )
    try:
        return _session_projection(repository.revoke_session_by_id(session_id, expected_revision))
    except ValueError as error:
        if str(error) == 'session_not_active':
            raise ApiError(
                status_code=409,
                code='SESSION_NOT_ACTIVE',
                message='The staff session is not active.',
            ) from error
        raise


def customer_projection(account: CustomerAccountRecord) -> AdminCustomerAccountProjection:
    return AdminCustomerAccountProjection(
        customer_id=account.customer_id,
        email=account.email,
        display_name=account.display_name,
        phone=account.phone,
        active=account.active,
        communication_preferences=account.communication_preferences,
        revision=account.revision,
        updated_at=account.updated_at,
    )


def staff_projection(account: StaffAccountRecord) -> AdminStaffAccountProjection:
    return AdminStaffAccountProjection(
        staff_id=account.staff_id,
        email=account.email,
        display_name=account.display_name,
        roles=list(account.roles),
        active=account.active,
        revision=account.revision,
        updated_at=account.updated_at,
    )


def record_account_update(
    repository: PersistenceRepository,
    principal: Principal,
    subject: AuditSubject,
    changed_fields: Sequence[str],
    reason: str,
    correlation_id: str | None,
) -> None:
    repository.append_audit_event(
        AuditEventEnvelope(
            event_id=new_id('aud'),
            event_type=AuditEventType.ACTION_COMPLETED,
            outcome=AuditOutcome.SUCCEEDED,
            subject=subject,
            actor=AuditActor(
                actor_id=f'{principal.actor_type}:{principal.subject}',
                actor_type='system',
                auth_source=principal.auth_source,
            ),
            reason=f'{reason} (changed: {", ".join(sorted(set(changed_fields)))})',
            source_refs=[f'admin-account:{subject.subject_id}'],
            visibility=AuditVisibility.ADMINISTRATION_ONLY,
            correlation_id=correlation_id,
            created_at=datetime.now(UTC),
        )
    )


def record_account_action(
    repository: PersistenceRepository,
    principal: Principal,
    subject: AuditSubject,
    *,
    action: str,
    reason: str,
    source_refs: Sequence[str],
    correlation_id: str | None,
    idempotency_key: str | None,
) -> None:
    """Append a bounded administration audit fact for an identity action."""

    repository.append_audit_event(
        AuditEventEnvelope(
            event_id=new_id('aud'),
            event_type=AuditEventType.ACTION_COMPLETED,
            outcome=AuditOutcome.SUCCEEDED,
            subject=subject,
            actor=AuditActor(
                actor_id=f'{principal.actor_type}:{principal.subject}',
                actor_type='system',
                auth_source=principal.auth_source,
            ),
            reason=f'{action}: {reason}',
            source_refs=list(source_refs),
            visibility=AuditVisibility.ADMINISTRATION_ONLY,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
        )
    )
