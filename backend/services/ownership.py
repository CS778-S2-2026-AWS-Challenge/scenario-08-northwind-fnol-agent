"""Authorised Workbench ownership, cowork, transfer, and requeue actions."""

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    ClaimCollaborationRequest,
    ClaimCoworkerRecord,
    CollaborationMutationResponse,
    CollaborationRequestKind,
    CollaborationRequestStatus,
    CreateCoworkRequest,
    CreateTransferRequest,
    DecideCollaborationRequest,
    HandoffRecord,
    HandoffStatus,
    RequeueClaimRequest,
    StaffActionStatus,
    WorkingClaim,
)
from backend.domain.workbench import WorkbenchAllowedAction
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


def _error(status: int, code: str, message: str, *, revision: int | None = None) -> ApiError:
    return ApiError(
        status_code=status,
        code=code,
        message=message,
        retryable=code == 'REVISION_CONFLICT',
        current_revision=revision,
    )


def _claim(repository: PersistenceRepository, principal: Principal, claim_id: str) -> WorkingClaim:
    if principal.actor_type != 'staff':
        raise _error(403, 'ACCESS_DENIED', 'Staff Workbench access is required.')
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _error(404, 'RESOURCE_NOT_FOUND', 'The claim was not found.')
    return claim


def _active_handoff(repository: PersistenceRepository, claim: WorkingClaim) -> HandoffRecord | None:
    return next(
        (
            item
            for item in reversed(repository.list_handoffs(claim.claim_id, claim.customer_id))
            if item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
        ),
        None,
    )


def _primary_owner(repository: PersistenceRepository, claim: WorkingClaim) -> str | None:
    handoff = _active_handoff(repository, claim)
    return claim.assignee_id or (handoff.assigned_to if handoff is not None else None)


