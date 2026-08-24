from typing import cast

from fastapi import APIRouter, Depends, Header, Request, Response, status

from backend.adapters.evidence_storage import (
    EvidenceStorage,
    EvidenceStorageUnavailable,
    EvidenceUploadNotFound,
    EvidenceUploadSizeMismatch,
)
from backend.core.auth import Principal, require_claimant
from backend.core.errors import ApiError
from backend.domain.models import (
    CompleteEvidenceUploadRequest,
    EvidenceCompleteResponse,
    EvidenceFactDecisionRequest,
    EvidenceFactDecisionResponse,
    EvidenceFileStatus,
    EvidenceListResponse,
    EvidenceMutationResponse,
    EvidenceUploadResponse,
    RegisterEvidenceRequest,
    RequestEvidenceUploadRequest,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence import (
    complete_upload,
    decide_evidence_facts,
    list_evidence,
    register_evidence,
    request_upload,
)

router = APIRouter(prefix='/api/v1/claims', tags=['claimant-evidence'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def storage_for(request: Request) -> EvidenceStorage:
    return cast(EvidenceStorage, request.app.state.evidence_storage)


@router.get('/{claim_id}/evidence', response_model=EvidenceListResponse)
def read_evidence(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> EvidenceListResponse:
    return list_evidence(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/evidence',
    response_model=EvidenceMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence(
    claim_id: str,
    payload: RegisterEvidenceRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> EvidenceMutationResponse:
    return register_evidence(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.post(
    '/{claim_id}/evidence/uploads',
    response_model=EvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence_upload(
    claim_id: str,
    payload: RequestEvidenceUploadRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> EvidenceUploadResponse:
    return request_upload(
        repository_for(request),
        storage_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.put('/{claim_id}/evidence/{evidence_id}/content', status_code=status.HTTP_204_NO_CONTENT)
async def upload_evidence_content(
    claim_id: str,
    evidence_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> Response:
    repository = repository_for(request)
    evidence = repository.get_evidence(claim_id, evidence_id, principal.subject)
    if evidence is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The evidence was not found.'
        )
    if evidence.file_status is not EvidenceFileStatus.AWAITING_UPLOAD:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='This evidence item is not awaiting an upload.',
        )
    if request.headers.get('content-type', '').split(';', 1)[0] != evidence.media_type:
        raise ApiError(
            status_code=415,
            code='UNSUPPORTED_MEDIA_TYPE',
            message='The uploaded content type does not match the registered evidence.',
        )
    try:
        storage_for(request).put_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            content=await request.body(),
        )
    except EvidenceUploadSizeMismatch as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The uploaded file size does not match the registered evidence.',
        ) from error
    except EvidenceUploadNotFound as error:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The evidence upload target is no longer available.',
        ) from error
    except EvidenceStorageUnavailable as error:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable.',
            retryable=True,
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/{claim_id}/evidence/{evidence_id}/complete',
    response_model=EvidenceCompleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def finish_evidence_upload(
    claim_id: str,
    evidence_id: str,
    payload: CompleteEvidenceUploadRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> EvidenceCompleteResponse:
    return complete_upload(
        repository_for(request),
        storage_for(request),
        principal,
        claim_id,
        evidence_id,
        payload,
        idempotency_key,
        if_match,
    )


@router.post(
    '/{claim_id}/evidence/{evidence_id}/fact-decisions',
    response_model=EvidenceFactDecisionResponse,
)
def decide_extracted_facts(
    claim_id: str,
    evidence_id: str,
    payload: EvidenceFactDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> EvidenceFactDecisionResponse:
    return decide_evidence_facts(
        repository_for(request),
        principal,
        claim_id,
        evidence_id,
        payload,
        idempotency_key,
        if_match,
    )
