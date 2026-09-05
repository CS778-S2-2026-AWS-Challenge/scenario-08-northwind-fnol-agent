from typing import Any

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    AcceptHandoffRequest,
    ActorType,
    AgentAction,
    Coverage,
    CreateStaffActionRequest,
    CreateStaffMessageRequest,
    CustomerNextStep,
    CustomerSupport,
    CustomerUpdateRecord,
    FraudSignal,
    HandoffMutationResponse,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    MessageRecord,
    MessageVisibility,
    ResolveHandoffRequest,
    SessionStatus,
    SignalDecisionRecord,
    SignalDecisionRequest,
    SignalDecisionResponse,
    StaffActionMutationResponse,
    StaffActionRecord,
    StaffActionStatus,
    StaffMessageResponse,
    UpdateStaffActionRequest,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.workbench import (
    WorkbenchCompletionPayloadDefaults,
    WorkbenchSignalPayloadDefaults,
)
from backend.domain.workbench_action_registry import (
    WORK_ITEM_TYPE_REGISTRY,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.staff_access import ClaimStaffAccess, require_claim_collaborator
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import (
    require_workbench_action,
    risk_signals,
    workbench_handoff,
)


def _not_found(message: str) -> ApiError:
    return ApiError(status_code=404, code='RESOURCE_NOT_FOUND', message=message)


def _validation(message: str) -> ApiError:
    return ApiError(status_code=422, code='VALIDATION_ERROR', message=message)


def _validate_fixed_action_payload(
    payload: ResolveHandoffRequest | UpdateStaffActionRequest,
    defaults: WorkbenchCompletionPayloadDefaults,
) -> None:
    expected_result = defaults.result
    if expected_result is None:
        raise _validation('The projected action has no registered completion result.')
    if payload.result is None or (
        payload.result.outcome != expected_result.outcome
        or payload.result.reason_codes != expected_result.reason_codes
        or payload.result.source_refs != expected_result.source_refs
    ):
        raise _validation('The result must match the projected registered action contract.')
    if payload.state_changes != defaults.state_changes:
        raise _validation('State changes must match the projected registered action contract.')
    expected_update = defaults.customer_update
    if expected_update is None:
        if payload.customer_update is not None:
            raise _validation('This registered action does not permit a claimant update.')
        return
    if payload.customer_update is None or (
        payload.customer_update.responsible_party.value != expected_update.responsible_party.value
        or payload.customer_update.related_refs != expected_update.related_refs
    ):
        raise _validation('The claimant update must match the projected action contract.')


def _completion_defaults(
    payload: object,
) -> WorkbenchCompletionPayloadDefaults:
    if not isinstance(payload, WorkbenchCompletionPayloadDefaults):
        raise _validation('The projected action has no registered completion contract.')
    return payload


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
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'human.accept_handoff', handoff_id
    )
    handoff = _handoff(repository, claim, handoff_id)
    if handoff.status is not HandoffStatus.QUEUED:
        raise _validation('Only a queued handoff can be accepted.')
    requested_assignee = payload.assignee_id or principal.subject
    if requested_assignee != principal.subject:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Staff can accept a Claim only for their own account.',
        )
    if claim.assignee_id not in {None, principal.subject}:
        raise ApiError(
            status_code=409,
            code='OWNERSHIP_CONFLICT',
            message='The Claim is already assigned to another staff member.',
        )
    timestamp = now_utc()
    accepted = handoff.model_copy(
        update={
            'status': HandoffStatus.ACCEPTED,
            'assigned_to': requested_assignee,
            'accepted_at': timestamp,
        }
    )
    updated = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': timestamp,
            'assignee_id': requested_assignee,
            'customer_next_step': CustomerNextStep(
                status=(
                    'professional_review_in_progress'
                    if handoff.type is HandoffType.PROFESSIONAL_REVIEW
                    else 'human_support_in_progress'
                ),
                summary=(
                    'A claims specialist is now reviewing the policy point in your report.'
                    if handoff.type is HandoffType.PROFESSIONAL_REVIEW
                    else 'A Northwind staff member is now assisting you.'
                ),
                responsible_party='claims_professional',
            ),
        }
    )
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
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idempotency, handoff=accepted)
    return response


