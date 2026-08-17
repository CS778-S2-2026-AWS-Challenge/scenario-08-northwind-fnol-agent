from datetime import datetime

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.intake import next_controlled_intake_step
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    ClaimantClaim,
    ClaimantHandoff,
    ClaimantSession,
    ClaimListItem,
    ClaimListResponse,
    ClaimState,
    CreateClaimRequest,
    CreateClaimResponse,
    CustomerNextStep,
    FormConfirmationRequest,
    FormConfirmationResponse,
    FormPatchRequest,
    FormPatchResponse,
    FormSource,
    FormStatus,
    NeededFor,
    PageInfo,
    ResponsibleParty,
    ResumePackage,
    SessionRecord,
    SessionStatus,
    StartSessionRequest,
    StructuredFormField,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import (
    ClaimRepository,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.handoffs import claimant_handoff
from backend.services.support import (
    decode_cursor,
    encode_cursor,
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


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def _claimant_claim(repository: PersistenceRepository, claim: WorkingClaim) -> ClaimantClaim:
    handoff: ClaimantHandoff | None = None
    if claim.active_session_id is not None:
        # Claimant receives only the public lifecycle state, never staff routing data.
        open_handoffs = [
            item
            for item in repository.list_handoffs(claim.claim_id, claim.customer_id)
            if item.status.value not in {'resolved', 'cancelled'} and item.support_need is not None
        ]
        if open_handoffs:
            active = open_handoffs[-1]
            handoff = claimant_handoff(active)
    return ClaimantClaim(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        form=claim.form,
        evidence_summary=claim.evidence_summary,
        external_claim=claim.external_claim,
        customer_next_step=claim.customer_next_step,
        handoff=handoff,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _claim_list_item(claim: WorkingClaim) -> ClaimListItem:
    return ClaimListItem(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        external_claim=claim.external_claim,
        customer_next_step=claim.customer_next_step,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
        can_resume=claim.customer_next_step.can_resume,
    )


def _claimant_session(session: SessionRecord, next_step: CustomerNextStep) -> ClaimantSession:
    return ClaimantSession(
        session_id=session.session_id,
        claim_id=session.claim_id,
        status=session.status,
        resume=ResumePackage(
            summary=session.summary,
            unresolved_questions=session.unresolved_questions,
            pending_items=session.pending_items,
            prior_commitments=session.prior_commitments,
            customer_next_step=next_step,
        ),
        started_at=session.started_at,
        last_active_at=session.last_active_at,
        closed_at=session.closed_at,
    )


def start_claim(
    repository: PersistenceRepository,
    principal: Principal,
    payload: CreateClaimRequest,
    idempotency_key: str | None,
) -> CreateClaimResponse:
    key = require_idempotency_key(idempotency_key)
    route = '/api/v1/claims'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        claim = repository.get_claim(existing.claim_id, principal.subject)
        session = repository.get_session(existing.claim_id, existing.session_id, principal.subject)
        if claim is None or session is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent result could not be restored.',
                retryable=True,
            )
        return CreateClaimResponse(
            claim=_claimant_claim(repository, claim),
            session=_claimant_session(session, claim.customer_next_step),
        )

    timestamp = now_utc()
    claim_id = new_id('clm')
    session_id = new_id('ses')
    next_step = CustomerNextStep(
        status='describe_incident',
        summary='Tell me what happened in your own words.',
        responsible_party=ResponsibleParty.CLAIMANT,
    )
    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=principal.subject,
        channel=payload.channel,
        locale=payload.locale,
        incident_type=payload.incident_type,
        claim_state=ClaimState(),
        active_session_id=session_id,
        customer_next_step=next_step,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=session_id,
        claim_id=claim_id,
        customer_id=principal.subject,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session_id,
        )
    )
    return CreateClaimResponse(
        claim=_claimant_claim(repository, claim),
        session=_claimant_session(session, next_step),
    )


