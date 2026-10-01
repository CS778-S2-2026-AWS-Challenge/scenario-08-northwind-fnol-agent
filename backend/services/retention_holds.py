"""Authorised Workbench actions that apply and release retention holds."""

from datetime import datetime

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
from backend.domain.ids import stable_digest, stable_operation_id
from backend.domain.models import ActorType, WorkingClaim
from backend.domain.retention import (
    ApplyRetentionHoldRequest,
    ReleaseRetentionHoldRequest,
    RetentionHoldRecord,
    WorkbenchRetentionHold,
)
from backend.domain.workbench import WorkbenchAllowedAction
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
)
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import require_workbench_action


def project_retention_hold(hold: RetentionHoldRecord) -> WorkbenchRetentionHold:
    """Return the staff-only resource for one retention hold.

    Args:
        hold: The authoritative hold record.

    Returns:
        The Workbench projection without authority internals.
    """

    return WorkbenchRetentionHold(
        hold_id=hold.hold_id,
        claim_id=hold.claim_id,
        reason=hold.reason,
        applied_at=hold.applied_at,
        released_at=hold.released_at,
        active=hold.active,
    )


def _replayed(
    repository: PersistenceRepository,
    principal: Principal,
    route: str,
    key: str,
    fingerprint: str,
) -> WorkbenchRetentionHold | None:
    record = repository.find_idempotency(principal.subject, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused with different retention hold data.',
        )
    if record.response_payload is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The retention hold response could not be restored.',
            retryable=True,
        )
    return WorkbenchRetentionHold.model_validate(record.response_payload)


def _claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkingClaim:
    require_staff_capability(principal, 'workbench:write')
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )
    return claim


def _commit(
    repository: PersistenceRepository,
    principal: Principal,
    claim: WorkingClaim,
    action: WorkbenchAllowedAction,
    hold: RetentionHoldRecord,
    *,
    route: str,
    key: str,
    fingerprint: str,
    note: str,
    recorded_at: datetime,
) -> WorkbenchRetentionHold:
    """Persist the hold, its audit event, then the replay record.

    Every identity and timestamp derives from the request, so a retry after a
    partial failure re-commits the same hold and audit event as exact replays.
    """

    try:
        repository.save_retention_hold(hold)
        repository.append_audit_event(
            AuditEventEnvelope(
                event_id='aud_hold_' + stable_digest(f'{principal.subject}:{route}:{key}', 20),
                event_type=AuditEventType.ACTION_COMPLETED,
                outcome=AuditOutcome.SUCCEEDED,
                subject=AuditSubject(
                    subject_type=AuditSubjectType.CLAIM,
                    subject_id=claim.claim_id,
                    claim_id=claim.claim_id,
                ),
                actor=AuditActor(
                    actor_type=ActorType.STAFF,
                    actor_id=principal.subject,
                    auth_source=principal.auth_source,
                ),
                reason=note,
                source_refs=[f'retention-hold:{hold.hold_id}', *hold.source_refs],
                permission=AuditPermission(
                    required_permission=f'{action.action_code}:primary_owner',
                    outcome=AuditPermissionOutcome.AUTHORISED,
                ),
                visibility=AuditVisibility.INTERNAL_ONLY,
                idempotency_key=key,
                claim_revision=claim.revision,
                created_at=recorded_at,
            )
        )
    except (IdempotencyConflict, ValueError) as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The retention hold conflicts with an existing request.',
        ) from conflict

    response = project_retention_hold(hold)
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim.claim_id,
            session_id=claim.active_session_id or '',
            action_registry_version=action.registry_version,
            action_code=action.action_code,
            target_ref=action.target_ref,
            response_payload=response.model_dump(mode='json'),
        )
    )
    return response


def apply_retention_hold(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: ApplyRetentionHoldRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> WorkbenchRetentionHold:
    """Stop destructive retention cleanup for one Claim until the hold is released.

    Args:
        repository: Authoritative persistence boundary.
        principal: Authenticated staff principal; must be the Claim's primary owner.
        claim_id: Claim to hold.
        payload: Typed hold reason and the source of the hold decision.
        idempotency_key: Required replay key.
        if_match: Claim revision the action was offered against.

    Returns:
        The created hold, or the original response on exact replay.

    Raises:
        ApiError: Missing write scope, unknown Claim, stale revision, an action the
            current projection does not offer, or a conflicting replay.
    """

    require_staff_capability(principal, 'workbench:write')
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/retention-holds'
    fingerprint = request_fingerprint(
        {**payload.model_dump(mode='json'), 'expected_revision': expected}
    )
    replay = _replayed(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay

    claim = _claim(repository, principal, claim_id)
    action = require_workbench_action(
        repository, principal, claim, expected, 'retention.hold.apply', claim_id
    )
    hold_id = stable_operation_id('rhl', f'{claim_id}:{principal.subject}:{route}:{key}')
    existing = next(
        (item for item in repository.list_retention_holds(claim_id) if item.hold_id == hold_id),
        None,
    )
    hold = existing or RetentionHoldRecord(
        hold_id=hold_id,
        claim_id=claim_id,
        reason=payload.reason,
        authority_ref=f'staff:{principal.subject}',
        source_refs=[f'workbench-action:retention.hold.apply:{hold_id}'],
        applied_at=now_utc(),
    )
    return _commit(
        repository,
        principal,
        claim,
        action,
        hold,
        route=route,
        key=key,
        fingerprint=fingerprint,
        note=payload.note.strip(),
        recorded_at=hold.applied_at,
    )


def release_retention_hold(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    hold_id: str,
    payload: ReleaseRetentionHoldRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> WorkbenchRetentionHold:
    """Release one active hold so retention can resume the same operation.

    Args:
        repository: Authoritative persistence boundary.
        principal: Authenticated staff principal; must be the Claim's primary owner.
        claim_id: Claim that owns the hold.
        hold_id: Active hold to release.
        payload: Why the hold can be released.
        idempotency_key: Required replay key.
        if_match: Claim revision the action was offered against.

    Returns:
        The released hold, or the original response on exact replay.

    Raises:
        ApiError: Missing write scope, unknown Claim or hold, stale revision, an
            action the current projection does not offer, or a conflicting replay.
    """

    require_staff_capability(principal, 'workbench:write')
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/retention-holds/{hold_id}/release'
    fingerprint = request_fingerprint(
        {**payload.model_dump(mode='json'), 'expected_revision': expected}
    )
    replay = _replayed(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay

    claim = _claim(repository, principal, claim_id)
    current = next(
        (item for item in repository.list_retention_holds(claim_id) if item.hold_id == hold_id),
        None,
    )
    if current is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The retention hold was not found.',
        )
    if current.active:
        action = require_workbench_action(
            repository, principal, claim, expected, 'retention.hold.release', hold_id
        )
        released = current.model_copy(update={'released_at': now_utc()})
    else:
        # Release is one-way; a second release has nothing left to change.
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The retention hold is already released.',
        )
    return _commit(
        repository,
        principal,
        claim,
        action,
        released,
        route=route,
        key=key,
        fingerprint=fingerprint,
        note=payload.note.strip(),
        recorded_at=released.released_at or now_utc(),
    )
