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


def _upload_size_error(*, exceeds_global_limit: bool) -> ApiError:
    if exceeds_global_limit:
        return ApiError(
            status_code=413,
            code='UPLOAD_TOO_LARGE',
            message='The uploaded file exceeds the maximum permitted size.',
        )
    return ApiError(
        status_code=422,
        code='VALIDATION_ERROR',
        message='The uploaded file size does not match the registered evidence.',
    )


async def _read_bounded_upload(
    request: Request,
    *,
    expected_size_bytes: int,
    max_size_bytes: int,
) -> bytes:
    """Read only a registered, globally bounded fixture upload into memory."""

    content_length = request.headers.get('content-length')
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = -1
        if declared_length > max_size_bytes:
            raise _upload_size_error(exceeds_global_limit=True)
        if declared_length > expected_size_bytes:
            raise _upload_size_error(exceeds_global_limit=False)

    content = bytearray()
    async for chunk in request.stream():
        next_size = len(content) + len(chunk)
        if next_size > max_size_bytes:
            raise _upload_size_error(exceeds_global_limit=True)
        if next_size > expected_size_bytes:
            raise _upload_size_error(exceeds_global_limit=False)
        content.extend(chunk)

    if len(content) != expected_size_bytes:
        raise _upload_size_error(exceeds_global_limit=False)
    return bytes(content)


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
    storage = storage_for(request)
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
    if not storage.supports_content_proxy:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='This upload target does not accept content through the application.',
        )
    if request.headers.get('content-type', '').split(';', 1)[0] != evidence.media_type:
        raise ApiError(
            status_code=415,
            code='UNSUPPORTED_MEDIA_TYPE',
            message='The uploaded content type does not match the registered evidence.',
        )
    if evidence.size_bytes is None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='This evidence item has no registered upload size.',
        )
    try:
        content = await _read_bounded_upload(
            request,
            expected_size_bytes=evidence.size_bytes,
            max_size_bytes=storage.max_size_bytes,
        )
        storage.put_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            content=content,
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