def get_claim(
    repository: PersistenceRepository, principal: Principal, claim_id: str
) -> ClaimantClaim:
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    return _claimant_claim(repository, claim)


def list_claims(
    repository: ClaimRepository,
    principal: Principal,
    *,
    limit: int,
    cursor: str | None,
    workflow_state: WorkflowState | None,
    updated_after: datetime | None,
) -> ClaimListResponse:
    if updated_after is not None and updated_after.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The updated_after filter must include a timezone offset.',
            details=[
                ErrorDetail(
                    field='updated_after',
                    reason='Use an ISO 8601 timestamp with a timezone offset.',
                )
            ],
        )
    claims = repository.list_claims_for_customer(principal.subject)
    if workflow_state is not None:
        claims = [claim for claim in claims if claim.claim_state.workflow_state == workflow_state]
    if updated_after is not None:
        claims = [claim for claim in claims if claim.updated_at > updated_after]
    claims.sort(key=lambda claim: (claim.updated_at, claim.claim_id), reverse=True)

    offset = decode_cursor(cursor)
    page_claims = claims[offset : offset + limit]
    next_offset = offset + len(page_claims)
    next_cursor = encode_cursor(next_offset) if next_offset < len(claims) else None
    return ClaimListResponse(
        items=[_claim_list_item(claim) for claim in page_claims],
        page=PageInfo(next_cursor=next_cursor),
    )


def start_session(
    repository: ClaimRepository,
    principal: Principal,
    claim_id: str,
    payload: StartSessionRequest,
    idempotency_key: str | None,
) -> ClaimantSession:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/claims/{claim_id}/sessions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        claim = repository.get_claim(claim_id, principal.subject)
        session = repository.get_session(claim_id, existing.session_id, principal.subject)
        if claim is None or session is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent result could not be restored.',
                retryable=True,
            )
        return _claimant_session(session, claim.customer_next_step)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()

    active_session = repository.get_active_session(claim_id, principal.subject)
    if active_session is not None and active_session.status is SessionStatus.ACTIVE:
        session = active_session
    else:
        previous_sessions = repository.list_sessions_for_claim(
            claim_id,
            principal.subject,
        )
        resume_source = active_session
        if resume_source is None and previous_sessions:
            resume_source = max(
                previous_sessions,
                key=lambda item: (
                    item.last_active_at,
                    item.started_at,
                    item.session_id,
                ),
            )

        timestamp = now_utc()
        session = SessionRecord(
            session_id=new_id('ses'),
            claim_id=claim_id,
            customer_id=principal.subject,
            summary=resume_source.summary if resume_source is not None else None,
            unresolved_questions=(
                list(resume_source.unresolved_questions) if resume_source is not None else []
            ),
            pending_items=list(resume_source.pending_items) if resume_source is not None else [],
            prior_commitments=(
                list(resume_source.prior_commitments) if resume_source is not None else []
            ),
            context_revision=claim.revision,
            started_at=timestamp,
            last_active_at=timestamp,
        )
        updated_claim = claim.model_copy(
            update={
                'active_session_id': session.session_id,
                'revision': claim.revision + 1,
                'updated_at': timestamp,
            }
        )
        repository.save_claim(updated_claim, expected_revision=claim.revision)
        repository.save_session(session)
        claim = updated_claim

    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session.session_id,
        )
    )
    return _claimant_session(session, claim.customer_next_step)


def get_session(
    repository: ClaimRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
) -> ClaimantSession:
    claim = repository.get_claim(claim_id, principal.subject)
    session = repository.get_session(claim_id, session_id, principal.subject)
    if claim is None or session is None:
        raise _session_not_found()
    return _claimant_session(session, claim.customer_next_step)


