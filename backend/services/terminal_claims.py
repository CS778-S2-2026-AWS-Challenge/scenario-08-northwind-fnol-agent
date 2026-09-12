"""Authorised Workbench mutations for terminal Claim dispositions."""

from hashlib import sha256
from typing import Any

from backend.core.auth import Principal
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
from backend.domain.models import (
    ActorType,
    ReopenClaimRequest,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.domain.workbench import WorkbenchClaimDetail
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
from backend.services.workbench import (
    project_workbench_claim_detail,
    require_workbench_action,
)


def _retry(
    repository: PersistenceRepository,
    actor_id: str,
    route: str,
    key: str,
    fingerprint: str,
) -> WorkbenchClaimDetail | None:
    record = repository.find_idempotency(actor_id, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused with different reopen data.',
        )
    if record.response_payload is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The reopened Claim response could not be restored.',
            retryable=True,
        )
    return WorkbenchClaimDetail.model_validate(record.response_payload)


def _claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkingClaim:
    if principal.actor_type != 'staff':
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Staff Workbench access is required.',
        )
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )
    return claim


def _save(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope,
) -> None:
    try:
        repository.save_claim_mutation_with_audit(
            claim,
            expected_revision,
            idempotency,
            (audit_event,),
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The Claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The reopen operation conflicts with an existing request.',
        ) from conflict
    except KeyError as conflict:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The Claim is no longer available.',
        ) from conflict


def reopen_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: ReopenClaimRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> WorkbenchClaimDetail:
    """Clear an authorised abandoned/closed disposition and restore active projection.

    Args:
        repository: Authoritative Claim and audit persistence boundary.
        principal: Authenticated staff principal requesting the action.
        claim_id: Exact Claim targeted by the projected action.
        payload: The bounded staff reason projected by ``claim.reopen``.
        idempotency_key: Retry key for this staff mutation.
        if_match: Expected authoritative Claim revision.

    Returns:
        The updated Workbench Claim detail at the resulting revision.

    Raises:
        ApiError: Authentication, action, input, revision, or persistence checks fail.
    """
    if principal.actor_type != 'staff':
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Staff Workbench access is required.',
        )
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    reason = payload.reason.strip()
    route = f'/api/v1/workbench/claims/{claim_id}/reopen'
    fingerprint_payload: dict[str, Any] = {
        **payload.model_dump(mode='json'),
        'expected_revision': expected,
    }
    fingerprint = request_fingerprint(fingerprint_payload)
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return replay
    if not reason:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='A reopen reason is required.',
        )

    claim = _claim(repository, principal, claim_id)
    action = require_workbench_action(
        repository,
        principal,
        claim,
        expected,
        'claim.reopen',
        claim_id,
    )
    terminal = claim.terminal_disposition
    if terminal is None or terminal.value not in {
        TerminalDispositionValue.ABANDONED,
        TerminalDispositionValue.CLOSED,
    }:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The requested action is not available in the current Workbench projection.',
        )

    timestamp = now_utc()
    updated = claim.model_copy(
        update={
            'terminal_disposition': None,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    response = project_workbench_claim_detail(repository, principal, updated)
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        action_registry_version=action.registry_version,
        action_code=action.action_code,
        target_ref=action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )
    audit_event = AuditEventEnvelope(
        event_id=(
            'aud_reopen_' + sha256(f'{principal.subject}:{route}:{key}'.encode()).hexdigest()[:20]
        ),
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.STAFF,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason=reason,
        source_refs=terminal.source_refs,
        permission=AuditPermission(
            required_permission='claim.reopen:primary_owner',
            outcome=AuditPermissionOutcome.AUTHORISED,
        ),
        visibility=AuditVisibility.INTERNAL_ONLY,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )
    _save(repository, updated, expected, idempotency, audit_event)
    return response