def send_staff_message(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: CreateStaffMessageRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> StaffMessageResponse:
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/messages'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return StaffMessageResponse.model_validate(replay)
    claim = _staff_claim(repository, principal, claim_id)
    active_session_id = claim.active_session_id
    target_ref = active_session_id
    if target_ref is None:
        active_handoffs = [
            item
            for item in repository.list_handoffs(claim_id, claim.customer_id)
            if item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
        ]
        target_ref = active_handoffs[-1].handoff_id if active_handoffs else claim_id
    projected_action = require_workbench_action(
        repository,
        principal,
        claim,
        expected,
        'conversation.send_claimant_message',
        target_ref,
    )
    if active_session_id is None:
        raise _validation('An active claimant session is required before sending a staff message.')
    active_session = repository.get_session(claim_id, active_session_id, claim.customer_id)
    if active_session is None or active_session.status is not SessionStatus.ACTIVE:
        raise _validation('An active claimant session is required before sending a staff message.')

    handoffs = repository.list_handoffs(claim_id, claim.customer_id)
    active = next(
        (
            item
            for item in reversed(handoffs)
            if item.status in {HandoffStatus.ACCEPTED, HandoffStatus.IN_PROGRESS}
        ),
        None,
    )
    if active is None:
        raise _validation('An accepted handoff is required before sending a staff message.')
    coworker_ids = {item.staff_id for item in repository.list_claim_coworkers(claim_id)}
    if active.assigned_to != principal.subject and principal.subject not in coworker_ids:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The Claim is assigned to another staff member and cowork access is required.',
        )
    if payload.in_reply_to is not None:
        referenced = repository.get_message(
            claim_id,
            active_session_id,
            payload.in_reply_to,
            claim.customer_id,
        )
        if referenced is None or referenced.visibility is MessageVisibility.INTERNAL_ONLY:
            raise _validation(
                'The reply reference must belong to the permitted claim conversation and session.'
            )
    timestamp = now_utc()
    message = MessageRecord(
        message_id=new_id('msg'),
        claim_id=claim_id,
        session_id=active_session_id,
        actor=ActorType.STAFF,
        visibility=MessageVisibility.SHARED,
        content=payload.content.model_dump(mode='json'),
        in_reply_to=payload.in_reply_to,
        created_at=timestamp,
    )
    updated_handoff = active.model_copy(update={'status': HandoffStatus.IN_PROGRESS})
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = StaffMessageResponse(
        claim_id=claim_id,
        session_id=message.session_id,
        claim_revision=updated.revision,
        message=message,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=message.session_id,
        message_id=message.message_id,
        handoff_id=active.handoff_id,
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idempotency, handoff=updated_handoff, message=message)
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
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'human.resolve_handoff', handoff_id
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
    _validate_fixed_action_payload(payload, _completion_defaults(projected_action.payload_defaults))
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
        action_type=(
            'professional_review'
            if handoff.type is HandoffType.PROFESSIONAL_REVIEW
            else 'handoff_support'
        ),
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
    resulting_state = projected.claim_state
    if handoff.type is HandoffType.PROFESSIONAL_REVIEW:
        resulting_state = resulting_state.model_copy(update={'next_action': AgentAction.PROCEED})
    updated = projected.model_copy(
        update={
            'claim_state': resulting_state,
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
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
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
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'work_item.create', claim_id
    )
    access = require_claim_collaborator(repository, claim, principal)
    if payload.action_type not in WORK_ITEM_TYPE_REGISTRY:
        raise _validation('The staff action type is not registered for Workbench use.')
    timestamp = now_utc()
    assigned_to = payload.assigned_to or principal.subject
    permitted_assignees = {
        claim.assignee_id,
        *(item.staff_id for item in repository.list_claim_coworkers(claim_id)),
    }
    if assigned_to not in permitted_assignees:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message=(
                'Staff actions can be assigned only to the primary owner or an active coworker.'
            ),
        )
    if access is ClaimStaffAccess.COWORKER and assigned_to != principal.subject:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='A coworker can create a staff action only for their own account.',
        )
    action = StaffActionRecord(
        action_id=new_id('act'),
        claim_id=claim_id,
        action_type=payload.action_type,
        status=StaffActionStatus.OPEN,
        assigned_to=assigned_to,
        requested_outcome=WORK_ITEM_TYPE_REGISTRY[payload.action_type].requested_outcome,
        source_refs=projected_action.source_refs,
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
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idem, staff_action=action)
    return response


def _apply_state_changes(claim: WorkingClaim, payload: UpdateStaffActionRequest) -> WorkingClaim:
    state = claim.claim_state
    allowed = {
        'claim_state.coverage': Coverage,
        'claim_state.customer_support': CustomerSupport,
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
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'work_item.update', action_id
    )
    action = repository.get_staff_action(claim_id, action_id)
    if action is None:
        raise _not_found('The staff action was not found.')
    if action.assigned_to != principal.subject:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='A staff member can update only a WorkItem assigned to their account.',
        )
    if action.status in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}:
        raise _validation('A completed or cancelled staff action cannot be changed.')
    if payload.status is StaffActionStatus.COMPLETED and payload.result is None:
        raise _validation('Completing a staff action requires a result and reason code.')
    if payload.status is not StaffActionStatus.COMPLETED and (
        payload.state_changes or payload.customer_update
    ):
        raise _validation('State changes and claimant updates require a completed staff action.')
    if payload.status is StaffActionStatus.COMPLETED:
        _validate_fixed_action_payload(
            payload, _completion_defaults(projected_action.payload_defaults)
        )
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
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
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
    projected_action = require_workbench_action(
        repository, principal, claim, expected, 'signal.record_decision', signal_id
    )
    projected_signal = next(
        (signal for signal in risk_signals(repository, claim) if signal.signal_id == signal_id),
        None,
    )
    if projected_signal is None:
        raise _not_found('The internal review signal was not found.')
    reason_input = next(
        item for item in projected_action.inputs if item.field_code == 'reason_codes.0'
    )
    registered_reasons = {item.value for item in reason_input.choices}
    if len(payload.reason_codes) != 1 or payload.reason_codes[0] not in registered_reasons:
        raise _validation('The signal decision reason is not registered for Workbench use.')
    decision_input = next(item for item in projected_action.inputs if item.field_code == 'decision')
    registered_decisions = {item.value for item in decision_input.choices}
    if payload.decision.value not in registered_decisions:
        raise _validation('The signal decision is not registered for Workbench use.')
    signal_defaults = projected_action.payload_defaults
    if not isinstance(signal_defaults, WorkbenchSignalPayloadDefaults):
        raise _validation('The projected action has no registered signal contract.')
    if payload.evidence_refs != signal_defaults.evidence_refs:
        raise _validation('Signal evidence references must match the projected action contract.')
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
        action_registry_version=projected_action.registry_version,
        action_code=projected_action.action_code,
        target_ref=projected_action.target_ref,
        response_payload=response.model_dump(mode='json'),
    )
    _save(repository, updated, expected, idem, signal_decision=decision)
    return response
