from typing import cast

from fastapi import APIRouter, Depends, Header, Request, status

from backend.core.auth import Principal, require_claimant
from backend.domain.models import CreateSupportRequest, SupportRequestResponse
from backend.repositories.handoff_guard import guarded_handoff_repository
from backend.repositories.protocols import PersistenceRepository
from backend.services.handoffs import create_support_request

router = APIRouter(prefix='/api/v1/claims', tags=['claimant-support'])


def repository_for(request: Request) -> PersistenceRepository:
    repository = cast(PersistenceRepository, request.app.state.claim_repository)
    return guarded_handoff_repository(repository)


@router.post(
    '/{claim_id}/support-requests',
    response_model=SupportRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_support(
    claim_id: str,
    payload: CreateSupportRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> SupportRequestResponse:
    return create_support_request(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )
