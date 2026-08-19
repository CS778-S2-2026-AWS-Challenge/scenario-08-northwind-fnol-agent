from backend.adapters.evidence_storage import (
    EvidenceStorage,
    EvidenceUploadNotFound,
    EvidenceUploadTooLarge,
    UnsupportedEvidenceMediaType,
)
from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.ids import new_id
from backend.domain.models import (
    ClaimantEvidence,
    CompleteEvidenceUploadRequest,
    EvidenceCompleteResponse,
    EvidenceFileStatus,
    EvidenceListResponse,
    EvidenceMutationResponse,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    EvidenceUploadResponse,
    EvidenceWaitType,
    RegisterEvidenceRequest,
    RequestEvidenceUploadRequest,
    ResponsibleParty,
    UploadConstraints,
    UploadTarget,
    WorkingClaim,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def _evidence_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The evidence item was not found.',
    )


def _claimant_evidence(evidence: EvidenceRecord) -> ClaimantEvidence:
    return ClaimantEvidence(
        evidence_id=evidence.evidence_id,
        claim_id=evidence.claim_id,
        kind=evidence.kind,
        status=evidence.status,
        file_status=evidence.file_status,
        original_filename=evidence.original_filename,
        media_type=evidence.media_type,
        size_bytes=evidence.size_bytes,
        source=evidence.source,
        related_fields=evidence.related_fields,
        needed_for=evidence.needed_for,
        claimant_note=evidence.claimant_note,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def _updated_claim(
    claim: WorkingClaim,
    records: list[EvidenceRecord],
) -> WorkingClaim:
    timestamp = max(record.updated_at for record in records)
    return claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': timestamp,
            'evidence_summary': evidence_summary_for(records),
            'claim_state': claim.claim_state.model_copy(
                update={'evidence': evidence_state_for(records)}
            ),
        }
    )


def _records_with(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    evidence: EvidenceRecord,
) -> list[EvidenceRecord]:
    existing = repository.list_evidence(claim.claim_id, claim.customer_id)
    return [record for record in existing if record.evidence_id != evidence.evidence_id] + [
        evidence
    ]


def _validate_revision(claim: WorkingClaim, expected_revision: int) -> None:
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )


def _persist(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    evidence: EvidenceRecord,
    idempotency: IdempotencyRecord,
) -> None:
    try:
        repository.save_evidence_mutation(
            claim,
            expected_revision,
            evidence,
            idempotency,
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The evidence request was already accepted with different retry data.',
        ) from conflict


