"""Claimant routes for saved policies and separately protected account data."""

import logging
from collections.abc import Callable
from typing import TypeVar, cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from backend.core.auth import Principal, require_claimant_session
from backend.core.errors import ApiError
from backend.domain.account_data import (
    ClaimPolicySelectionResponse,
    CreateIdentityDocumentRequest,
    CreatePaymentDestinationRequest,
    CreatePolicyNumberRequest,
    IdentityDocumentListResponse,
    IdentityDocumentProjection,
    PaymentDestinationListResponse,
    PaymentDestinationProjection,
    PolicyNumberListResponse,
    PolicyNumberProjection,
    SelectPolicyNumberRequest,
    UpdateIdentityDocumentRequest,
    UpdatePaymentDestinationRequest,
    UpdatePolicyNumberRequest,
)
from backend.repositories.account_data import AccountDataRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.account_data import (
    create_identity_document,
    create_payment_destination,
    create_policy,
    deactivate_record,
    list_identity_documents,
    list_payment_destinations,
    list_policies,
    select_policy,
    update_identity_document,
    update_payment_destination,
    update_policy,
)
from backend.services.protected_values import ProtectedValueAdapter

account_router = APIRouter(prefix='/account', tags=['claimant account data'])
claim_router = APIRouter(tags=['claimant account data'])
logger = logging.getLogger(__name__)
OperationResultT = TypeVar('OperationResultT')


def _execute_logged_account_operation(
    *,
    operation: str,
    request: Request,
    principal: Principal,
    execute: Callable[[], OperationResultT],
    resource_id: str | None = None,
) -> OperationResultT:
    context = {
        'request_id': str(getattr(request.state, 'request_id', 'unavailable')),
        'customer_id': principal.subject,
    }
    if resource_id is not None:
        context['resource_id'] = resource_id
    try:
        result = execute()
    except ApiError as error:
        logger.info(
            operation,
            extra={**context, 'outcome': 'rejected', 'error_code': error.code},
        )
        raise
    except Exception:
        logger.exception(
            operation,
            extra={**context, 'outcome': 'failed', 'error_code': 'INTERNAL_ERROR'},
        )
        raise
    result_id = next(
        (
            str(value)
            for field in ('policy_id', 'payment_destination_id', 'identity_id', 'resource_id')
            if (value := getattr(result, field, None)) is not None
        ),
        None,
    )
    success_context = {**context, 'outcome': 'succeeded'}
    if result_id is not None:
        success_context['resource_id'] = result_id
    revision = getattr(result, 'revision', None)
    if revision is not None:
        success_context['revision'] = revision
    logger.info(operation, extra=success_context)
    return result


def repositories_for(request: Request) -> tuple[AccountDataRepository, PersistenceRepository]:
    repository = request.app.state.claim_repository
    return cast(AccountDataRepository, repository), cast(PersistenceRepository, repository)


def protected_values_for(request: Request) -> ProtectedValueAdapter:
    return cast(ProtectedValueAdapter, request.app.state.protected_value_adapter)


@account_router.post('/policies', response_model=PolicyNumberProjection, status_code=201)
def post_policy(
    payload: CreatePolicyNumberRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> PolicyNumberProjection:
    repository, persistence = repositories_for(request)
    return _execute_logged_account_operation(
        operation='account_policy.create',
        request=request,
        principal=principal,
        execute=lambda: create_policy(repository, persistence, principal, payload, idempotency_key),
    )


@account_router.get('/policies', response_model=PolicyNumberListResponse)
def get_policies(
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=25, ge=1),
    cursor: str | None = Query(default=None),
) -> PolicyNumberListResponse:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='account_policy.list',
        request=request,
        principal=principal,
        execute=lambda: list_policies(repository, principal, include_inactive, limit, cursor),
    )


@account_router.patch('/policies/{policy_id}', response_model=PolicyNumberProjection)
def patch_policy(
    policy_id: str,
    payload: UpdatePolicyNumberRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> PolicyNumberProjection:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='account_policy.update',
        request=request,
        principal=principal,
        resource_id=policy_id,
        execute=lambda: update_policy(repository, principal, policy_id, payload, if_match),
    )


