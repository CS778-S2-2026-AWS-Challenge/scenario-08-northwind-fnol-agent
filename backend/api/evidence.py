from typing import cast

from fastapi import APIRouter, Depends, Header, Request, status

from backend.adapters.evidence_storage import EvidenceStorage
from backend.core.auth import Principal, require_claimant
from backend.domain.models import (
    CompleteEvidenceUploadRequest,
    EvidenceCompleteResponse,
    EvidenceFactDecisionRequest,
    EvidenceFactDecisionResponse,
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