def list_evidence(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> EvidenceListResponse:
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    evidence = repository.list_evidence(claim_id, principal.subject)
    return EvidenceListResponse(
        claim_id=claim_id,
        revision=claim.revision,
        items=[_claimant_evidence(record) for record in evidence],
        customer_next_step=claim.customer_next_step,
    )


def register_evidence(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: RegisterEvidenceRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> EvidenceMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/evidence'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent evidence result could not be restored.',
                retryable=True,
            )
        return EvidenceMutationResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    _validate_revision(claim, expected_revision)
    if payload.status is EvidenceStatus.RECEIVED:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='Received evidence must be registered through the upload flow.',
            details=[ErrorDetail(field='status', reason='Use an upload for received evidence.')],
        )

    timestamp = now_utc()
    evidence = EvidenceRecord(
        evidence_id=new_id('evd'),
        claim_id=claim_id,
        kind=payload.kind,
        status=payload.status,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        related_fields=payload.related_fields,
        needed_for=payload.needed_for,
        claimant_note=payload.claimant_note,
        wait_type='claimant',
        responsible_party='claimant',
        context_summary=(
            f'Needed for: {", ".join(payload.needed_for)}' if payload.needed_for else None
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    updated_claim = _updated_claim(claim, _records_with(repository, claim, evidence))
    response = EvidenceMutationResponse(
        evidence=_claimant_evidence(evidence),
        revision=updated_claim.revision,
        customer_next_step=updated_claim.customer_next_step,
    )
    _persist(
        repository,
        updated_claim,
        expected_revision,
        evidence,
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        ),
    )
    return response


def request_upload(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    principal: Principal,
    claim_id: str,
    payload: RequestEvidenceUploadRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> EvidenceUploadResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/evidence/uploads'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent upload result could not be restored.',
                retryable=True,
            )
        return EvidenceUploadResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    _validate_revision(claim, expected_revision)
    evidence_id = new_id('evd')
    try:
        target = storage.create_upload_target(
            claim_id=claim_id,
            evidence_id=evidence_id,
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
        )
    except UnsupportedEvidenceMediaType as error:
        raise ApiError(
            status_code=415,
            code='UNSUPPORTED_MEDIA_TYPE',
            message='The evidence media type is not supported.',
            details=[ErrorDetail(field='media_type', reason=str(error))],
        ) from error
    except EvidenceUploadTooLarge as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The evidence file exceeds the upload size limit.',
            details=[ErrorDetail(field='size_bytes', reason=str(error))],
        ) from error

    timestamp = now_utc()
    evidence = EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind=payload.kind,
        status=EvidenceStatus.INCOMPLETE,
        file_status=EvidenceFileStatus.AWAITING_UPLOAD,
        original_filename=payload.original_filename,
        media_type=payload.media_type,
        size_bytes=payload.size_bytes,
        source=EvidenceSource.CLAIMANT,
        wait_type='claimant',
        responsible_party='claimant',
        context_summary='Waiting for the claimant to complete the evidence upload.',
        provenance={'storage_key': target.storage_key},
        created_at=timestamp,
        updated_at=timestamp,
    )
    updated_claim = _updated_claim(claim, _records_with(repository, claim, evidence))
    response = EvidenceUploadResponse(
        evidence_id=evidence_id,
        revision=updated_claim.revision,
        upload=UploadTarget(
            method='PUT',
            url=target.url,
            headers=target.headers,
            expires_at=target.expires_at,
        ),
        constraints=UploadConstraints(
            max_size_bytes=storage.max_size_bytes,
            allowed_media_types=list(storage.allowed_media_types),
        ),
        customer_next_step=updated_claim.customer_next_step,
    )
    _persist(
        repository,
        updated_claim,
        expected_revision,
        evidence,
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        ),
    )
    return response


def complete_upload(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    principal: Principal,
    claim_id: str,
    evidence_id: str,
    payload: CompleteEvidenceUploadRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> EvidenceCompleteResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent completion result could not be restored.',
                retryable=True,
            )
        return EvidenceCompleteResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    _validate_revision(claim, expected_revision)
    evidence = repository.get_evidence(claim_id, evidence_id, principal.subject)
    if evidence is None:
        raise _evidence_not_found()
    if evidence.file_status is not EvidenceFileStatus.AWAITING_UPLOAD:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='This evidence item is not awaiting an upload.',
        )
    if evidence.media_type is None or evidence.size_bytes is None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The upload metadata is incomplete.',
        )
    try:
        stored = storage.complete_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            checksum=payload.upload_checksum,
            media_type=evidence.media_type,
            size_bytes=evidence.size_bytes,
        )
    except EvidenceUploadNotFound as error:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The stored upload could not be matched to this evidence item.',
        ) from error

    timestamp = now_utc()
    provenance = {
        **evidence.provenance,
        'storage_key': stored.storage_key,
        'upload_checksum': stored.checksum,
        'processing_state': 'queued',
    }
    completed = evidence.model_copy(
        update={
            'status': EvidenceStatus.RECEIVED,
            'file_status': EvidenceFileStatus.PROCESSING,
            'wait_type': EvidenceWaitType.INTERNAL,
            'responsible_party': ResponsibleParty.NORTHWIND,
            'expected_by': None,
            'expected_timing': None,
            'context_summary': 'Northwind is processing the completed evidence upload.',
            'provenance': provenance,
            'updated_at': timestamp,
        }
    )
    updated_claim = _updated_claim(claim, _records_with(repository, claim, completed))
    response = EvidenceCompleteResponse(
        evidence=_claimant_evidence(completed),
        revision=updated_claim.revision,
        status_url=f'/api/v1/claims/{claim_id}/evidence',
        customer_next_step=updated_claim.customer_next_step,
    )
    _persist(
        repository,
        updated_claim,
        expected_revision,
        completed,
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        ),
    )
    return response
