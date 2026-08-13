from typing import Any

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    AcceptHandoffRequest,
    Coverage,
    CreateStaffActionRequest,
    CustomerNextStep,
    CustomerUpdateRecord,
    FraudSignal,
    HandoffMutationResponse,
    HandoffRecord,
    HandoffStatus,
    ResolveHandoffRequest,
    SignalDecisionRecord,
    SignalDecisionRequest,
    SignalDecisionResponse,
    StaffActionMutationResponse,
    StaffActionRecord,
    StaffActionStatus,
    UpdateStaffActionRequest,
    WorkflowState,
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
from backend.services.workbench import workbench_handoff


def _not_found(message: str) -> ApiError:
    return ApiError(status_code=404, code='RESOURCE_NOT_FOUND', message=message)


def _validation(message: str) -> ApiError:
    return ApiError(status_code=422, code='VALIDATION_ERROR', message=message)


def _staff_claim(
    repository: PersistenceRepository, principal: Principal, claim_id: str
) -> WorkingClaim:
    if principal.actor_type != 'staff':
        raise ApiError(status_code=403, code='ACCESS_DENIED', message='Staff access is required.')
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _not_found('The claim was not found.')
    return claim


def _retry(
    repository: PersistenceRepository, actor: str, route: str, key: str, fingerprint: str
) -> dict[str, Any] | None:
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
            message='The staff operation could not be restored.',
            retryable=True,
        )
    return record.response_payload


def _save(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    idempotency: IdempotencyRecord,
    **records: Any,
) -> None:
    try:
        repository.save_staff_mutation(claim, expected_revision, idempotency, **records)
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
            message='The staff operation was already accepted with different data.',
        ) from conflict


def _handoff(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    handoff_id: str,
) -> HandoffRecord:
    handoff = repository.get_handoff(claim.claim_id, handoff_id, claim.customer_id)
    if handoff is None:
        raise _not_found('The handoff was not found.')
    return handoff


def accept_handoff(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    handoff_id: str,
    payload: AcceptHandoffRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> HandoffMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return HandoffMutationResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    handoff = _handoff(repository, claim, handoff_id)
    if handoff.status is not HandoffStatus.QUEUED:
        raise _validation('Only a queued handoff can be accepted.')
    timestamp = now_utc()
    accepted = handoff.model_copy(
        update={
            'status': HandoffStatus.ACCEPTED,
            'assigned_to': payload.assignee_id or principal.subject,
            'accepted_at': timestamp,
        }
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = HandoffMutationResponse(
        handoff=workbench_handoff(accepted),
        revision=updated.revision,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        handoff_id=handoff_id,
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idempotency, handoff=accepted)
    return response


def resolve_handoff(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    handoff_id: str,
    payload: ResolveHandoffRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> HandoffMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return HandoffMutationResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    handoff = _handoff(repository, claim, handoff_id)
    if handoff.status not in {HandoffStatus.ACCEPTED, HandoffStatus.IN_PROGRESS}:
        raise _validation('The handoff must be accepted before it can be resolved.')
    if handoff.assigned_to not in {None, principal.subject}:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The handoff is assigned to another staff member.',
        )
    projected = _apply_state_changes(
        claim,
        UpdateStaffActionRequest(
            status=StaffActionStatus.COMPLETED,
            result=payload.result,
            state_changes=payload.state_changes,
            customer_update=payload.customer_update,
        ),
    )
    timestamp = now_utc()
    resolved = handoff.model_copy(
        update={
            'status': HandoffStatus.RESOLVED,
            'assigned_to': handoff.assigned_to or principal.subject,
            'resolved_at': timestamp,
        }
    )
    action = StaffActionRecord(
        action_id=new_id('act'),
        claim_id=claim_id,
        action_type='handoff_support',
        status=StaffActionStatus.COMPLETED,
        assigned_to=resolved.assigned_to or principal.subject,
        requested_outcome=handoff.requested_action,
        source_refs=[handoff_id],
        result=payload.result,
        completed_by=principal.subject,
        created_at=handoff.accepted_at or timestamp,
        completed_at=timestamp,
    )
    customer_update = CustomerUpdateRecord(
        **payload.customer_update.model_dump(),
        update_id=new_id('upd'),
        claim_id=claim_id,
        created_by=principal.subject,
        created_at=timestamp,
    )
    updated = projected.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': timestamp,
            'customer_next_step': CustomerNextStep(
                status='staff_update',
                summary=customer_update.summary,
                responsible_party=customer_update.responsible_party,
            ),
        }
    )
    response = HandoffMutationResponse(
        handoff=workbench_handoff(resolved),
        revision=updated.revision,
        staff_action=action,
        customer_update=customer_update,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        handoff_id=handoff_id,
        response_payload=response.model_dump(mode='json'),
    )
    _save(
        repository,
        updated,
        expected,
        idempotency,
        handoff=resolved,
        staff_action=action,
        customer_update=customer_update,
    )
    return response


