import base64
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from backend.adapters.evidence_storage import EvidenceStorage, EvidenceStorageUnavailable
from backend.core.auth import Principal, require_staff
from backend.core.errors import ApiError
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
from backend.services.review_writeback import (
    decide_review_signal,
    get_review_connected_workbench_detail,
)
from backend.services.staff_actions import (
    accept_handoff,
    create_staff_action,
    resolve_handoff,
    send_staff_message,
    update_staff_action,
)
from backend.services.workbench import list_workbench_claims

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


def storage_for(request: Request) -> EvidenceStorage:
    return cast(EvidenceStorage, request.app.state.evidence_storage)


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
    return get_review_connected_workbench_detail(repository_for(request), principal, claim_id)


@router.get('/{claim_id}/evidence/{evidence_id}/content')
def read_workbench_evidence_content(
    claim_id: str,
    evidence_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> Response:
    repository = repository_for(request)
    # Reuse the Workbench permission boundary before reading any file content.
    detail = get_review_connected_workbench_detail(repository, principal, claim_id)
    evidence = next((item for item in detail.evidence if item.evidence_id == evidence_id), None)
    if evidence is None or evidence.media_type is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The evidence file was not found.'
        )
    try:
        content = storage_for(request).read_upload(claim_id=claim_id, evidence_id=evidence_id)
    except EvidenceStorageUnavailable as error:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable.',
            retryable=True,
        ) from error
    if content is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The evidence file is not available to view.',
        )
    filename = (evidence.original_filename or 'evidence').replace('"', '')
    return Response(
        content=content,
        media_type=evidence.media_type,
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


@router.get('/{claim_id}/evidence/{evidence_id}/content-data')
def read_workbench_evidence_content_data(
    claim_id: str,
    evidence_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> dict[str, str]:
    repository = repository_for(request)
    detail = get_review_connected_workbench_detail(repository, principal, claim_id)
    evidence = next((item for item in detail.evidence if item.evidence_id == evidence_id), None)
    if evidence is None or evidence.media_type is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The evidence file was not found.'
        )
    try:
        content = storage_for(request).read_upload(claim_id=claim_id, evidence_id=evidence_id)
    except EvidenceStorageUnavailable as error:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable.',
            retryable=True,
        ) from error
    if content is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The evidence file is not available to view.',
        )
    return {
        'filename': evidence.original_filename or 'evidence',
        'media_type': evidence.media_type,
        'base64_data': base64.b64encode(content).decode('ascii'),
    }


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
    return decide_review_signal(
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
