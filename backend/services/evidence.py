from backend.adapters.evidence_storage import (
    EvidenceStorage,
    EvidenceStorageUnavailable,
    EvidenceUploadNotFound,
    EvidenceUploadTooLarge,
    UnsupportedEvidenceMediaType,
)
from backend.core.auth import Principal, require_durable_claimant
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.branch_registry import validate_registered_field_value
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    ClaimantEvidence,
    CompleteEvidenceProcessingRequest,
    CompleteEvidenceUploadRequest,
    EvidenceCompleteResponse,
    EvidenceFactDecisionRequest,
    EvidenceFactDecisionResponse,
    EvidenceFileStatus,
    EvidenceListResponse,
    EvidenceMutationResponse,
    EvidenceProcessingResponse,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    EvidenceUploadResponse,
    EvidenceWaitType,
    FormSource,
    FormStatus,
    NeededFor,
    RegisterEvidenceRequest,
    RequestEvidenceUploadRequest,
    ResponsibleParty,
    StructuredFormField,
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
from backend.services.branching import build_applied_branch_evaluation
from backend.services.evidence_visibility import claimant_visible_evidence
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

# Conditions that say something about content that exists. Registration records material
# that has not arrived, so none of these can be declared there: they can only follow an
# upload, or a comparison against material already held.
ARRIVED_MATERIAL_STATUSES = frozenset(
    {
        EvidenceStatus.INVALID,
        EvidenceStatus.SUPERSEDED,
        EvidenceStatus.EXPIRED,
    }
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


def _transition_entry(
    *,
    field_code: str | None,
    from_state: str,
    to_state: str,
    source: str,
    at: str,
    actor_type: str,
    actor_id: str,
    proposed_at: str | None = None,
) -> dict[str, str | None]:
    return {
        'field_code': field_code,
        'from': from_state,
        'to': to_state,
        'source': source,
        'at': at,
        'actor_type': actor_type,
        'actor_id': actor_id,
        'proposed_at': proposed_at,
    }


def _with_transition(
    provenance: dict[str, object],
    transition: dict[str, str | None],
) -> dict[str, object]:
    existing = provenance.get('transition_history', [])
    history = existing if isinstance(existing, list) else []
    return {**provenance, 'transition_history': [*history, transition]}


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
            branch_evaluation=build_applied_branch_evaluation(
                claim,
                repository=repository,
                recomputation_reason='evidence_changed',
                trigger_source_refs=[evidence.evidence_id],
            ),
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
    evidence = claimant_visible_evidence(repository.list_evidence(claim_id, principal.subject))
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
    require_durable_claimant(principal)
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
    if payload.status in ARRIVED_MATERIAL_STATUSES:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='This condition describes material that has arrived, and registration '
            'records material that has not.',
            details=[
                ErrorDetail(
                    field='status',
                    reason=f'{payload.status.value} can only follow an upload, because it '
                    'says something about content that exists.',
                )
            ],
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
    require_durable_claimant(principal)
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
        restored = EvidenceUploadResponse.model_validate(existing.response_payload)
        if restored.upload.expires_at > now_utc():
            return restored
        evidence = repository.get_evidence(
            claim_id,
            restored.evidence_id,
            principal.subject,
        )
        if (
            evidence is None
            or evidence.file_status is not EvidenceFileStatus.AWAITING_UPLOAD
            or evidence.media_type is None
            or evidence.size_bytes is None
        ):
            return restored
        try:
            refreshed = storage.create_upload_target(
                claim_id=claim_id,
                evidence_id=restored.evidence_id,
                media_type=evidence.media_type,
                size_bytes=evidence.size_bytes,
            )
        except EvidenceStorageUnavailable as error:
            raise ApiError(
                status_code=503,
                code='DEPENDENCY_UNAVAILABLE',
                message='Evidence storage is temporarily unavailable. The claim is unchanged.',
                retryable=True,
            ) from error
        return restored.model_copy(
            update={
                'upload': UploadTarget(
                    method='PUT',
                    url=refreshed.url,
                    headers=refreshed.headers,
                    expires_at=refreshed.expires_at,
                )
            }
        )

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
    except EvidenceStorageUnavailable as error:
        # An outage is not a rejected file. It is reported as a retryable
        # dependency failure so the claimant is told to try again rather than
        # told their evidence was refused.
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable. The claim is unchanged.',
            retryable=True,
        ) from error
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
        # The upload has been registered and has not finished. That is a fact about
        # the file, not about the material, so the business condition is that the
        # claim is still waiting and the file status carries the rest.
        status=EvidenceStatus.PENDING,
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
    require_durable_claimant(principal)
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
    except EvidenceStorageUnavailable as error:
        # An outage is not a rejected file. It is reported as a retryable
        # dependency failure so the claimant is told to try again rather than
        # told their evidence was refused.
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable. The claim is unchanged.',
            retryable=True,
        ) from error
    except EvidenceUploadNotFound as error:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The stored upload could not be matched to this evidence item.',
        ) from error

    timestamp = now_utc()
    provenance = _with_transition(
        {
            **evidence.provenance,
            'storage_key': stored.storage_key,
            'upload_checksum': stored.checksum,
            'processing_state': 'queued',
        },
        _transition_entry(
            field_code=None,
            from_state=EvidenceFileStatus.AWAITING_UPLOAD.value,
            to_state=EvidenceFileStatus.PROCESSING.value,
            source=evidence.source.value,
            at=timestamp.isoformat(),
            actor_type=ActorType.SYSTEM.value,
            actor_id=stored.source_id,
        ),
    )
    completed = evidence.model_copy(
        update={
            'status': EvidenceStatus.RECEIVED,
            'file_status': EvidenceFileStatus.PROCESSING,
            'wait_type': EvidenceWaitType.INTERNAL,
            'responsible_party': ResponsibleParty.SYSTEM,
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


def complete_evidence_processing(
    repository: PersistenceRepository,
    claim_id: str,
    evidence_id: str,
    payload: CompleteEvidenceProcessingRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> EvidenceProcessingResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()
    existing = repository.find_idempotency(claim.customer_id, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with different processing results.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent processing result could not be restored.',
                retryable=True,
            )
        return EvidenceProcessingResponse.model_validate(existing.response_payload)

    _validate_revision(claim, expected_revision)
    evidence = repository.get_evidence(claim_id, evidence_id, claim.customer_id)
    if evidence is None:
        raise _evidence_not_found()
    if payload.outcome == 'retry':
        if evidence.file_status is not EvidenceFileStatus.FAILED:
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message='Only failed evidence can be retried.',
            )
        timestamp = now_utc()
        retried = evidence.model_copy(
            update={
                'file_status': EvidenceFileStatus.PROCESSING,
                'context_summary': 'Northwind is processing the retried evidence upload.',
                'provenance': _with_transition(
                    {**evidence.provenance, 'processing_state': 'queued'},
                    _transition_entry(
                        field_code=None,
                        from_state=EvidenceFileStatus.FAILED.value,
                        to_state=EvidenceFileStatus.PROCESSING.value,
                        source=evidence.source.value,
                        at=timestamp.isoformat(),
                        actor_type=ActorType.SYSTEM.value,
                        actor_id='mock_evidence_processor',
                    ),
                ),
                'updated_at': timestamp,
            }
        )
        updated_claim = _updated_claim(claim, _records_with(repository, claim, retried))
        response = EvidenceProcessingResponse(
            evidence_id=evidence_id,
            revision=updated_claim.revision,
            file_status=retried.file_status,
            proposed_fields={},
        )
        _persist(
            repository,
            updated_claim,
            expected_revision,
            retried,
            IdempotencyRecord(
                actor_id=claim.customer_id,
                route=route,
                key=key,
                request_fingerprint=fingerprint,
                claim_id=claim_id,
                session_id=claim.active_session_id or '',
                response_payload=response.model_dump(mode='json'),
            ),
        )
        return response

    if evidence.file_status is not EvidenceFileStatus.PROCESSING:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='This evidence item is not awaiting processing completion.',
        )
    if evidence.media_type is None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The evidence media type is unavailable.',
        )

    if payload.outcome == 'failed':
        timestamp = now_utc()
        failed = evidence.model_copy(
            update={
                'file_status': EvidenceFileStatus.FAILED,
                'context_summary': 'Northwind could not process this evidence upload.',
                'provenance': _with_transition(
                    {**evidence.provenance, 'processing_state': 'failed'},
                    _transition_entry(
                        field_code=None,
                        from_state=EvidenceFileStatus.PROCESSING.value,
                        to_state=EvidenceFileStatus.FAILED.value,
                        source=evidence.source.value,
                        at=timestamp.isoformat(),
                        actor_type=ActorType.SYSTEM.value,
                        actor_id='mock_evidence_processor',
                    ),
                ),
                'updated_at': timestamp,
            }
        )
        updated_claim = _updated_claim(claim, _records_with(repository, claim, failed))
        response = EvidenceProcessingResponse(
            evidence_id=evidence_id,
            revision=updated_claim.revision,
            file_status=failed.file_status,
            proposed_fields={},
        )
        _persist(
            repository,
            updated_claim,
            expected_revision,
            failed,
            IdempotencyRecord(
                actor_id=claim.customer_id,
                route=route,
                key=key,
                request_fingerprint=fingerprint,
                claim_id=claim_id,
                session_id=claim.active_session_id or '',
                response_payload=response.model_dump(mode='json'),
            ),
        )
        return response

    field_codes = [fact.field_code for fact in payload.facts]
    invalid_codes = [code for code in field_codes if code not in REGISTERED_FIELD_CODES]
    if len(set(field_codes)) != len(field_codes) or invalid_codes:
        details = [
            ErrorDetail(field=code, reason='The extracted field code is not registered.')
            for code in invalid_codes
        ]
        if len(set(field_codes)) != len(field_codes):
            details.append(ErrorDetail(field='facts', reason='Field codes must not be repeated.'))
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The processing result contains invalid extracted facts.',
            details=details,
        )
    invalid_values: list[ErrorDetail] = []
    for fact in payload.facts:
        try:
            validate_registered_field_value(fact.field_code, fact.value)
        except ValueError as error:
            invalid_values.append(ErrorDetail(field=fact.field_code, reason=str(error)))
    if invalid_values:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The processing result contains invalid extracted fact values.',
            details=invalid_values,
        )
    # Extraction may only fill a field that the shared form does not hold yet.
    # Writing into an occupied field would replace its value, source, and
    # source references through the merge below, so a claimant proposal, a
    # disputed value, or a recorded gap would silently disappear instead of
    # remaining traceable. A confirmed value is protected for the same reason.
    occupied_fields = [code for code in field_codes if code in claim.form]
    if occupied_fields:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Extracted facts cannot overwrite existing claim information.',
            details=[
                ErrorDetail(
                    field=code,
                    reason=(
                        f'The existing field is {claim.form[code].status.value} '
                        'and must be resolved before extraction can fill it.'
                    ),
                )
                for code in occupied_fields
            ],
        )

    timestamp = now_utc()
    form_source = (
        FormSource.IMAGE if evidence.media_type.startswith('image/') else FormSource.DOCUMENT
    )
    proposed_fields = {
        fact.field_code: StructuredFormField(
            value=fact.value,
            source=form_source,
            source_refs=[evidence_id],
            status=FormStatus.PROPOSED,
            needed_for=NeededFor.CURRENT_ACTION,
            confidence=fact.confidence,
            updated_at=timestamp,
            updated_by=ActorReference(
                actor_type=ActorType.SYSTEM,
                actor_id='mock_evidence_processor',
            ),
        )
        for fact in payload.facts
    }
    provenance: dict[str, object] = {
        **evidence.provenance,
        'processing_state': 'completed',
        'extraction_state': 'proposed',
        'fact_decisions': {code: 'proposed' for code in field_codes},
    }
    provenance = _with_transition(
        provenance,
        _transition_entry(
            field_code=None,
            from_state=EvidenceFileStatus.PROCESSING.value,
            to_state=EvidenceFileStatus.READY.value,
            source=evidence.source.value,
            at=timestamp.isoformat(),
            actor_type=ActorType.SYSTEM.value,
            actor_id='mock_evidence_processor',
        ),
    )
    for field_code in field_codes:
        provenance = _with_transition(
            provenance,
            _transition_entry(
                field_code=field_code,
                from_state=EvidenceFileStatus.PROCESSING.value,
                to_state=FormStatus.PROPOSED.value,
                source=form_source.value,
                at=timestamp.isoformat(),
                actor_type=ActorType.SYSTEM.value,
                actor_id='mock_evidence_processor',
            ),
        )
    processed = evidence.model_copy(
        update={
            'file_status': EvidenceFileStatus.READY,
            'provenance': provenance,
            'updated_at': timestamp,
        }
    )
    updated_claim = _updated_claim(claim, _records_with(repository, claim, processed)).model_copy(
        update={'form': {**claim.form, **proposed_fields}}
    )
    response = EvidenceProcessingResponse(
        evidence_id=evidence_id,
        revision=updated_claim.revision,
        file_status=processed.file_status,
        proposed_fields=proposed_fields,
    )
    _persist(
        repository,
        updated_claim,
        expected_revision,
        processed,
        IdempotencyRecord(
            actor_id=claim.customer_id,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        ),
    )
    return response


