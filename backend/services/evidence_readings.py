"""A handler sets what a claimant file is when the assistant read it wrongly.

The reading is a completed staff action naming the file. Everything that counts
files by kind (document needs, open items, triage) reads it through
``interpreted_evidence_kinds``, where a handler's reading wins over the model's.
"""

from __future__ import annotations

from hashlib import sha256

from pydantic import Field

from backend.core.auth import Principal, require_staff_capability
from backend.core.errors import ApiError
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.evidence import REGISTERED_EVIDENCE_KINDS, canonical_evidence_kind
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorType,
    ContractModel,
    StaffActionRecord,
    StaffActionResult,
    StaffActionStatus,
)
from backend.domain.open_items import EVIDENCE_READING_ACTION
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
from backend.services.workbench import require_workbench_action

ACTION_CODE = 'evidence.correct_reading'


class CorrectEvidenceReadingRequest(ContractModel):
    kind: str = Field(min_length=1, max_length=100)


class CorrectEvidenceReadingResponse(ContractModel):
    claim_id: str
    claim_revision: int = Field(ge=1)
    evidence_id: str
    kind: str


def correct_evidence_reading(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    evidence_id: str,
    payload: CorrectEvidenceReadingRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> CorrectEvidenceReadingResponse:
    """Record a handler's reading of one claimant file.

    Raises:
        ApiError: Authority, kind, revision, or replay checks fail.
    """
    require_staff_capability(principal, 'workbench:write')
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/reading'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        return CorrectEvidenceReadingResponse.model_validate(existing.response_payload)
    kind = canonical_evidence_kind(payload.kind)
    if kind not in REGISTERED_EVIDENCE_KINDS:
        raise ApiError(
            status_code=422, code='VALIDATION_ERROR', message='Choose a registered file type.'
        )
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The Claim was not found.'
        )
    action = require_workbench_action(
        repository, principal, claim, expected, ACTION_CODE, evidence_id
    )
    timestamp = now_utc()
    staff_action = StaffActionRecord(
        action_id=new_id('act'),
        claim_id=claim_id,
        action_type=EVIDENCE_READING_ACTION,
        status=StaffActionStatus.COMPLETED,
        assigned_to=principal.subject,
        requested_outcome=f'Read {evidence_id} as {kind}.',
        source_refs=[evidence_id],
        result=StaffActionResult(
            outcome=kind,
            summary=f'A handler set this file as {kind}.',
            reason_codes=['STAFF_EVIDENCE_READING'],
            source_refs=[evidence_id],
        ),
        completed_by=principal.subject,
        created_at=timestamp,
        completed_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': expected + 1, 'updated_at': timestamp})
    response = CorrectEvidenceReadingResponse(
        claim_id=claim_id, claim_revision=updated.revision, evidence_id=evidence_id, kind=kind
    )
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        action_registry_version=action.registry_version,
        action_code=action.action_code,
        target_ref=evidence_id,
        response_payload=response.model_dump(mode='json'),
        response_status=200,
    )
    audit = AuditEventEnvelope(
        event_id='aud_reading_'
        + sha256(f'{principal.subject}:{route}:{key}'.encode()).hexdigest()[:24],
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM, subject_id=claim_id, claim_id=claim_id
        ),
        actor=AuditActor(
            actor_type=ActorType.STAFF,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Staff corrected how a claimant file is read.',
        source_refs=[evidence_id, staff_action.action_id],
        permission=AuditPermission(
            required_permission=action.action_code, outcome=AuditPermissionOutcome.AUTHORISED
        ),
        visibility=AuditVisibility.INTERNAL_ONLY,
        correlation_id=key,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )
    try:
        repository.save_staff_mutation(
            updated, expected, record, staff_action=staff_action, audit_event=audit
        )
    except (RevisionConflict, IdempotencyConflict) as error:
        current = repository.get_claim_internal(claim_id)
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The Claim changed. Refresh before changing the file type again.',
            current_revision=current.revision if current is not None else None,
            retryable=True,
        ) from error
    return response
