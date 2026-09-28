from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status

from backend.core.auth import Principal, require_administrator, require_staff
from backend.core.errors import ApiError
from backend.domain.feedback import (
    FeedbackCreate,
    FeedbackPage,
    FeedbackReceipt,
    FeedbackRecord,
)
from backend.domain.models import PageInfo
from backend.repositories.feedback import FeedbackIdempotencyConflict, FeedbackRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.support import (
    decode_cursor,
    encode_cursor,
    request_fingerprint,
    require_idempotency_key,
)

staff_router = APIRouter(prefix='/api/v1/staff/feedback', tags=['staff feedback'])
admin_router = APIRouter(prefix='/internal/v1/admin/feedback', tags=['administration'])


def repository_for(request: Request) -> FeedbackRepository:
    return cast(FeedbackRepository, request.app.state.feedback_repository)


@staff_router.post('', response_model=FeedbackReceipt, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_staff),
) -> FeedbackReceipt:
    key = require_idempotency_key(idempotency_key)
    staff_repository = cast(
        StaffIdentityRepository,
        request.app.state.staff_identity_repository,
    )
    account = staff_repository.get_account(principal.subject)
    if account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The staff account was not found.',
        )
    repository = repository_for(request)
    record = FeedbackRecord(
        feedback_id=repository.new_feedback_id(),
        message=payload.message,
        submitted_by_staff_id=principal.subject,
        submitted_by_display_name=account.display_name,
        created_at=datetime.now(UTC),
    )
    try:
        saved = repository.submit(
            record,
            actor=principal.subject,
            key=key,
            fingerprint=request_fingerprint(payload.model_dump(mode='json')),
        )
    except FeedbackIdempotencyConflict as error:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='Idempotency-Key was reused with different feedback.',
        ) from error
    return FeedbackReceipt(feedback_id=saved.feedback_id, created_at=saved.created_at)


@admin_router.get('', response_model=FeedbackPage)
def list_feedback(
    request: Request,
    staff_id: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> FeedbackPage:
    offset = decode_cursor(cursor)
    records = repository_for(request).list(staff_id=staff_id, limit=limit + 1, offset=offset)
    items = records[:limit]
    next_cursor = encode_cursor(offset + len(items)) if len(records) > limit else None
    return FeedbackPage(items=items, page=PageInfo(next_cursor=next_cursor))


@admin_router.get('/{feedback_id}', response_model=FeedbackRecord)
def get_feedback(
    feedback_id: str,
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> FeedbackRecord:
    record = repository_for(request).get(feedback_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code='FEEDBACK_NOT_FOUND',
            message='The requested staff feedback was not found.',
        )
    return record
