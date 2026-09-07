import base64
import re
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from backend.adapters.evidence_storage import EvidenceStorage, EvidenceStorageUnavailable
from backend.core.auth import Principal, require_staff
from backend.core.errors import ApiError
from backend.domain.models import (
    AcceptHandoffRequest,
    CollaborationMutationResponse,
    CreateCoworkRequest,
    CreateStaffActionRequest,
    CreateStaffMessageRequest,
    CreateTransferRequest,
    DecideCollaborationRequest,
    HandoffMutationResponse,
    RequeueClaimRequest,
    ResolveHandoffRequest,
    SignalDecisionRequest,
    SignalDecisionResponse,
    StaffActionMutationResponse,
    StaffMessageResponse,
    UpdateStaffActionRequest,
    WorkflowState,
)
from backend.domain.workbench import (
    WorkbenchClaimDetail,
    WorkbenchClaimFilterMetadata,
    WorkbenchClaimListResponse,
    WorkbenchCollaborationRequestsResponse,
    WorkbenchConversationsResponse,
    WorkbenchCustomerUpdatesResponse,
    WorkbenchEventsResponse,
    WorkbenchEvidenceResponse,
    WorkbenchExternalRequestsResponse,
    WorkbenchFieldsResponse,
    WorkbenchHandoffsResponse,
    WorkbenchMessagesResponse,
    WorkbenchQueueView,
    WorkbenchRetrievalsResponse,
    WorkbenchSessionsResponse,
    WorkbenchSignalsResponse,
    WorkbenchWorkItemsResponse,
    WorkPriorityLevel,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.ownership import (
    create_cowork_request,
    create_transfer_request,
    decide_collaboration_request,
    requeue_claim,
)
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
from backend.services.workbench import (
    get_workbench_claim_filter_metadata,
    list_workbench_claims,
    list_workbench_collaboration_requests,
    list_workbench_conversations,
    list_workbench_customer_updates,
    list_workbench_events,
    list_workbench_evidence,
    list_workbench_external_requests,
    list_workbench_fields,
    list_workbench_handoffs,
    list_workbench_messages,
    list_workbench_retrievals,
    list_workbench_sessions,
    list_workbench_signals,
    list_workbench_work_items,
)

router = APIRouter(prefix='/api/v1/workbench/claims', tags=['workbench'])
conversation_router = APIRouter(prefix='/api/v1/workbench/conversations', tags=['workbench'])


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


@conversation_router.get('', response_model=WorkbenchConversationsResponse)
def read_workbench_conversations(
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchConversationsResponse:
    return list_workbench_conversations(repository_for(request), principal, limit, cursor)


def storage_for(request: Request) -> EvidenceStorage:
    return cast(EvidenceStorage, request.app.state.evidence_storage)


def _evidence_storage_key(
    repository: PersistenceRepository, claim_id: str, evidence_id: str
) -> str | None:
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        return None
    evidence = repository.get_evidence(claim_id, evidence_id, claim.customer_id)
    if evidence is None:
        return None
    value = evidence.provenance.get('storage_key')
    return value if isinstance(value, str) else None


def _safe_download_filename(value: str | None) -> str:
    filename = re.sub(r'[\x00-\x1f\x7f"\\]', '', value or 'evidence').strip()
    return filename or 'evidence'


@router.get('', response_model=WorkbenchClaimListResponse)
def read_workbench_claims(
    request: Request,
    principal: Principal = Depends(require_staff),
    view: WorkbenchQueueView | None = Query(default=None),
    workflow_state: WorkflowState | None = Query(default=None),
    priority: WorkPriorityLevel | None = Query(default=None),
    tag: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchClaimListResponse:
    return list_workbench_claims(
        repository_for(request),
        principal,
        view=view,
        workflow_state=workflow_state,
        priority=priority,
        tag=tag,
        search=search,
        limit=limit,
        cursor=cursor,
    )


@router.get('/filter-metadata', response_model=WorkbenchClaimFilterMetadata)
def read_workbench_claim_filter_metadata(
    principal: Principal = Depends(require_staff),
) -> WorkbenchClaimFilterMetadata:
    return get_workbench_claim_filter_metadata(principal)


@router.get('/{claim_id}', response_model=WorkbenchClaimDetail)
def read_workbench_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> WorkbenchClaimDetail:
    return get_review_connected_workbench_detail(repository_for(request), principal, claim_id)


@router.get('/{claim_id}/fields', response_model=WorkbenchFieldsResponse)
def read_workbench_fields(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchFieldsResponse:
    return list_workbench_fields(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/sessions', response_model=WorkbenchSessionsResponse)
def read_workbench_sessions(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchSessionsResponse:
    return list_workbench_sessions(repository_for(request), principal, claim_id, limit, cursor)


@router.get(
    '/{claim_id}/collaboration-requests',
    response_model=WorkbenchCollaborationRequestsResponse,
)
def read_workbench_collaboration_requests(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchCollaborationRequestsResponse:
    return list_workbench_collaboration_requests(
        repository_for(request), principal, claim_id, limit, cursor
    )


@router.get(
    '/{claim_id}/sessions/{session_id}/messages',
    response_model=WorkbenchMessagesResponse,
)
def read_workbench_messages(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchMessagesResponse:
    return list_workbench_messages(
        repository_for(request), principal, claim_id, session_id, limit, cursor
    )


@router.get('/{claim_id}/evidence', response_model=WorkbenchEvidenceResponse)
def read_workbench_evidence(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchEvidenceResponse:
    return list_workbench_evidence(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/retrievals', response_model=WorkbenchRetrievalsResponse)
def read_workbench_retrievals(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchRetrievalsResponse:
    return list_workbench_retrievals(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/signals', response_model=WorkbenchSignalsResponse)
def read_workbench_signals(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchSignalsResponse:
    return list_workbench_signals(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/handoffs', response_model=WorkbenchHandoffsResponse)
def read_workbench_handoffs(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchHandoffsResponse:
    return list_workbench_handoffs(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/work-items', response_model=WorkbenchWorkItemsResponse)
def read_workbench_work_items(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchWorkItemsResponse:
    return list_workbench_work_items(repository_for(request), principal, claim_id, limit, cursor)


@router.get('/{claim_id}/customer-updates', response_model=WorkbenchCustomerUpdatesResponse)
def read_workbench_customer_updates(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchCustomerUpdatesResponse:
    return list_workbench_customer_updates(
        repository_for(request), principal, claim_id, limit, cursor
    )


@router.get('/{claim_id}/external-requests', response_model=WorkbenchExternalRequestsResponse)
def read_workbench_external_requests(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchExternalRequestsResponse:
    return list_workbench_external_requests(
        repository_for(request), principal, claim_id, limit, cursor
    )


@router.get('/{claim_id}/events', response_model=WorkbenchEventsResponse)
def read_workbench_events(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> WorkbenchEventsResponse:
    return list_workbench_events(repository_for(request), principal, claim_id, limit, cursor)


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
    claim = repository.get_claim_internal(detail.claim_id)
    evidence = (
        repository.get_evidence(claim_id, evidence_id, claim.customer_id)
        if claim is not None
        else None
    )
    if evidence is None or evidence.media_type is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The evidence file was not found.'
        )
    try:
        content = storage_for(request).read_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            storage_key=_evidence_storage_key(repository, claim_id, evidence_id),
        )
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
    filename = _safe_download_filename(evidence.original_filename)
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
    claim = repository.get_claim_internal(detail.claim_id)
    evidence = (
        repository.get_evidence(claim_id, evidence_id, claim.customer_id)
        if claim is not None
        else None
    )
    if evidence is None or evidence.media_type is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The evidence file was not found.'
        )
    try:
        content = storage_for(request).read_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            storage_key=_evidence_storage_key(repository, claim_id, evidence_id),
        )
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


@router.post(
    '/{claim_id}/cowork-requests',
    response_model=CollaborationMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_cowork(
    claim_id: str,
    payload: CreateCoworkRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> CollaborationMutationResponse:
    return create_cowork_request(
        repository_for(request), principal, claim_id, payload, idempotency_key, if_match
    )


@router.post(
    '/{claim_id}/transfer-requests',
    response_model=CollaborationMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def request_transfer(
    claim_id: str,
    payload: CreateTransferRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> CollaborationMutationResponse:
    return create_transfer_request(
        repository_for(request), principal, claim_id, payload, idempotency_key, if_match
    )


@router.patch(
    '/{claim_id}/collaboration-requests/{request_id}',
    response_model=CollaborationMutationResponse,
)
def decide_collaboration(
    claim_id: str,
    request_id: str,
    payload: DecideCollaborationRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> CollaborationMutationResponse:
    return decide_collaboration_request(
        repository_for(request),
        principal,
        claim_id,
        request_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.post('/{claim_id}/requeue', response_model=CollaborationMutationResponse)
def return_claim_to_queue(
    claim_id: str,
    payload: RequeueClaimRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> CollaborationMutationResponse:
    return requeue_claim(
        repository_for(request), principal, claim_id, payload, idempotency_key, if_match
    )
