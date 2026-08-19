from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status

from backend.core.auth import Principal, require_staff
from backend.domain.models import (
    AcceptHandoffRequest,
    CreateStaffActionRequest,
    CreateStaffMessageRequest,
    HandoffMutationResponse,
    ResolveHandoffRequest,
    SignalDecisionRequest,
    SignalDecisionResponse,
    StaffActionMutationResponse,
    StaffMessageResponse,
    UpdateStaffActionRequest,
    WorkbenchClaimDetail,
    WorkbenchClaimListResponse,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.staff_actions import (
    accept_handoff,
    create_staff_action,
    decide_signal,
    resolve_handoff,
    send_staff_message,
    update_staff_action,
)
from backend.services.workbench import get_workbench_claim_detail, list_workbench_claims

router = APIRouter(prefix='/api/v1/workbench/claims', tags=['workbench'])


@router.post('/{claim_id}/messages', response_model=StaffMessageResponse)
def create_staff_message(
    claim_id: str,
    payload: CreateStaffMessageRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> StaffMessageResponse:
    return send_staff_message(
        repository_for(request), principal, claim_id, payload, idempotency_key, if_match
    )


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


@router.get('', response_model=WorkbenchClaimListResponse)
def read_workbench_claims(
    request: Request,
    principal: Principal = Depends(require_staff),
    view: str | None = Query(default=None),
) -> WorkbenchClaimListResponse:
    return list_workbench_claims(repository_for(request), principal, view)


@router.get('/{claim_id}', response_model=WorkbenchClaimDetail)
def read_workbench_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> WorkbenchClaimDetail:
    return get_workbench_claim_detail(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/staff-actions',
    response_model=StaffActionMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_action(
    claim_id: str,
    payload: CreateStaffActionRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> StaffActionMutationResponse:
    return create_staff_action(
        repository_for(request), principal, claim_id, payload, idempotency_key, if_match
    )


@router.patch('/{claim_id}/staff-actions/{action_id}', response_model=StaffActionMutationResponse)
def update_action(
    claim_id: str,
    action_id: str,
    payload: UpdateStaffActionRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> StaffActionMutationResponse:
    return update_staff_action(
        repository_for(request), principal, claim_id, action_id, payload, idempotency_key, if_match
    )


@router.post(
    '/{claim_id}/signals/{signal_id}/decisions',
    response_model=SignalDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_signal_decision(
    claim_id: str,
    signal_id: str,
    payload: SignalDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> SignalDecisionResponse:
    return decide_signal(
        repository_for(request), principal, claim_id, signal_id, payload, idempotency_key, if_match
    )


@router.post('/{claim_id}/handoffs/{handoff_id}/accept', response_model=HandoffMutationResponse)
def accept_claim_handoff(
    claim_id: str,
    handoff_id: str,
    payload: AcceptHandoffRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> HandoffMutationResponse:
    return accept_handoff(
        repository_for(request),
        principal,
        claim_id,
        handoff_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.post('/{claim_id}/handoffs/{handoff_id}/resolve', response_model=HandoffMutationResponse)
def resolve_claim_handoff(
    claim_id: str,
    handoff_id: str,
    payload: ResolveHandoffRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> HandoffMutationResponse:
    return resolve_handoff(
        repository_for(request),
        principal,
        claim_id,
        handoff_id,
        payload,
        idempotency_key,
        if_match,
    )