def decide_evidence_facts(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    evidence_id: str,
    payload: EvidenceFactDecisionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> EvidenceFactDecisionResponse:
    require_durable_claimant(principal)
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/fact-decisions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different fact decision.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent fact decision could not be restored.',
                retryable=True,
            )
        return EvidenceFactDecisionResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    _validate_revision(claim, expected_revision)
    evidence = repository.get_evidence(claim_id, evidence_id, principal.subject)
    if evidence is None:
        raise _evidence_not_found()
    if evidence.file_status is not EvidenceFileStatus.READY:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Evidence facts cannot be decided before processing is complete.',
        )

    duplicate_codes = len(set(payload.field_codes)) != len(payload.field_codes)
    unavailable_codes = [
        field_code
        for field_code in payload.field_codes
        if field_code not in claim.form
        or claim.form[field_code].status is not FormStatus.PROPOSED
        or evidence_id not in claim.form[field_code].source_refs
        or claim.form[field_code].source not in {FormSource.IMAGE, FormSource.DOCUMENT}
    ]
    if duplicate_codes or unavailable_codes:
        details = [
            ErrorDetail(
                field=field_code,
                reason='The field is not a proposed fact from this evidence item.',
            )
            for field_code in unavailable_codes
        ]
        if duplicate_codes:
            details.append(
                ErrorDetail(field='field_codes', reason='Field codes must not be repeated.')
            )
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more evidence facts cannot be decided.',
            details=details,
        )

    timestamp = now_utc()
    form_status = FormStatus.CONFIRMED if payload.decision == 'confirmed' else FormStatus.DISPUTED
    updated_fields = {
        field_code: claim.form[field_code].model_copy(
            update={
                'status': form_status,
                'confidence': 1.0
                if payload.decision == 'confirmed'
                else claim.form[field_code].confidence,
                'updated_at': timestamp,
                'updated_by': ActorReference(
                    actor_type=ActorType.CLAIMANT,
                    actor_id=principal.subject,
                ),
            }
        )
        for field_code in payload.field_codes
    }
    stored_decisions = evidence.provenance.get('fact_decisions', {})
    decisions = dict(stored_decisions) if isinstance(stored_decisions, dict) else {}
    provenance: dict[str, object] = dict(evidence.provenance)
    for field_code in payload.field_codes:
        original = claim.form[field_code]
        decisions[field_code] = payload.decision
        provenance = _with_transition(
            provenance,
            _transition_entry(
                field_code=field_code,
                from_state=FormStatus.PROPOSED.value,
                to_state=payload.decision,
                source=original.source.value,
                at=timestamp.isoformat(),
                actor_type=ActorType.CLAIMANT.value,
                actor_id=principal.subject,
                proposed_at=original.updated_at.isoformat(),
            ),
        )
    provenance['fact_decisions'] = decisions
    decision_states = set(decisions.values())
    if 'proposed' in decision_states:
        provenance['extraction_state'] = 'proposed'
    elif decision_states == {'confirmed'}:
        provenance['extraction_state'] = 'confirmed'
    elif decision_states == {'rejected'}:
        provenance['extraction_state'] = 'rejected'
    else:
        provenance['extraction_state'] = 'reviewed'

    decided = evidence.model_copy(update={'provenance': provenance, 'updated_at': timestamp})
    updated_claim = _updated_claim(claim, _records_with(repository, claim, decided)).model_copy(
        update={'form': {**claim.form, **updated_fields}}
    )
    response = EvidenceFactDecisionResponse(
        evidence_id=evidence_id,
        revision=updated_claim.revision,
        decision=payload.decision,
        updated_fields=updated_fields,
    )
    _persist(
        repository,
        updated_claim,
        expected_revision,
        decided,
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
