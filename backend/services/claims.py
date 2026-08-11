import hashlib
import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import UTC, datetime

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    ClaimantClaim,
    ClaimantSession,
    ClaimListItem,
    ClaimListResponse,
    ClaimState,
    CreateClaimRequest,
    CreateClaimResponse,
    CustomerNextStep,
    EvidenceSummary,
    FormPatchRequest,
    FormPatchResponse,
    FormSource,
    NeededFor,
    PageInfo,
    ResponsibleParty,
    ResumePackage,
    SessionRecord,
    StartSessionRequest,
    StructuredFormField,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import ClaimRepository, IdempotencyRecord, RevisionConflict

IF_MATCH_PATTERN = re.compile(r'^"?(\d+)"?$')


def now_utc() -> datetime:
    return datetime.now(UTC)


def request_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def encode_cursor(offset: int) -> str:
    return urlsafe_b64encode(str(offset).encode()).decode().rstrip('=')


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        offset = int(urlsafe_b64decode(padded).decode())
    except (Base64Error, UnicodeDecodeError, ValueError) as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination cursor is invalid.',
            details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
        ) from error
    if offset < 0:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination cursor is invalid.',
            details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
        )
    return offset


def require_idempotency_key(key: str | None) -> str:
    if key is None or not key.strip():
        raise ApiError(
            status_code=400,
            code='VALIDATION_ERROR',
            message='Idempotency-Key is required for this operation.',
            details=[ErrorDetail(field='Idempotency-Key', reason='The header is required.')],
        )
    if len(key) > 200:
        raise ApiError(
            status_code=400,
            code='VALIDATION_ERROR',
            message='Idempotency-Key is too long.',
            details=[
                ErrorDetail(field='Idempotency-Key', reason='Maximum length is 200 characters.')
            ],
        )
    return key.strip()


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise ApiError(
            status_code=409,
            code='REVISION_REQUIRED',
            message='If-Match is required when changing an existing claim.',
        )
    match = IF_MATCH_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ApiError(
            status_code=409,
            code='REVISION_REQUIRED',
            message='If-Match must contain the expected numeric revision.',
        )
    return int(match.group(1))


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


def _claimant_claim(claim: WorkingClaim) -> ClaimantClaim:
    return ClaimantClaim(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        form=claim.form,
        evidence_summary=EvidenceSummary(),
        external_claim=claim.external_claim,
        customer_next_step=claim.customer_next_step,
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
    repository: ClaimRepository,
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
            claim=_claimant_claim(claim),
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
        claim=_claimant_claim(claim),
        session=_claimant_session(session, next_step),
    )


def get_claim(repository: ClaimRepository, principal: Principal, claim_id: str) -> ClaimantClaim:
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    return _claimant_claim(claim)


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
    if active_session is not None:
        session = active_session
    else:
        timestamp = now_utc()
        session = SessionRecord(
            session_id=new_id('ses'),
            claim_id=claim_id,
            customer_id=principal.subject,
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
