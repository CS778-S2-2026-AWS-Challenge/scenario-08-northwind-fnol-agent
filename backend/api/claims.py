from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status

from backend.adapters.claims_service import ClaimsServiceAdapter
from backend.core.auth import Principal, require_claimant
from backend.domain.models import (
    ClaimantClaim,
    ClaimantSession,
    ClaimCreationResponse,
    ClaimListResponse,
    CreateClaimRequest,
    CreateClaimResponse,
    CreateMessageRequest,
    FormConfirmationRequest,
    FormConfirmationResponse,
    FormPatchRequest,
    FormPatchResponse,
    MessageListResponse,
    MessageTurnResponse,
    StartSessionRequest,
    WorkflowState,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import AgentTurnProvider
from backend.services.claim_creation import create_claim_from_confirmed_report
from backend.services.claims import (
    confirm_form_fields,
    get_claim,
    get_session,
    list_claims,
    start_claim,
    update_form,
)
from backend.services.messages import list_claim_messages, submit_message
from backend.services.resume import start_session_with_recovery

router = APIRouter(prefix='/api/v1/claims', tags=['claimant'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def agent_for(request: Request) -> AgentTurnProvider:
    return cast(AgentTurnProvider, request.app.state.agent_turn_provider)


def claims_adapter_for(request: Request) -> ClaimsServiceAdapter:
    return cast(ClaimsServiceAdapter, request.app.state.claims_service_adapter)


@router.post('', response_model=CreateClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    request: Request,
    payload: CreateClaimRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> CreateClaimResponse:
    return start_claim(repository_for(request), principal, payload, idempotency_key)


@router.get('', response_model=ClaimListResponse)
def read_claims(
    request: Request,
    principal: Principal = Depends(require_claimant),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    workflow_state: WorkflowState | None = Query(default=None),
    updated_after: datetime | None = Query(default=None),
) -> ClaimListResponse:
    return list_claims(
        repository_for(request),
        principal,
        limit=limit,
        cursor=cursor,
        workflow_state=workflow_state,
        updated_after=updated_after,
    )


@router.get('/{claim_id}', response_model=ClaimantClaim)
def read_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> ClaimantClaim:
    return get_claim(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/creation',
    response_model=ClaimCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_external_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimCreationResponse:
    return create_claim_from_confirmed_report(
        repository_for(request),
        claims_adapter_for(request),
        principal,
        claim_id,
        idempotency_key,
        if_match,
    )


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
    return start_session_with_recovery(
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


@router.post(
    '/{claim_id}/sessions/{session_id}/messages',
    response_model=MessageTurnResponse,
)
def create_message(
    claim_id: str,
    session_id: str,
    request: Request,
    payload: CreateMessageRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> MessageTurnResponse:
    return submit_message(
        repository_for(request),
        agent_for(request),
        principal,
        claim_id,
        session_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.get(
    '/{claim_id}/sessions/{session_id}/messages',
    response_model=MessageListResponse,
)
def read_messages(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    before: datetime | None = Query(default=None),
    after: datetime | None = Query(default=None),
) -> MessageListResponse:
    return list_claim_messages(
        repository_for(request),
        principal,
        claim_id,
        session_id,
        limit=limit,
        cursor=cursor,
        before=before,
        after=after,
    )


@router.patch('/{claim_id}/form', response_model=FormPatchResponse)
def patch_form(
    claim_id: str,
    request: Request,
    payload: FormPatchRequest,
    principal: Principal = Depends(require_claimant),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> FormPatchResponse:
    return update_form(repository_for(request), principal, claim_id, payload, if_match)


@router.post('/{claim_id}/form/confirmations', response_model=FormConfirmationResponse)
def confirm_form(
    claim_id: str,
    request: Request,
    payload: FormConfirmationRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> FormConfirmationResponse:
    return confirm_form_fields(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )
