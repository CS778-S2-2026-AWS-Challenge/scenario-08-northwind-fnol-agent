from typing import cast

from fastapi import APIRouter, Depends, Query, Request

from backend.core.auth import Principal, require_administrator
from backend.core.errors import ApiError
from backend.domain.operations import (
    OperationKind,
    OperationMetricsProjection,
    OperationPage,
    OperationRecord,
    OperationState,
)
from backend.repositories.operations import OperationRepository
from backend.services import admin_operations
from backend.services.runtime_configuration import RuntimeConfigurationResolver
from backend.services.support import paginate

router = APIRouter(prefix='/internal/v1/admin/operations', tags=['administration'])


def operation_repo(request: Request) -> OperationRepository:
    return cast(OperationRepository, request.app.state.operation_repository)


@router.get('', response_model=OperationPage)
def list_operations(
    request: Request,
    kind: OperationKind | None = Query(default=None),
    state: OperationState | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> OperationPage:
    repository = operation_repo(request)
    records = repository.list(
        kind=kind.value if kind is not None else None,
        state=state.value if state is not None else None,
        limit=100,
    )
    items, page = paginate(records, limit, cursor)
    return OperationPage(items=items, page=page)


@router.get('/metrics', response_model=OperationMetricsProjection)
def operation_metrics(
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> OperationMetricsProjection:
    resolver = cast(
        RuntimeConfigurationResolver,
        request.app.state.runtime_configuration_resolver,
    )
    return admin_operations.operation_metrics(operation_repo(request), resolver)


@router.get('/{operation_id}', response_model=OperationRecord)
def get_operation(
    request: Request,
    operation_id: str,
    _principal: Principal = Depends(require_administrator),
) -> OperationRecord:
    operation = operation_repo(request).get(operation_id)
    if operation is None:
        raise ApiError(
            status_code=404,
            code='OPERATION_NOT_FOUND',
            message='The requested Control Plane operation was not found.',
        )
    return operation
