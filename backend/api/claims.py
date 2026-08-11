from typing import cast

from fastapi import APIRouter, Depends, Header, Request, status

from backend.core.auth import Principal, require_claimant
from backend.domain.models import (
    ClaimantClaim,
    ClaimantSession,
    CreateClaimRequest,
    CreateClaimResponse,
    FormPatchRequest,
    FormPatchResponse,
    StartSessionRequest,
)
from backend.repositories.protocols import ClaimRepository
from backend.services.claims import (
    get_claim,
    get_session,
    start_claim,
    start_session,
    update_form,
)

router = APIRouter(prefix='/api/v1/claims', tags=['claimant'])


def repository_for(request: Request) -> ClaimRepository:
    return cast(ClaimRepository, request.app.state.claim_repository)


@router.post('', response_model=CreateClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    request: Request,
    payload: CreateClaimRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> CreateClaimResponse:
    return start_claim(repository_for(request), principal, payload, idempotency_key)


@router.get('/{claim_id}', response_model=ClaimantClaim)
def read_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> ClaimantClaim:
    return get_claim(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/sessions',
    response_model=ClaimantSession,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    claim_id: str,
    request: Request,
    payload: StartSessionRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> ClaimantSession:
    return start_session(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
    )


@router.get('/{claim_id}/sessions/{session_id}', response_model=ClaimantSession)
def read_session(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> ClaimantSession:
    return get_session(repository_for(request), principal, claim_id, session_id)


@router.patch('/{claim_id}/form', response_model=FormPatchResponse)
def patch_form(
    claim_id: str,
    request: Request,
    payload: FormPatchRequest,
    principal: Principal = Depends(require_claimant),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> FormPatchResponse:
    return update_form(repository_for(request), principal, claim_id, payload, if_match)
