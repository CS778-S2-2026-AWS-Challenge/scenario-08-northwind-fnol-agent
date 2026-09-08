from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
from backend.core.errors import ApiError
from backend.domain.evaluation import EvaluationCreate, EvaluationPage, EvaluationRecord
from backend.repositories.evaluations import EvaluationRepository
from backend.repositories.operations import OperationIdempotencyRecord
from backend.services.support import paginate, request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin/evaluations', tags=['administration'])


def repository_for(request: Request) -> EvaluationRepository:
    return cast(EvaluationRepository, request.app.state.evaluation_repository)


@router.post('', response_model=EvaluationRecord, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    payload: EvaluationCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> EvaluationRecord | JSONResponse:
    key = require_idempotency_key(idempotency_key)
    route = 'POST /internal/v1/admin/evaluations'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    operation_repository = request.app.state.operation_repository
    existing = operation_repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    now = datetime.now(UTC)
    repository = repository_for(request)
    record = repository.create(
        EvaluationRecord(
            evaluation_id=repository.new_evaluation_id(),
            created_at=now,
            completed_at=now,
            **payload.model_dump(),
        )
    )
    operation_repository.save_idempotency(
        OperationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            response=record.model_dump(mode='json'),
            status_code=status.HTTP_201_CREATED,
        )
    )
    return record


@router.get('', response_model=EvaluationPage)
def list_evaluations(
    request: Request,
    purpose: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> EvaluationPage:
    records = repository_for(request).list(purpose=purpose, state=state, limit=100)
    items, page = paginate(records, limit, cursor)
    return EvaluationPage(items=items, page=page)


@router.get('/{evaluation_id}', response_model=EvaluationRecord)
def get_evaluation(
    evaluation_id: str,
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> EvaluationRecord:
    record = repository_for(request).get(evaluation_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code='EVALUATION_NOT_FOUND',
            message='The requested evaluation was not found.',
        )
    return record