def create_staff_action(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: CreateStaffActionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> StaffActionMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/staff-actions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return StaffActionMutationResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    timestamp = now_utc()
    action = StaffActionRecord(
        action_id=new_id('act'),
        claim_id=claim_id,
        action_type=payload.action_type,
        status=StaffActionStatus.OPEN,
        assigned_to=payload.assigned_to or principal.subject,
        requested_outcome=payload.requested_outcome,
        source_refs=payload.source_refs,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = StaffActionMutationResponse(action=action, revision=updated.revision)
    idem = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id='',
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idem, staff_action=action)
    return response


def _apply_state_changes(claim: WorkingClaim, payload: UpdateStaffActionRequest) -> WorkingClaim:
    state = claim.claim_state
    allowed = {
        'claim_state.coverage': Coverage,
        'claim_state.fraud_signal': FraudSignal,
        'claim_state.workflow_state': WorkflowState,
    }
    updates: dict[str, Any] = {}
    for change in payload.state_changes:
        enum_type = allowed.get(change.path)
        if enum_type is None:
            raise _validation(f'Staff write-back cannot change {change.path}.')
        try:
            value: Any = enum_type(change.to)
        except ValueError as error:
            raise _validation(f'Invalid value for {change.path}.') from error
        updates[change.path.removeprefix('claim_state.')] = value
    return claim.model_copy(update={'claim_state': state.model_copy(update=updates)})


def update_staff_action(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    action_id: str,
    payload: UpdateStaffActionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> StaffActionMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/staff-actions/{action_id}'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return StaffActionMutationResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    action = repository.get_staff_action(claim_id, action_id)
    if action is None:
        raise _not_found('The staff action was not found.')
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    if action.status in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}:
        raise _validation('A completed or cancelled staff action cannot be changed.')
    if payload.status is StaffActionStatus.COMPLETED and payload.result is None:
        raise _validation('Completing a staff action requires a result and reason code.')
    if payload.status is not StaffActionStatus.COMPLETED and (
        payload.state_changes or payload.customer_update
    ):
        raise _validation('State changes and claimant updates require a completed staff action.')
    timestamp = now_utc()
    updated_action = action.model_copy(
        update={
            'status': payload.status,
            'result': payload.result,
            'completed_by': principal.subject
            if payload.status is StaffActionStatus.COMPLETED
            else None,
            'completed_at': timestamp if payload.status is StaffActionStatus.COMPLETED else None,
        }
    )
    updated_claim = _apply_state_changes(claim, payload)
    customer_update = None
    if payload.customer_update is not None:
        customer_update = CustomerUpdateRecord(
            **payload.customer_update.model_dump(),
            update_id=new_id('upd'),
            claim_id=claim_id,
            created_by=principal.subject,
            created_at=timestamp,
        )
        updated_claim = updated_claim.model_copy(
            update={
                'customer_next_step': CustomerNextStep(
                    status='staff_update',
                    summary=customer_update.summary,
                    responsible_party=customer_update.responsible_party,
                )
            }
        )
    updated_claim = updated_claim.model_copy(
        update={'revision': claim.revision + 1, 'updated_at': timestamp}
    )
    response = StaffActionMutationResponse(
        action=updated_action, revision=updated_claim.revision, customer_update=customer_update
    )
    idem = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id='',
        response_payload=response.model_dump(mode='json'),
    )
    _save(
        repository,
        updated_claim,
        expected,
        idem,
        staff_action=updated_action,
        customer_update=customer_update,
    )
    return response


def decide_signal(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    signal_id: str,
    payload: SignalDecisionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> SignalDecisionResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/signals/{signal_id}/decisions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return SignalDecisionResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    sessions = repository.list_sessions_for_claim(claim_id, claim.customer_id)
    signal_exists = any(
        str(message.content.get('signal_id') or message.content.get('code')) == signal_id
        for session in sessions
        for message in repository.list_messages(claim_id, session.session_id, claim.customer_id)
        if message.content.get('type') == 'review_signal'
    ) or any(
        str(signal.get('signal_id') or signal.get('code')) == signal_id
        for decision in repository.list_agent_decisions(claim_id, claim.customer_id)
        for signal in decision.proposed_signals
    )
    if not signal_exists:
        raise _not_found('The internal review signal was not found.')
    timestamp = now_utc()
    decision = SignalDecisionRecord(
        **payload.model_dump(),
        signal_decision_id=new_id('sdec'),
        claim_id=claim_id,
        signal_id=signal_id,
        actor_id=principal.subject,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = SignalDecisionResponse(signal_decision=decision, revision=updated.revision)
    idem = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id='',
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idem, signal_decision=decision)
    return response