def update_form(
    repository: ClaimRepository,
    principal: Principal,
    claim_id: str,
    payload: FormPatchRequest,
    if_match: str | None,
) -> FormPatchResponse:
    expected_revision = parse_if_match(if_match)
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )

    timestamp = now_utc()
    updated_fields: dict[str, StructuredFormField] = {}
    for update in payload.updates:
        if update.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The field code is not registered.',
                details=[
                    ErrorDetail(field='field_code', reason=f'Unknown field: {update.field_code}.')
                ],
            )
        existing = claim.form.get(update.field_code)
        if (
            existing is not None
            and existing.status.value == 'confirmed'
            and existing.value != update.value
            and update.correction_reason is None
        ):
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message='A confirmed field cannot be silently overwritten.',
                details=[
                    ErrorDetail(
                        field=update.field_code,
                        reason='Submit a correction through the validated form flow.',
                    )
                ],
            )
        updated_fields[update.field_code] = StructuredFormField(
            value=update.value,
            source=FormSource.CLAIMANT,
            status=update.status,
            needed_for=NeededFor.CURRENT_ACTION,
            updated_at=timestamp,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
        )

    updated_claim = claim.model_copy(
        update={
            'form': {**claim.form, **updated_fields},
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    try:
        repository.save_claim(updated_claim, expected_revision=expected_revision)
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    return FormPatchResponse(
        claim_id=claim_id,
        revision=updated_claim.revision,
        updated_fields=updated_fields,
        customer_next_step=updated_claim.customer_next_step,
    )


def confirm_form_fields(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: FormConfirmationRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> FormConfirmationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/form/confirmations'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing_idempotency = repository.find_idempotency(principal.subject, route, key)
    if existing_idempotency is not None:
        if existing_idempotency.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing_idempotency.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent confirmation result could not be restored.',
                retryable=True,
            )
        return FormConfirmationResponse.model_validate(existing_idempotency.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    duplicate_codes = len(set(payload.field_codes)) != len(payload.field_codes)
    unavailable_codes = [
        field_code
        for field_code in payload.field_codes
        if field_code not in claim.form
        or claim.form[field_code].status not in {FormStatus.PROPOSED, FormStatus.CONFIRMED}
    ]
    if duplicate_codes or unavailable_codes:
        details = [
            ErrorDetail(field=field_code, reason='The field does not exist or is not confirmable.')
            for field_code in unavailable_codes
        ]
        if duplicate_codes:
            details.append(
                ErrorDetail(field='field_codes', reason='Field codes must not be repeated.')
            )
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more fields cannot be confirmed.',
            details=details,
        )

    timestamp = now_utc()
    confirmed_fields = {
        field_code: claim.form[field_code].model_copy(
            update={
                'status': FormStatus.CONFIRMED,
                'confidence': 1.0,
                'updated_at': timestamp,
                'updated_by': ActorReference(
                    actor_type=ActorType.CLAIMANT,
                    actor_id=principal.subject,
                ),
            }
        )
        for field_code in payload.field_codes
    }
    incident_type = claim.incident_type
    confirmed_incident_type = confirmed_fields.get('incident.type')
    if confirmed_incident_type is not None and isinstance(confirmed_incident_type.value, str):
        incident_type = confirmed_incident_type.value.strip().lower()
    projected_claim = claim.model_copy(
        update={
            'form': {**claim.form, **confirmed_fields},
            'incident_type': incident_type,
        }
    )
    next_step = next_controlled_intake_step(projected_claim)
    updated_claim = claim.model_copy(
        update={
            'form': {**claim.form, **confirmed_fields},
            'incident_type': incident_type,
            'claim_state': claim.claim_state.model_copy(update={'next_action': AgentAction.ASK}),
            'customer_next_step': next_step,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    try:
        repository.save_claim(updated_claim, expected_revision=expected_revision)
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    response = FormConfirmationResponse(
        claim_id=claim_id,
        revision=updated_claim.revision,
        confirmed_fields=confirmed_fields,
        customer_next_step=next_step,
    )
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        )
    )
    return response
