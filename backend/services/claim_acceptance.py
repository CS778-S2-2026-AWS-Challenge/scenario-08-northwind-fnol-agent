"""Self-assignment of a created Claim through the existing staff transaction."""

from hashlib import sha256

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
from backend.domain.claim_ownership import claim_acceptance_eligible, has_claim_owner
from backend.domain.models import ActorType
from backend.domain.workbench import WorkbenchClaimDetail
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.staff_presence import require_claimable_staff
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import project_workbench_claim_detail, require_workbench_action


def _replay(
    repository: PersistenceRepository, actor: str, route: str, key: str, fingerprint: str
) -> WorkbenchClaimDetail | None:
    record = repository.find_idempotency(actor, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused with a different request.',
        )
    if record.response_payload is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The saved acceptance response is unavailable.',
            retryable=True,
        )
    return WorkbenchClaimDetail.model_validate(record.response_payload)


def _already_assigned() -> ApiError:
    return ApiError(
        status_code=409,
        code='CLAIM_ALREADY_ASSIGNED',
        message='This Claim has already been taken. Refresh to see its current owner.',
    )


def accept_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    idempotency_key: str | None,
    if_match: str | None,
) -> WorkbenchClaimDetail:
    """Acquire an unassigned created Claim for the authenticated professional.

    Args:
        repository: Authoritative Claim, staff presence, audit, and retry storage.
        principal: Server-authenticated staff identity and capabilities.
        claim_id: Claim to acquire.
        idempotency_key: Actor-scoped identity retained across transport retries.
        if_match: Claim revision observed before explicit confirmation.

    Returns:
        The committed or exactly replayed Workbench detail.

    Raises:
        ApiError: Authority, eligibility, presence, revision, or replay checks fail.
    """
    require_staff_capability(principal, 'workbench:write')
    require_staff_capability(principal, 'workbench:read')
    if 'claims_professional' not in principal.roles:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Only a claims professional can take a Claim.',
        )
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/accept'
    fingerprint = request_fingerprint({})
    replay = _replay(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The Claim was not found.'
        )
    handoffs = repository.list_handoffs(claim_id, claim.customer_id)
    if has_claim_owner(claim, handoffs):
        raise _already_assigned()
    if not claim_acceptance_eligible(claim, handoffs):
        raise ApiError(
            status_code=409,
            code='CLAIM_NOT_READY_FOR_ACCEPTANCE',
            message='Only an undecided Claim with completed FNOL creation can be taken.',
        )
    require_claimable_staff(repository, principal)
    presence = repository.get_staff_presence(principal.subject)
    action = require_workbench_action(
        repository, principal, claim, expected, 'ownership.accept_claim', claim_id
    )
    timestamp = now_utc()
    updated = claim.model_copy(
        update={
            'assignee_id': principal.subject,
            'revision': expected + 1,
            'updated_at': timestamp,
        }
    )
    response = project_workbench_claim_detail(repository, principal, updated)
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        action_registry_version=action.registry_version,
        action_code=action.action_code,
        target_ref=claim_id,
        response_payload=response.model_dump(mode='json'),
        response_status=200,
    )
    audit = AuditEventEnvelope(
        event_id='aud_accept_'
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
        reason='Staff took primary ownership of the created Claim.',
        source_refs=[claim_id],
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
            updated,
            expected,
            record,
            required_staff_id=principal.subject,
            required_staff_revision=presence.revision if presence is not None else None,
            audit_event=audit,
        )
    except (RevisionConflict, IdempotencyConflict) as error:
        replay = _replay(repository, principal.subject, route, key, fingerprint)
        if replay is not None:
            return replay
        current = repository.get_claim_internal(claim_id)
        if current is not None and has_claim_owner(
            current, repository.list_handoffs(claim_id, current.customer_id)
        ):
            raise _already_assigned() from error
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The Claim changed. Refresh before confirming again.',
            current_revision=current.revision if current is not None else None,
            retryable=True,
        ) from error
    except KeyError as error:
        if error.args != ('staff_not_available',):
            raise
        raise ApiError(
            status_code=409,
            code='STAFF_NOT_AVAILABLE',
            message='Staff must be online and available to take a Claim.',
        ) from error
    return response
