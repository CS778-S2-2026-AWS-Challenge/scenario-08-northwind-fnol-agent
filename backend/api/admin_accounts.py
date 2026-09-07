from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.auth import Principal, require_administrator
from backend.core.errors import ApiError
from backend.domain.admin_identity import AdminAccountSessionPage, AdminAccountSessionProjection
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.identity import (
    AdminCustomerAccountCreate,
    AdminCustomerAccountPage,
    AdminCustomerAccountPatch,
    AdminCustomerAccountProjection,
)
from backend.domain.staff_identity import (
    AdminStaffAccountCreate,
    AdminStaffAccountPage,
    AdminStaffAccountPatch,
    AdminStaffAccountProjection,
)
from backend.repositories.identity import IdentityRepository
from backend.repositories.operations import OperationIdempotencyRecord, OperationRepository
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services import admin_accounts
from backend.services.support import (
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

router = APIRouter(prefix='/internal/v1/admin/accounts', tags=['administration'])


def customer_repo(request: Request) -> IdentityRepository:
    return cast(IdentityRepository, request.app.state.identity_repository)


def staff_repo(request: Request) -> StaffIdentityRepository:
    return cast(StaffIdentityRepository, request.app.state.staff_identity_repository)


def persistence_repo(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.data_runtime_bundle.repository)


def operation_repo(request: Request) -> OperationRepository:
    return cast(OperationRepository, request.app.state.operation_repository)


def _idempotent(
    request: Request,
    principal: Principal,
    key: str | None,
    route: str,
    payload: object,
    operation: Callable[[], BaseModel],
    status_code: int = status.HTTP_200_OK,
) -> BaseModel | JSONResponse:
    idempotency_key = require_idempotency_key(key)
    fingerprint = request_fingerprint(payload)
    repository = operation_repo(request)
    existing = repository.find_idempotency(principal.subject, route, idempotency_key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    result = operation()
    repository.save_idempotency(
        OperationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=idempotency_key,
            fingerprint=fingerprint,
            response=result.model_dump(mode='json'),
            status_code=status_code,
        )
    )
    return result


def _audit_subject(kind: str, account_id: str) -> AuditSubject:
    if kind == 'customers':
        return AuditSubject(subject_type=AuditSubjectType.CUSTOMER, subject_id=account_id)
    return AuditSubject(subject_type=AuditSubjectType.ACCESS, subject_id=f'staff:{account_id}')


@router.get('/customers', response_model=AdminCustomerAccountPage)
def list_customers(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminCustomerAccountPage:
    return admin_accounts.list_customers(customer_repo(request), limit, cursor)


@router.post(
    '/customers',
    response_model=AdminCustomerAccountProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_customer(
    payload: AdminCustomerAccountCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    route = 'POST /internal/v1/admin/accounts/customers'

    def operation() -> AdminCustomerAccountProjection:
        result = admin_accounts.create_customer(customer_repo(request), payload)
        admin_accounts.record_account_action(
            persistence_repo(request),
            principal,
            _audit_subject('customers', result.customer_id),
            action='Customer account created',
            reason='Created through the authorised administration boundary.',
            source_refs=[f'admin-account:{result.customer_id}'],
            correlation_id=getattr(request.state, 'request_id', None),
            idempotency_key=idempotency_key,
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        payload.model_dump(mode='json'),
        operation,
        status.HTTP_201_CREATED,
    )


@router.patch('/customers/{customer_id}', response_model=AdminCustomerAccountProjection)
def update_customer(
    customer_id: str,
    payload: AdminCustomerAccountPatch,
    request: Request,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected_revision = parse_if_match(if_match)
    route = f'PATCH /internal/v1/admin/accounts/customers/{customer_id}'

    def operation() -> AdminCustomerAccountProjection:
        result = admin_accounts.update_customer(
            customer_repo(request), customer_id, payload, expected_revision
        )
        admin_accounts.record_account_update(
            persistence_repo(request),
            principal,
            _audit_subject('customers', customer_id),
            list(payload.model_dump(exclude_none=True).keys()),
            'Customer account updated.',
            getattr(request.state, 'request_id', None),
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        {'payload': payload.model_dump(mode='json'), 'revision': expected_revision},
        operation,
    )


@router.get('/customers/{customer_id}/sessions', response_model=AdminAccountSessionPage)
def list_customer_sessions(
    customer_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminAccountSessionPage:
    return admin_accounts.list_customer_sessions(customer_repo(request), customer_id, limit, cursor)


@router.post(
    '/customers/{customer_id}/sessions/{session_id}/revoke',
    response_model=AdminAccountSessionProjection,
)
def revoke_customer_session(
    customer_id: str,
    session_id: str,
    request: Request,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected_revision = parse_if_match(if_match)
    route = f'POST /internal/v1/admin/accounts/customers/{customer_id}/sessions/{session_id}/revoke'

    def operation() -> AdminAccountSessionProjection:
        result = admin_accounts.revoke_customer_session(
            customer_repo(request), customer_id, session_id, expected_revision
        )
        admin_accounts.record_account_action(
            persistence_repo(request),
            principal,
            _audit_subject('customers', customer_id),
            action='Customer session revoked',
            reason='Revoked through the authorised administration boundary.',
            source_refs=[f'admin-account:{customer_id}', f'identity-session:{session_id}'],
            correlation_id=getattr(request.state, 'request_id', None),
            idempotency_key=idempotency_key,
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        {'revision': expected_revision},
        operation,
    )


@router.get('/staff', response_model=AdminStaffAccountPage)
def list_staff(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminStaffAccountPage:
    return admin_accounts.list_staff(staff_repo(request), limit, cursor)


@router.post(
    '/staff',
    response_model=AdminStaffAccountProjection,
    status_code=status.HTTP_201_CREATED,
)
def create_staff(
    payload: AdminStaffAccountCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    route = 'POST /internal/v1/admin/accounts/staff'

    def operation() -> AdminStaffAccountProjection:
        result = admin_accounts.create_staff(staff_repo(request), payload)
        admin_accounts.record_account_action(
            persistence_repo(request),
            principal,
            _audit_subject('staff', result.staff_id),
            action='Staff account created',
            reason='Created through the authorised administration boundary.',
            source_refs=[f'admin-account:staff:{result.staff_id}'],
            correlation_id=getattr(request.state, 'request_id', None),
            idempotency_key=idempotency_key,
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        payload.model_dump(mode='json'),
        operation,
        status.HTTP_201_CREATED,
    )


@router.patch('/staff/{staff_id}', response_model=AdminStaffAccountProjection)
def update_staff(
    staff_id: str,
    payload: AdminStaffAccountPatch,
    request: Request,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected_revision = parse_if_match(if_match)
    route = f'PATCH /internal/v1/admin/accounts/staff/{staff_id}'

    def operation() -> AdminStaffAccountProjection:
        result = admin_accounts.update_staff(
            staff_repo(request), staff_id, payload, expected_revision
        )
        admin_accounts.record_account_update(
            persistence_repo(request),
            principal,
            _audit_subject('staff', staff_id),
            list(payload.model_dump(exclude_none=True).keys()),
            'Staff account updated.',
            getattr(request.state, 'request_id', None),
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        {'payload': payload.model_dump(mode='json'), 'revision': expected_revision},
        operation,
    )


@router.get('/staff/{staff_id}/sessions', response_model=AdminAccountSessionPage)
def list_staff_sessions(
    staff_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminAccountSessionPage:
    return admin_accounts.list_staff_sessions(staff_repo(request), staff_id, limit, cursor)


@router.post(
    '/staff/{staff_id}/sessions/{session_id}/revoke',
    response_model=AdminAccountSessionProjection,
)
def revoke_staff_session(
    staff_id: str,
    session_id: str,
    request: Request,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected_revision = parse_if_match(if_match)
    route = f'POST /internal/v1/admin/accounts/staff/{staff_id}/sessions/{session_id}/revoke'

    def operation() -> AdminAccountSessionProjection:
        result = admin_accounts.revoke_staff_session(
            staff_repo(request), staff_id, session_id, expected_revision
        )
        admin_accounts.record_account_action(
            persistence_repo(request),
            principal,
            _audit_subject('staff', staff_id),
            action='Staff session revoked',
            reason='Revoked through the authorised administration boundary.',
            source_refs=[f'admin-account:staff:{staff_id}', f'identity-session:{session_id}'],
            correlation_id=getattr(request.state, 'request_id', None),
            idempotency_key=idempotency_key,
        )
        return result

    return _idempotent(
        request,
        principal,
        idempotency_key,
        route,
        {'revision': expected_revision},
        operation,
    )


@router.get('/customers/{customer_id}/audit', response_model=dict)
def audit_customer(
    customer_id: str,
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    if customer_repo(request).get_account(customer_id) is None:
        raise ApiError(
            status_code=404, code='ACCOUNT_NOT_FOUND', message='The customer account was not found.'
        )
    subject = AuditSubject(subject_type=AuditSubjectType.CUSTOMER, subject_id=customer_id)
    return {
        'items': persistence_repo(request).list_audit_events_internal(subject),
        'page': {'next_cursor': None},
    }


@router.get('/staff/{staff_id}/audit', response_model=dict)
def audit_staff(
    staff_id: str,
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    if staff_repo(request).get_account(staff_id) is None:
        raise ApiError(
            status_code=404, code='ACCOUNT_NOT_FOUND', message='The staff account was not found.'
        )
    subject = AuditSubject(subject_type=AuditSubjectType.ACCESS, subject_id=f'staff:{staff_id}')
    return {
        'items': persistence_repo(request).list_audit_events_internal(subject),
        'page': {'next_cursor': None},
    }