def _retry(
    repository: PersistenceRepository,
    principal: Principal,
    route: str,
    key: str,
    fingerprint: str,
) -> CollaborationMutationResponse | None:
    record = repository.find_idempotency(principal.subject, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise _error(
            409, 'IDEMPOTENCY_CONFLICT', 'The idempotency key was reused with different data.'
        )
    if record.response_payload is None:
        raise _error(500, 'INTERNAL_ERROR', 'The ownership operation could not be restored.')
    return CollaborationMutationResponse.model_validate(record.response_payload)


def _save(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected: int,
    idempotency: IdempotencyRecord,
    request: ClaimCollaborationRequest,
    *,
    coworkers: list[ClaimCoworkerRecord] | None = None,
    handoff: HandoffRecord | None = None,
) -> None:
    try:
        repository.save_ownership_mutation(
            claim,
            expected,
            idempotency,
            request,
            coworkers=coworkers,
            handoff=handoff,
        )
    except RevisionConflict as conflict:
        raise _error(
            409,
            'REVISION_CONFLICT',
            'The claim changed after this page was loaded.',
            revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise _error(
            409,
            'IDEMPOTENCY_CONFLICT',
            'The ownership operation conflicts with an existing record.',
        ) from conflict


def _idempotency(
    principal: Principal,
    route: str,
    key: str,
    fingerprint: str,
    claim: WorkingClaim,
    response: CollaborationMutationResponse,
    action: WorkbenchAllowedAction,
) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim.claim_id,
        session_id='',
        action_registry_version=action.registry_version,
        action_code=action.action_code,
        target_ref=action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )


def _validate_projected_inputs(
    action: WorkbenchAllowedAction,
    submitted: dict[str, object],
) -> None:
    definitions = {item.field_code: item for item in action.inputs}
    unprojected = sorted(set(submitted) - set(definitions))
    if unprojected:
        raise _error(
            422,
            'VALIDATION_ERROR',
            f'The action does not accept the submitted field: {unprojected[0]}.',
        )
    for field_code, definition in definitions.items():
        value = submitted.get(field_code)
        if definition.required and (value is None or not str(value).strip()):
            raise _error(
                422,
                'VALIDATION_ERROR',
                f'The projected action requires {field_code}.',
            )
        if definition.choices and value not in {choice.value for choice in definition.choices}:
            raise _error(
                422,
                'VALIDATION_ERROR',
                f'The submitted value for {field_code} is not registered for this action.',
            )


def create_cowork_request(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: CreateCoworkRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> CollaborationMutationResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/workbench/claims/{claim_id}/cowork-requests'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = _claim(repository, principal, claim_id)
    expected = parse_if_match(if_match)
    owner = _primary_owner(repository, claim)
    action_code = (
        'ownership.invite_cowork' if owner == principal.subject else 'ownership.request_cowork'
    )
    projected_action = require_workbench_action(
        repository, principal, claim, expected, action_code, claim.claim_id
    )
    _validate_projected_inputs(
        projected_action,
        payload.model_dump(mode='json', exclude_none=True),
    )
    if owner is None:
        raise _error(
            422,
            'VALIDATION_ERROR',
            'Accept the unassigned Claim instead of requesting cowork access.',
        )
    if principal.subject == owner:
        target = payload.staff_id
        if target is None or target == owner:
            raise _error(
                422, 'VALIDATION_ERROR', 'A primary owner must name another staff member to invite.'
            )
    else:
        if payload.staff_id not in {None, principal.subject}:
            raise _error(
                403, 'ACCESS_DENIED', 'A non-owner can request cowork access only for themselves.'
            )
        target = principal.subject
    if any(item.staff_id == target for item in repository.list_claim_coworkers(claim_id)):
        raise _error(409, 'OWNERSHIP_CONFLICT', 'That staff member already has cowork access.')
    if any(
        item.kind is CollaborationRequestKind.COWORK
        and item.status is CollaborationRequestStatus.PENDING
        and item.target_staff_id == target
        for item in repository.list_collaboration_requests(claim_id)
    ):
        raise _error(
            409,
            'OWNERSHIP_CONFLICT',
            'A cowork request for that staff member is already pending.',
        )
    timestamp = now_utc()
    request = ClaimCollaborationRequest(
        request_id=new_id('col'),
        claim_id=claim_id,
        kind=CollaborationRequestKind.COWORK,
        status=CollaborationRequestStatus.PENDING,
        requested_by=principal.subject,
        primary_owner_id=owner,
        target_staff_id=target,
        reason=payload.reason,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = CollaborationMutationResponse(request=request, revision=updated.revision)
    _save(
        repository,
        updated,
        expected,
        _idempotency(principal, route, key, fingerprint, claim, response, projected_action),
        request,
    )
    return response


def create_transfer_request(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: CreateTransferRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> CollaborationMutationResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/workbench/claims/{claim_id}/transfer-requests'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = _claim(repository, principal, claim_id)
    expected = parse_if_match(if_match)
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'ownership.request_transfer', claim.claim_id
    )
    _validate_projected_inputs(
        projected_action,
        payload.model_dump(mode='json', exclude_none=True),
    )
    owner = _primary_owner(repository, claim)
    if owner != principal.subject:
        raise _error(403, 'ACCESS_DENIED', 'Only the primary owner can request a normal transfer.')
    if payload.target_staff_id == owner:
        raise _error(422, 'VALIDATION_ERROR', 'A transfer must name a different staff member.')
    if any(
        item.kind is CollaborationRequestKind.TRANSFER
        and item.status is CollaborationRequestStatus.PENDING
        and item.target_staff_id == payload.target_staff_id
        for item in repository.list_collaboration_requests(claim_id)
    ):
        raise _error(
            409,
            'OWNERSHIP_CONFLICT',
            'A transfer request for that staff member is already pending.',
        )
    timestamp = now_utc()
    request = ClaimCollaborationRequest(
        request_id=new_id('col'),
        claim_id=claim_id,
        kind=CollaborationRequestKind.TRANSFER,
        status=CollaborationRequestStatus.PENDING,
        requested_by=principal.subject,
        primary_owner_id=owner,
        target_staff_id=payload.target_staff_id,
        reason=payload.reason,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = CollaborationMutationResponse(request=request, revision=updated.revision)
    _save(
        repository,
        updated,
        expected,
        _idempotency(principal, route, key, fingerprint, claim, response, projected_action),
        request,
    )
    return response


def decide_collaboration_request(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    request_id: str,
    payload: DecideCollaborationRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> CollaborationMutationResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/workbench/claims/{claim_id}/collaboration-requests/{request_id}'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = _claim(repository, principal, claim_id)
    expected = parse_if_match(if_match)
    request = next(
        (
            item
            for item in repository.list_collaboration_requests(claim_id)
            if item.request_id == request_id
        ),
        None,
    )
    if request is None:
        raise _error(404, 'RESOURCE_NOT_FOUND', 'The collaboration request was not found.')
    projected_action = require_workbench_action(
        repository,
        principal,
        claim,
        expected,
        f'ownership.decide_{request.kind.value}',
        request_id,
    )
    _validate_projected_inputs(
        projected_action,
        payload.model_dump(mode='json', exclude_none=True),
    )
    if request.status is not CollaborationRequestStatus.PENDING:
        raise _error(
            422, 'VALIDATION_ERROR', 'Only a pending collaboration request can be decided.'
        )
    expected_decider = (
        request.primary_owner_id
        if request.requested_by != request.primary_owner_id
        else request.target_staff_id
    )
    if principal.subject != expected_decider:
        raise _error(
            403,
            'ACCESS_DENIED',
            'This collaboration request must be decided by the other participant.',
        )
    timestamp = now_utc()
    decided = request.model_copy(
        update={
            'status': payload.decision,
            'resolved_by': principal.subject,
            'resolved_at': timestamp,
        }
    )
    coworkers: list[ClaimCoworkerRecord] = []
    coworker = None
    handoff = _active_handoff(repository, claim)
    updated_claim = claim
    if (
        payload.decision is CollaborationRequestStatus.ACCEPTED
        and request.kind is CollaborationRequestKind.COWORK
    ):
        coworker = ClaimCoworkerRecord(
            coworker_id=new_id('cow'),
            claim_id=claim_id,
            staff_id=request.target_staff_id or request.requested_by,
            granted_by=principal.subject,
            source_request_id=request.request_id,
            granted_at=timestamp,
        )
        coworkers.append(coworker)
    if (
        payload.decision is CollaborationRequestStatus.ACCEPTED
        and request.kind is CollaborationRequestKind.TRANSFER
    ):
        updated_claim = claim.model_copy(update={'assignee_id': request.target_staff_id})
        if handoff is not None:
            handoff = handoff.model_copy(update={'assigned_to': request.target_staff_id})
        coworkers.extend(
            item.model_copy(update={'active': False, 'revoked_at': timestamp})
            for item in repository.list_claim_coworkers(claim_id)
        )
    updated_claim = updated_claim.model_copy(
        update={'revision': claim.revision + 1, 'updated_at': timestamp}
    )
    response = CollaborationMutationResponse(
        request=decided, revision=updated_claim.revision, coworker=coworker
    )
    _save(
        repository,
        updated_claim,
        expected,
        _idempotency(principal, route, key, fingerprint, claim, response, projected_action),
        decided,
        coworkers=coworkers,
        handoff=handoff
        if request.kind is CollaborationRequestKind.TRANSFER
        and payload.decision is CollaborationRequestStatus.ACCEPTED
        else None,
    )
    return response


def requeue_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: RequeueClaimRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> CollaborationMutationResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/workbench/claims/{claim_id}/requeue'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = _claim(repository, principal, claim_id)
    expected = parse_if_match(if_match)
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'ownership.requeue', claim.claim_id
    )
    _validate_projected_inputs(
        projected_action,
        payload.model_dump(mode='json', exclude_none=True),
    )
    if _primary_owner(repository, claim) != principal.subject:
        raise _error(
            403, 'ACCESS_DENIED', 'Only the primary owner can return this Claim to the queue.'
        )
    if any(
        item.status is StaffActionStatus.IN_PROGRESS
        for item in repository.list_staff_actions(claim_id)
    ):
        raise _error(
            409,
            'OWNERSHIP_CONFLICT',
            'Complete or pause in-progress staff work before requeueing this Claim.',
        )
    if any(
        item.status.value in {'prepared', 'unknown_outcome'}
        for item in repository.list_external_tasks_internal(claim_id)
    ):
        raise _error(
            409,
            'OWNERSHIP_CONFLICT',
            'Resolve the active external operation before requeueing this Claim.',
        )
    timestamp = now_utc()
    request = ClaimCollaborationRequest(
        request_id=new_id('col'),
        claim_id=claim_id,
        kind=CollaborationRequestKind.REQUEUE,
        status=CollaborationRequestStatus.ACCEPTED,
        requested_by=principal.subject,
        primary_owner_id=principal.subject,
        reason=payload.reason,
        created_at=timestamp,
        resolved_by=principal.subject,
        resolved_at=timestamp,
    )
    coworkers = [
        item.model_copy(update={'active': False, 'revoked_at': timestamp})
        for item in repository.list_claim_coworkers(claim_id)
    ]
    handoff = _active_handoff(repository, claim)
    if handoff is not None and handoff.status in {
        HandoffStatus.ACCEPTED,
        HandoffStatus.IN_PROGRESS,
    }:
        handoff = handoff.model_copy(
            update={'status': HandoffStatus.QUEUED, 'assigned_to': None, 'accepted_at': None}
        )
    updated = claim.model_copy(
        update={'assignee_id': None, 'revision': claim.revision + 1, 'updated_at': timestamp}
    )
    response = CollaborationMutationResponse(request=request, revision=updated.revision)
    _save(
        repository,
        updated,
        expected,
        _idempotency(principal, route, key, fingerprint, claim, response, projected_action),
        request,
        coworkers=coworkers,
        handoff=handoff,
    )
    return response