@account_router.delete('/policies/{policy_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(
    policy_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> Response:
    repository, _ = repositories_for(request)
    _execute_logged_account_operation(
        operation='account_policy.retire',
        request=request,
        principal=principal,
        resource_id=policy_id,
        execute=lambda: deactivate_record(repository, principal, 'policy', policy_id, if_match),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@account_router.post(
    '/payment-destinations', response_model=PaymentDestinationProjection, status_code=201
)
def post_payment_destination(
    payload: CreatePaymentDestinationRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> PaymentDestinationProjection:
    repository, persistence = repositories_for(request)
    return _execute_logged_account_operation(
        operation='payment_destination.create',
        request=request,
        principal=principal,
        execute=lambda: create_payment_destination(
            repository,
            persistence,
            protected_values_for(request),
            principal,
            payload,
            idempotency_key,
        ),
    )


@account_router.get('/payment-destinations', response_model=PaymentDestinationListResponse)
def get_payment_destinations(
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=25, ge=1),
    cursor: str | None = Query(default=None),
) -> PaymentDestinationListResponse:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='payment_destination.list',
        request=request,
        principal=principal,
        execute=lambda: list_payment_destinations(
            repository, principal, include_inactive, limit, cursor
        ),
    )


@account_router.patch(
    '/payment-destinations/{payment_destination_id}',
    response_model=PaymentDestinationProjection,
)
def patch_payment_destination(
    payment_destination_id: str,
    payload: UpdatePaymentDestinationRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> PaymentDestinationProjection:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='payment_destination.update',
        request=request,
        principal=principal,
        resource_id=payment_destination_id,
        execute=lambda: update_payment_destination(
            repository,
            protected_values_for(request),
            principal,
            payment_destination_id,
            payload,
            if_match,
        ),
    )


@account_router.delete(
    '/payment-destinations/{payment_destination_id}', status_code=status.HTTP_204_NO_CONTENT
)
def delete_payment_destination(
    payment_destination_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> Response:
    repository, _ = repositories_for(request)
    _execute_logged_account_operation(
        operation='payment_destination.retire',
        request=request,
        principal=principal,
        resource_id=payment_destination_id,
        execute=lambda: deactivate_record(
            repository, principal, 'payment destination', payment_destination_id, if_match
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@account_router.post(
    '/identity-documents', response_model=IdentityDocumentProjection, status_code=201
)
def post_identity_document(
    payload: CreateIdentityDocumentRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> IdentityDocumentProjection:
    repository, persistence = repositories_for(request)
    return _execute_logged_account_operation(
        operation='identity_document.create',
        request=request,
        principal=principal,
        execute=lambda: create_identity_document(
            repository,
            persistence,
            protected_values_for(request),
            principal,
            payload,
            idempotency_key,
        ),
    )


@account_router.get('/identity-documents', response_model=IdentityDocumentListResponse)
def get_identity_documents(
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=25, ge=1),
    cursor: str | None = Query(default=None),
) -> IdentityDocumentListResponse:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='identity_document.list',
        request=request,
        principal=principal,
        execute=lambda: list_identity_documents(
            repository, principal, include_inactive, limit, cursor
        ),
    )


@account_router.patch(
    '/identity-documents/{identity_id}', response_model=IdentityDocumentProjection
)
def patch_identity_document(
    identity_id: str,
    payload: UpdateIdentityDocumentRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> IdentityDocumentProjection:
    repository, _ = repositories_for(request)
    return _execute_logged_account_operation(
        operation='identity_document.update',
        request=request,
        principal=principal,
        resource_id=identity_id,
        execute=lambda: update_identity_document(
            repository,
            protected_values_for(request),
            principal,
            identity_id,
            payload,
            if_match,
        ),
    )


@account_router.delete('/identity-documents/{identity_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_identity_document(
    identity_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> Response:
    repository, _ = repositories_for(request)
    _execute_logged_account_operation(
        operation='identity_document.retire',
        request=request,
        principal=principal,
        resource_id=identity_id,
        execute=lambda: deactivate_record(
            repository, principal, 'identity document', identity_id, if_match
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@claim_router.post(
    '/{claim_id}/policy-selections',
    response_model=ClaimPolicySelectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_policy_selection(
    claim_id: str,
    payload: SelectPolicyNumberRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimPolicySelectionResponse:
    repository, persistence = repositories_for(request)
    return _execute_logged_account_operation(
        operation='claim_policy.select',
        request=request,
        principal=principal,
        resource_id=claim_id,
        execute=lambda: select_policy(
            repository, persistence, principal, claim_id, payload, idempotency_key, if_match
        ),
    )
