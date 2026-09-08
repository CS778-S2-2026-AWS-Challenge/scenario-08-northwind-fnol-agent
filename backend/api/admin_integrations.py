from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
from backend.core.errors import ApiError
from backend.domain.integration_health import (
    IntegrationHealthCheckPage,
    IntegrationHealthCheckRecord,
)
from backend.domain.integration_registry import IntegrationStatusPage, IntegrationStatusProjection
from backend.repositories.integration_health import IntegrationHealthRepository
from backend.repositories.operations import OperationIdempotencyRecord, OperationRepository
from backend.services import integration_registry
from backend.services.admin_action_projection import integration_projection
from backend.services.runtime_integrations import RuntimeIntegrationPolicy
from backend.services.support import request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin/integrations', tags=['administration'])


def health_repo(request: Request) -> IntegrationHealthRepository:
    return cast(IntegrationHealthRepository, request.app.state.integration_health_repository)


def operation_repo(request: Request) -> OperationRepository:
    return cast(OperationRepository, request.app.state.operation_repository)


def runtime_integration_policy(request: Request) -> RuntimeIntegrationPolicy:
    return cast(RuntimeIntegrationPolicy, request.app.state.runtime_integration_policy)


@router.get('', response_model=IntegrationStatusPage)
def list_integrations(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> IntegrationStatusPage:
    page = integration_registry.list_integrations(
        request.app.state,
        runtime_integration_policy(request).snapshot(),
        limit,
        cursor,
    )
    return page.model_copy(update={'items': [integration_projection(item) for item in page.items]})


@router.get('/{integration_id}', response_model=IntegrationStatusProjection)
def get_integration(
    request: Request,
    integration_id: str,
    _principal: Principal = Depends(require_administrator),
) -> IntegrationStatusProjection:
    return integration_projection(
        integration_registry.get_integration(
            request.app.state,
            runtime_integration_policy(request).snapshot(),
            integration_id,
        )
    )


@router.post('/{integration_id}/health-check', response_model=IntegrationHealthCheckRecord)
def check_integration(
    request: Request,
    integration_id: str,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> IntegrationHealthCheckRecord | JSONResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'POST /internal/v1/admin/integrations/{integration_id}/health-check'
    payload = {'integration_id': integration_id}
    fingerprint = request_fingerprint(payload)
    repository = operation_repo(request)
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    result = integration_registry.check_integration(
        request.app.state,
        health_repo(request),
        runtime_integration_policy(request).snapshot(),
        integration_id,
        repository,
    )
    repository.save_idempotency(
        OperationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            response=result.model_dump(mode='json'),
            status_code=200,
        )
    )
    return result


@router.get('/{integration_id}/health-checks', response_model=IntegrationHealthCheckPage)
def health_history(
    request: Request,
    integration_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    _principal: Principal = Depends(require_administrator),
) -> IntegrationHealthCheckPage:
    return integration_registry.health_history(health_repo(request), integration_id, limit)
