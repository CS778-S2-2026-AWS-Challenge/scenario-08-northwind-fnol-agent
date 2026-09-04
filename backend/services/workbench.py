"""Role-safe Workbench projections assembled from authoritative Claim records."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypeVar

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.external_services import ExternalTaskOperationStatus, ExternalTaskRecord
from backend.domain.models import (
    ClaimCollaborationRequest,
    CollaborationRequestKind,
    CollaborationRequestStatus,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceStatus,
    FormStatus,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    MessageRecord,
    NeededFor,
    ResponsibleParty,
    SessionRecord,
    SignalDecisionRecord,
    SignalDecisionValue,
    StaffActionRecord,
    StaffActionStatus,
    SupportNeed,
    WorkbenchHandoff,
    WorkbenchSession,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.staff_agent import StaffAgentMessageRole
from backend.domain.tag_registry import get_staff_tag_definition
from backend.domain.workbench import (
    ActionAvailability,
    ClaimLifecycleState,
    ConfirmationLevel,
    CurrentStaffAccess,
    MissingInformationAttention,
    OwnershipState,
    ResourceAvailability,
    RiskAttentionLevel,
    SignalReviewStatus,
    WorkbenchActionConfirmation,
    WorkbenchActionInput,
    WorkbenchActionInputChoice,
    WorkbenchActionInputControl,
    WorkbenchActivityEvent,
    WorkbenchAllowedAction,
    WorkbenchClaimantSummary,
    WorkbenchClaimDetail,
    WorkbenchClaimListItem,
    WorkbenchClaimListResponse,
    WorkbenchCollaborationRequestsResponse,
    WorkbenchConversationKind,
    WorkbenchConversationsResponse,
    WorkbenchConversationSummary,
    WorkbenchCurrentWorkItem,
    WorkbenchCustomerUpdatesResponse,
    WorkbenchEventsResponse,
    WorkbenchEvidenceResponse,
    WorkbenchExternalLifecycle,
    WorkbenchExternalRequest,
    WorkbenchExternalRequestsResponse,
    WorkbenchFieldItem,
    WorkbenchFieldsResponse,
    WorkbenchHandoffsResponse,
    WorkbenchIncidentSummary,
    WorkbenchIncompleteContext,
    WorkbenchIntegrationSummary,
    WorkbenchMessagesResponse,
    WorkbenchMissingInformation,
    WorkbenchOwnershipProjection,
    WorkbenchPriorityProjection,
    WorkbenchPriorityReason,
    WorkbenchResourcePage,
    WorkbenchResponsibility,
    WorkbenchRetrievalsResponse,
    WorkbenchRiskSignal,
    WorkbenchSectionSummaries,
    WorkbenchSectionSummary,
    WorkbenchSessionsResponse,
    WorkbenchSignalDetail,
    WorkbenchSignalsResponse,
    WorkbenchStaffSummary,
    WorkbenchWaitingExternalService,
    WorkbenchWorkItemsResponse,
    WorkbenchWorkSummary,
    WorkPriorityLevel,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import decode_cursor, encode_cursor, now_utc
from backend.services.tag_projection import project_staff_tags

ResourceT = TypeVar('ResourceT')

SIGNAL_DECISION_REASON_CHOICES = (
    ('CONFLICT_REQUIRES_REVIEW', 'Conflict requires review'),
    ('CLAIM_LEVEL_SIGNAL_CONFIRMED', 'Claim-level signal confirmed'),
    ('POLICY_SECTION_CONFIRMED', 'Policy section confirmed'),
    ('SOURCE_RECORD_NOT_COMPARABLE', 'Source record not comparable'),
    ('STAFF_CONFIRMED_INTERPRETATION_REQUIRED', 'Interpretation still required'),
    ('STAFF_CONFIRMED_REVIEW_REQUIREMENT', 'Review requirement confirmed'),
    ('STAFF_REVIEWED_SOURCE', 'Source reviewed'),
)

_PRIORITY_RANK = {
    WorkPriorityLevel.IMMEDIATE: 0,
    WorkPriorityLevel.URGENT: 100,
    WorkPriorityLevel.HIGH: 200,
    WorkPriorityLevel.STANDARD: 300,
    WorkPriorityLevel.ROUTINE: 400,
}

_HANDOFF_PRIORITY = {
    HandoffPriority.IMMEDIATE: WorkPriorityLevel.IMMEDIATE,
    HandoffPriority.URGENT: WorkPriorityLevel.URGENT,
    HandoffPriority.HIGH: WorkPriorityLevel.HIGH,
    HandoffPriority.STANDARD: WorkPriorityLevel.STANDARD,
}


def _staff_access_required() -> ApiError:
    return ApiError(
        status_code=403,
        code='ACCESS_DENIED',
        message='Staff workbench access is required.',
    )


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def _authorised_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkingClaim:
    if principal.actor_type != 'staff':
        raise _staff_access_required()
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()
    return claim


def _page(
    items: Sequence[ResourceT], limit: int, cursor: str | None
) -> WorkbenchResourcePage[ResourceT]:
    offset = decode_cursor(cursor)
    selected = list(items[offset : offset + limit])
    next_offset = offset + len(selected)
    next_cursor = encode_cursor(next_offset) if next_offset < len(items) else None
    return WorkbenchResourcePage(items=selected, page={'next_cursor': next_cursor})


def _workbench_session(session: SessionRecord) -> WorkbenchSession:
    return WorkbenchSession(
        session_id=session.session_id,
        claim_id=session.claim_id,
        status=session.status,
        summary=session.summary,
        unresolved_questions=session.unresolved_questions,
        pending_items=session.pending_items,
        prior_commitments=session.prior_commitments,
        context_revision=session.context_revision,
        started_at=session.started_at,
        last_active_at=session.last_active_at,
        closed_at=session.closed_at,
    )


def workbench_handoff(handoff: HandoffRecord) -> WorkbenchHandoff:
    return WorkbenchHandoff(
        handoff_id=handoff.handoff_id,
        claim_id=handoff.claim_id,
        type=handoff.type,
        status=handoff.status,
        priority=handoff.priority,
        queue=handoff.queue,
        support_need=handoff.support_need,
        trigger=handoff.trigger,
        preferred_channel=handoff.preferred_channel,
        reason_codes=handoff.reason_codes,
        reason=handoff.reason,
        requested_action=handoff.requested_action,
        applied_rule=handoff.applied_rule,
        packet=handoff.packet,
        source_message_id=handoff.source_message_id,
        assigned_to=handoff.assigned_to,
        created_at=handoff.created_at,
        accepted_at=handoff.accepted_at,
        resolved_at=handoff.resolved_at,
    )


def _claim_messages(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    sessions: Sequence[SessionRecord],
) -> list[MessageRecord]:
    messages: list[MessageRecord] = []
    for session in sessions:
        messages.extend(
            repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)
        )
    actor_order = {'claimant': 0, 'agent': 1, 'staff': 2, 'system': 3}
    messages.sort(
        key=lambda item: (item.created_at, actor_order[item.actor.value], item.message_id)
    )
    return messages


def _pending_evidence(records: Sequence[EvidenceRecord]) -> list[EvidenceRecord]:
    pending_file_states = {
        EvidenceFileStatus.AWAITING_UPLOAD,
        EvidenceFileStatus.UPLOADING,
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
    }
    return [
        record
        for record in records
        if record.status
        in {
            EvidenceStatus.PENDING_GENERATION,
            EvidenceStatus.INCOMPLETE,
            EvidenceStatus.UNOFFICIAL,
        }
        or record.file_status in pending_file_states
    ]


def _active_handoffs(handoffs: Sequence[HandoffRecord]) -> list[HandoffRecord]:
    return [
        item
        for item in handoffs
        if item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
    ]


def _lifecycle(
    claim: WorkingClaim,
    active_handoffs: Sequence[HandoffRecord],
    pending_evidence: Sequence[EvidenceRecord],
) -> ClaimLifecycleState:
    if (
        claim.claim_state.workflow_state is WorkflowState.CREATED
        or claim.external_claim is not None
    ):
        return ClaimLifecycleState.CREATED
    if any(item.type is HandoffType.PROFESSIONAL_REVIEW for item in active_handoffs):
        return ClaimLifecycleState.PROFESSIONAL_REVIEW
    if claim.claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW:
        return ClaimLifecycleState.PROFESSIONAL_REVIEW
    if active_handoffs:
        return ClaimLifecycleState.STAFF_SUPPORT
    if claim.claim_state.workflow_state is WorkflowState.READY_FOR_NEXT:
        return ClaimLifecycleState.READY_TO_CREATE
    if claim.claim_state.workflow_state is WorkflowState.AWAITING_EVIDENCE:
        if any(
            item.responsible_party is ResponsibleParty.EXTERNAL_PARTY for item in pending_evidence
        ):
            return ClaimLifecycleState.WAITING_EXTERNAL
        return ClaimLifecycleState.WAITING_CUSTOMER
    return ClaimLifecycleState.DRAFT_ACTIVE


def _ownership(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    principal: Principal,
    active_handoffs: Sequence[HandoffRecord],
) -> WorkbenchOwnershipProjection:
    assigned = next(
        (item for item in reversed(active_handoffs) if item.assigned_to is not None),
        None,
    )
    assignee_id = assigned.assigned_to if assigned is not None else claim.assignee_id
    coworkers = repository.list_claim_coworkers(claim.claim_id)
    requests = repository.list_collaboration_requests(claim.claim_id)
    pending = [item for item in requests if item.status is CollaborationRequestStatus.PENDING]
    if assignee_id == principal.subject:
        access = CurrentStaffAccess.PRIMARY
    elif any(item.staff_id == principal.subject for item in coworkers):
        access = CurrentStaffAccess.COWORKER
    else:
        access = CurrentStaffAccess.READ_ONLY
    return WorkbenchOwnershipProjection(
        state=OwnershipState.ASSIGNED if assignee_id else OwnershipState.UNASSIGNED,
        primary_assignee=(
            WorkbenchStaffSummary(staff_id=assignee_id) if assignee_id is not None else None
        ),
        coworkers=[WorkbenchStaffSummary(staff_id=item.staff_id) for item in coworkers],
        coworker_count=len(coworkers),
        accepted_at=assigned.accepted_at if assigned is not None else None,
        last_owner_activity_at=claim.updated_at if assignee_id else None,
        current_staff_access=access,
        pending_cowork_requests=sum(
            item.kind is CollaborationRequestKind.COWORK for item in pending
        ),
        pending_transfer_requests=sum(
            item.kind is CollaborationRequestKind.TRANSFER for item in pending
        ),
    )


def _priority(
    claim: WorkingClaim,
    active_handoffs: Sequence[HandoffRecord],
    computed_at: datetime,
) -> WorkbenchPriorityProjection:
    if active_handoffs:
        handoff = min(
            active_handoffs,
            key=lambda item: _PRIORITY_RANK[_HANDOFF_PRIORITY[item.priority]],
        )
        level = _HANDOFF_PRIORITY[handoff.priority]
        reasons = [
            WorkbenchPriorityReason(
                code='OPEN_HANDOFF',
                summary=handoff.reason,
                source_refs=[handoff.handoff_id],
            )
        ]
    elif claim.claim_state.workflow_state is WorkflowState.COLLECTING:
        level = WorkPriorityLevel.ROUTINE
        reasons = [
            WorkbenchPriorityReason(
                code='CLAIM_IN_PROGRESS',
                summary='The claimant has not yet completed the report.',
                source_refs=[claim.claim_id],
            )
        ]
    else:
        level = WorkPriorityLevel.STANDARD
        reasons = []
    return WorkbenchPriorityProjection(
        level=level,
        rank=_PRIORITY_RANK[level],
        reasons=reasons,
        computed_at=computed_at,
    )


def _responsibility(value: ResponsibleParty | None) -> WorkbenchResponsibility:
    if value is ResponsibleParty.CLAIMANT:
        return WorkbenchResponsibility.CLAIMANT
    if value is ResponsibleParty.EXTERNAL_PARTY:
        return WorkbenchResponsibility.EXTERNAL_PARTY
    if value is ResponsibleParty.SYSTEM:
        return WorkbenchResponsibility.SYSTEM
    return WorkbenchResponsibility.CLAIMS_PROFESSIONAL


def _signal_status(decision: SignalDecisionValue | None) -> SignalReviewStatus:
    if decision is SignalDecisionValue.DISMISSED:
        return SignalReviewStatus.DISMISSED
    if decision in {SignalDecisionValue.RESOLVED, SignalDecisionValue.OVERRIDDEN}:
        return SignalReviewStatus.RESOLVED
    if decision is SignalDecisionValue.CONFIRMED:
        return SignalReviewStatus.UNDER_REVIEW
    return SignalReviewStatus.OPEN


def risk_signals(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> list[WorkbenchRiskSignal]:
    decisions = repository.list_signal_decisions(claim.claim_id)
    latest = {item.signal_id: item for item in decisions}
    signals = _signal_sources(repository, claim)
    projected: list[WorkbenchRiskSignal] = []
    for signal in signals:
        signal_id = str(signal.get('signal_id') or signal.get('code') or '')
        if not signal_id:
            continue
        code = str(signal.get('code') or signal_id)
        decision = latest.get(signal_id)
        attention = (
            RiskAttentionLevel.URGENT_REVIEW
            if 'URGENT' in code or 'SAFETY' in code
            else RiskAttentionLevel.REVIEW_REQUIRED
        )
        source_refs = signal.get('source_refs')
        projected.append(
            WorkbenchRiskSignal(
                signal_id=signal_id,
                category='review',
                code=code,
                label='Review signal',
                attention_level=attention,
                status=_signal_status(decision.decision if decision else None),
                summary=str(signal.get('summary') or code.replace('_', ' ').title()),
                source_refs=(
                    [str(value) for value in source_refs] if isinstance(source_refs, list) else []
                ),
            )
        )
    return projected


def _signal_sources(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for decision in repository.list_agent_decisions(claim.claim_id, claim.customer_id):
        for signal in decision.proposed_signals:
            signal_id = str(signal.get('signal_id') or signal.get('code') or '')
            if signal_id:
                value = dict(signal)
                value.setdefault('created_at', decision.created_at)
                values[signal_id] = value
    sessions = repository.list_sessions_for_claim(claim.claim_id, claim.customer_id)
    for message in _claim_messages(repository, claim, sessions):
        if message.content.get('type') != 'review_signal':
            continue
        signal_id = str(message.content.get('signal_id') or message.content.get('code') or '')
        if signal_id:
            value = dict(message.content)
            value.setdefault('created_at', message.created_at)
            values.setdefault(signal_id, value)
    for persisted_signal in repository.list_review_signals(claim.claim_id, claim.customer_id):
        values[persisted_signal.signal_id] = persisted_signal.model_dump(mode='json')
    return list(values.values())


def _missing_information(
    claim: WorkingClaim,
    pending_evidence: Sequence[EvidenceRecord],
) -> list[WorkbenchMissingInformation]:
    items: list[WorkbenchMissingInformation] = []
    for code, field in claim.form.items():
        if field.status is not FormStatus.MISSING:
            continue
        current = field.needed_for is NeededFor.CURRENT_ACTION
        items.append(
            WorkbenchMissingInformation(
                kind='field',
                code=code,
                label=code.replace('.', ' ').replace('_', ' ').title(),
                attention=(
                    MissingInformationAttention.REQUIRED_NOW
                    if current
                    else MissingInformationAttention.NEEDED_NEXT
                ),
                blocked_action=claim.claim_state.next_action.value if current else None,
                responsible_party=WorkbenchResponsibility.CLAIMANT,
                source_refs=field.source_refs,
            )
        )
    for evidence in pending_evidence:
        items.append(
            WorkbenchMissingInformation(
                kind='evidence',
                code=evidence.kind,
                label=evidence.kind.replace('_', ' ').title(),
                attention=(
                    MissingInformationAttention.REQUIRED_NOW
                    if NeededFor.CURRENT_ACTION in evidence.needed_for
                    else MissingInformationAttention.NEEDED_NEXT
                ),
                blocked_action=(
                    claim.claim_state.next_action.value
                    if NeededFor.CURRENT_ACTION in evidence.needed_for
                    else None
                ),
                responsible_party=_responsibility(evidence.responsible_party),
                source_refs=[evidence.evidence_id],
            )
        )
    return items


def _current_work_item(
    active_handoffs: Sequence[HandoffRecord],
    actions: Sequence[StaffActionRecord],
) -> WorkbenchCurrentWorkItem | None:
    if active_handoffs:
        item = active_handoffs[-1]
        return WorkbenchCurrentWorkItem(
            work_item_id=item.handoff_id,
            type=item.type.value,
            status=item.status.value,
            owner_role=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
            requested_outcome=item.requested_action,
            source_refs=[item.handoff_id],
        )
    open_actions = [
        item
        for item in actions
        if item.status not in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}
    ]
    if not open_actions:
        return None
    action_item = open_actions[-1]
    return WorkbenchCurrentWorkItem(
        work_item_id=action_item.action_id,
        type=action_item.action_type,
        status=action_item.status.value,
        owner_role=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
        requested_outcome=action_item.requested_outcome,
        source_refs=action_item.source_refs,
    )


def _queue_key(claim: WorkingClaim, active_handoffs: Sequence[HandoffRecord]) -> str:
    if active_handoffs:
        handoff = active_handoffs[-1]
        if handoff.support_need is SupportNeed.HUMAN_REQUESTED:
            return 'claimant_support'
        if handoff.type is HandoffType.PROFESSIONAL_REVIEW:
            return 'professional_review'
        return handoff.queue
    return {
        WorkflowState.COLLECTING: 'incomplete_claims',
        WorkflowState.READY_FOR_NEXT: 'ready_to_progress',
        WorkflowState.AWAITING_EVIDENCE: 'awaiting_evidence',
        WorkflowState.PROFESSIONAL_REVIEW: 'professional_review',
        WorkflowState.CREATED: 'created_routed',
    }[claim.claim_state.workflow_state]


def _incomplete_context(
    claim: WorkingClaim,
    sessions: Sequence[SessionRecord],
) -> WorkbenchIncompleteContext | None:
    if claim.claim_state.workflow_state is not WorkflowState.COLLECTING or not sessions:
        return None
    last = max(sessions, key=lambda item: item.last_active_at)
    resume_point = last.summary or claim.customer_next_step.summary
    return WorkbenchIncompleteContext(
        interrupted_at=last.last_active_at,
        last_meaningful_activity_at=last.last_active_at,
        resume_point=resume_point,
        follow_up_status='not_scheduled',
    )


def _external_tasks(
    repository: PersistenceRepository,
    claim_id: str,
) -> tuple[list[ExternalTaskRecord], str | None]:
    try:
        return repository.list_external_tasks_internal(claim_id), None
    except RuntimeError:
        return [], 'External-service records are temporarily unavailable.'


def _integration_summary(
    claim: WorkingClaim,
    external_tasks: Sequence[ExternalTaskRecord],
) -> WorkbenchIntegrationSummary:
    waiting = [
        WorkbenchWaitingExternalService(
            task_id=item.task_id,
            service_identity=item.service_identity,
            requested_action=item.requested_action,
            status=item.status.value,
        )
        for item in external_tasks
        if item.status
        in {
            ExternalTaskOperationStatus.PREPARED,
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        }
    ]
    return WorkbenchIntegrationSummary(
        claim_creation_status=(
            claim.external_claim.creation_status.value if claim.external_claim else None
        ),
        assessor_routing_status=(
            claim.assessor_routing.routing_status.value if claim.assessor_routing else None
        ),
        waiting_external_services=waiting,
    )


def _input(
    field_code: str,
    label: str,
    control: WorkbenchActionInputControl,
    *,
    choices: Sequence[tuple[str, str]] = (),
    required: bool = True,
) -> WorkbenchActionInput:
    return WorkbenchActionInput(
        field_code=field_code,
        label=label,
        control=control,
        required=required,
        choices=[
            WorkbenchActionInputChoice(value=value, label=choice_label)
            for value, choice_label in choices
        ],
    )


def handoff_resolution_defaults(handoff: HandoffRecord) -> dict[str, Any]:
    if handoff.type is HandoffType.PROFESSIONAL_REVIEW:
        return {
            'result': {
                'outcome': 'professional_review_completed',
                'reason_codes': ['POLICY_SECTION_CONFIRMED'],
                'source_refs': handoff.packet.source_refs,
            },
            'state_changes': [
                {'path': 'claim_state.coverage', 'to': 'clear'},
                {'path': 'claim_state.workflow_state', 'to': 'ready_for_next'},
            ],
            'customer_update': {
                'responsible_party': 'claims_professional',
                'related_refs': [handoff.handoff_id],
            },
        }
    return {
        'result': {
            'outcome': 'support_completed',
            'reason_codes': ['SUPPORT_NEED_MET'],
            'source_refs': handoff.packet.source_refs,
        },
        'state_changes': [],
        'customer_update': {
            'responsible_party': 'claims_professional',
            'related_refs': [handoff.handoff_id],
        },
    }


def work_item_defaults(action: StaffActionRecord) -> dict[str, Any]:
    if action.action_type in {'coverage_review', 'professional_review'}:
        outcome = 'professional_review_completed'
        reasons = ['POLICY_SECTION_CONFIRMED']
        state_changes = [
            {'path': 'claim_state.coverage', 'to': 'clear'},
            {'path': 'claim_state.workflow_state', 'to': 'ready_for_next'},
        ]
        customer_update: dict[str, Any] | None = {
            'responsible_party': 'claimant',
            'related_refs': [action.action_id],
        }
    else:
        outcome = 'staff_work_completed'
        reasons = ['SUPPORT_NEED_MET']
        state_changes = []
        customer_update = None
    return {
        'result': {
            'outcome': outcome,
            'reason_codes': reasons,
            'source_refs': action.source_refs,
        },
        'state_changes': state_changes,
        'customer_update': customer_update,
    }


def _allowed_actions(
    claim: WorkingClaim,
    ownership: WorkbenchOwnershipProjection,
    active_handoffs: Sequence[HandoffRecord],
    staff_actions: Sequence[StaffActionRecord],
    risk_signals: Sequence[WorkbenchRiskSignal],
    collaboration_requests: Sequence[ClaimCollaborationRequest],
    principal: Principal,
) -> list[WorkbenchAllowedAction]:
    actions: list[WorkbenchAllowedAction] = []
    if active_handoffs:
        handoff = active_handoffs[-1]
        if handoff.status in {HandoffStatus.REQUESTED, HandoffStatus.QUEUED}:
            blocked = (
                handoff.assigned_to is not None
                and ownership.current_staff_access is not CurrentStaffAccess.PRIMARY
            )
            actions.append(
                WorkbenchAllowedAction(
                    action_code='human.accept_handoff',
                    target_ref=handoff.handoff_id,
                    label='Accept Claim',
                    purpose='Take responsibility for the requested staff work.',
                    availability=ActionAvailability.BLOCKED
                    if blocked
                    else ActionAvailability.CONFIRMATION_REQUIRED,
                    blocked_reason='This work is assigned to another staff member.'
                    if blocked
                    else None,
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message=(
                            'Accepting this Claim makes you responsible for the current handoff.'
                        ),
                    ),
                    expected_effects=['handoff.accept', 'ownership.assign'],
                    source_refs=[handoff.handoff_id],
                    result_state='pending_confirmation',
                    based_on_revision=claim.revision,
                )
            )
        elif ownership.current_staff_access in {
            CurrentStaffAccess.PRIMARY,
            CurrentStaffAccess.COWORKER,
        }:
            actions.append(
                WorkbenchAllowedAction(
                    action_code='conversation.send_claimant_message',
                    target_ref=claim.active_session_id or handoff.handoff_id,
                    label='Reply to claimant',
                    purpose='Continue the accepted claimant conversation.',
                    availability=(
                        ActionAvailability.CONFIRMATION_REQUIRED
                        if claim.active_session_id
                        else ActionAvailability.BLOCKED
                    ),
                    blocked_reason=None
                    if claim.active_session_id
                    else 'No active claimant session is available.',
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message='This message will be visible to the claimant.',
                    ),
                    expected_effects=['message.append', 'handoff.mark_in_progress'],
                    source_refs=[handoff.handoff_id],
                    inputs=[
                        _input(
                            'content.text',
                            'Claimant-visible message',
                            WorkbenchActionInputControl.TEXTAREA,
                        )
                    ],
                    result_state='awaiting_input',
                    based_on_revision=claim.revision,
                )
            )
            if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
                actions.append(
                    WorkbenchAllowedAction(
                        action_code='human.resolve_handoff',
                        target_ref=handoff.handoff_id,
                        label='Resolve handoff',
                        purpose='Record the outcome and the claimant-safe next step.',
                        availability=ActionAvailability.CONFIRMATION_REQUIRED,
                        confirmation=WorkbenchActionConfirmation(
                            level=ConfirmationLevel.EXPLICIT,
                            message='The recorded outcome will update the shared Claim context.',
                        ),
                        expected_effects=['handoff.resolve', 'customer_update.append'],
                        source_refs=[handoff.handoff_id],
                        inputs=[
                            _input(
                                'result.summary',
                                'Internal result summary',
                                WorkbenchActionInputControl.TEXTAREA,
                            ),
                            _input(
                                'customer_update.summary',
                                'Claimant update',
                                WorkbenchActionInputControl.TEXTAREA,
                            ),
                        ],
                        payload_defaults=handoff_resolution_defaults(handoff),
                        result_state='awaiting_input',
                        based_on_revision=claim.revision,
                    )
                )
    if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
        for signal in risk_signals:
            if signal.status not in {SignalReviewStatus.OPEN, SignalReviewStatus.UNDER_REVIEW}:
                continue
            actions.append(
                WorkbenchAllowedAction(
                    action_code='signal.record_decision',
                    target_ref=signal.signal_id,
                    label='Record signal decision',
                    purpose='Record a source-linked decision for this exact review signal.',
                    availability=ActionAvailability.CONFIRMATION_REQUIRED,
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message='This internal decision is audited and may change review work.',
                    ),
                    expected_effects=['signal.decision.append', 'claim.revision.advance'],
                    source_refs=signal.source_refs,
                    inputs=[
                        _input(
                            'decision',
                            'Decision',
                            WorkbenchActionInputControl.SELECT,
                            choices=(
                                ('confirmed', 'Confirm for review'),
                                ('dismissed', 'Dismiss signal'),
                                ('overridden', 'Override signal'),
                                ('resolved', 'Resolve signal'),
                            ),
                        ),
                        _input(
                            'reason_codes.0',
                            'Reason',
                            WorkbenchActionInputControl.SELECT,
                            choices=SIGNAL_DECISION_REASON_CHOICES,
                        ),
                        _input(
                            'summary',
                            'Decision summary',
                            WorkbenchActionInputControl.TEXTAREA,
                        ),
                    ],
                    payload_defaults={'evidence_refs': signal.source_refs},
                    result_state='awaiting_input',
                    based_on_revision=claim.revision,
                )
            )
    for staff_action in staff_actions:
        if staff_action.status in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}:
            continue
        if staff_action.assigned_to != principal.subject:
            continue
        actions.append(
            WorkbenchAllowedAction(
                action_code='work_item.update',
                target_ref=staff_action.action_id,
                label='Update assigned work',
                purpose='Progress or complete this exact assigned WorkItem.',
                availability=ActionAvailability.CONFIRMATION_REQUIRED,
                confirmation=WorkbenchActionConfirmation(
                    level=ConfirmationLevel.EXPLICIT,
                    message='The selected status and any completion result will be audited.',
                ),
                expected_effects=['work_item.update', 'claim.revision.advance'],
                source_refs=staff_action.source_refs,
                inputs=[
                    _input(
                        'status',
                        'Status',
                        WorkbenchActionInputControl.SELECT,
                        choices=(
                            ('in_progress', 'In progress'),
                            ('completed', 'Completed'),
                            ('cancelled', 'Cancelled'),
                        ),
                    ),
                    _input(
                        'result.summary',
                        'Result summary',
                        WorkbenchActionInputControl.TEXTAREA,
                        required=False,
                    ),
                    *(
                        [
                            _input(
                                'customer_update.summary',
                                'Claimant update',
                                WorkbenchActionInputControl.TEXTAREA,
                                required=False,
                            )
                        ]
                        if work_item_defaults(staff_action)['customer_update'] is not None
                        else []
                    ),
                ],
                payload_defaults=work_item_defaults(staff_action),
                result_state='awaiting_input',
                based_on_revision=claim.revision,
            )
        )
    if (
        ownership.current_staff_access is CurrentStaffAccess.READ_ONLY
        and ownership.primary_assignee
    ):
        actions.append(
            WorkbenchAllowedAction(
                action_code='ownership.request_cowork',
                target_ref=claim.claim_id,
                label='Request cowork access',
                purpose='Ask the primary owner to collaborate on this Claim.',
                availability=ActionAvailability.CONFIRMATION_REQUIRED,
                confirmation=WorkbenchActionConfirmation(
                    level=ConfirmationLevel.EXPLICIT,
                    message='The current primary owner will receive this request.',
                ),
                expected_effects=['collaboration_request.create'],
                based_on_revision=claim.revision,
            )
        )
    if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
        actions.extend(
            [
                WorkbenchAllowedAction(
                    action_code='ownership.invite_cowork',
                    target_ref=claim.claim_id,
                    label='Invite coworker',
                    purpose='Grant another staff member access after they accept the invitation.',
                    availability=ActionAvailability.CONFIRMATION_REQUIRED,
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message='The invited staff member must accept before access changes.',
                    ),
                    expected_effects=['collaboration_request.create'],
                    based_on_revision=claim.revision,
                ),
                WorkbenchAllowedAction(
                    action_code='ownership.request_transfer',
                    target_ref=claim.claim_id,
                    label='Request transfer',
                    purpose='Ask another staff member to become the primary owner.',
                    availability=ActionAvailability.CONFIRMATION_REQUIRED,
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message='Ownership changes only after the target staff member accepts.',
                    ),
                    expected_effects=['collaboration_request.create'],
                    based_on_revision=claim.revision,
                ),
                WorkbenchAllowedAction(
                    action_code='ownership.requeue',
                    target_ref=claim.claim_id,
                    label='Return to queue',
                    purpose='Release primary ownership when no protected work is active.',
                    availability=ActionAvailability.CONFIRMATION_REQUIRED,
                    confirmation=WorkbenchActionConfirmation(
                        level=ConfirmationLevel.EXPLICIT,
                        message='This Claim will become available for another staff member.',
                    ),
                    expected_effects=['ownership.release', 'queue.recompute'],
                    based_on_revision=claim.revision,
                ),
            ]
        )
    for request in collaboration_requests:
        if request.status is not CollaborationRequestStatus.PENDING:
            continue
        expected_decider = (
            request.primary_owner_id
            if request.requested_by != request.primary_owner_id
            else request.target_staff_id
        )
        if expected_decider != principal.subject:
            continue
        target = request.target_staff_id or request.requested_by
        actions.append(
            WorkbenchAllowedAction(
                action_code=f'ownership.decide_{request.kind.value}',
                target_ref=request.request_id,
                label=(
                    'Review cowork request'
                    if request.kind is CollaborationRequestKind.COWORK
                    else 'Review transfer request'
                ),
                purpose=(
                    f'Decide whether {target} may collaborate on this Claim.'
                    if request.kind is CollaborationRequestKind.COWORK
                    else f'Decide whether ownership should transfer to {target}.'
                ),
                availability=ActionAvailability.CONFIRMATION_REQUIRED,
                confirmation=WorkbenchActionConfirmation(
                    level=ConfirmationLevel.EXPLICIT,
                    message='Accepting this request changes Claim access and is audited.',
                ),
                expected_effects=(
                    ['ownership.cowork_grant']
                    if request.kind is CollaborationRequestKind.COWORK
                    else ['ownership.transfer']
                ),
                source_refs=[request.request_id],
                based_on_revision=claim.revision,
            )
        )
    return actions


def _primary_action(
    allowed_actions: Sequence[WorkbenchAllowedAction],
    active_handoffs: Sequence[HandoffRecord],
    current_work: WorkbenchCurrentWorkItem | None,
    risk_signals: Sequence[WorkbenchRiskSignal],
) -> WorkbenchAllowedAction | None:
    preferred: list[tuple[str, str | None]] = []
    if active_handoffs:
        handoff = active_handoffs[-1]
        preferred.append(
            (
                'human.accept_handoff'
                if handoff.status in {HandoffStatus.REQUESTED, HandoffStatus.QUEUED}
                else 'human.resolve_handoff',
                handoff.handoff_id,
            )
        )
    preferred.extend(
        ('signal.record_decision', signal.signal_id)
        for signal in risk_signals
        if signal.status in {SignalReviewStatus.OPEN, SignalReviewStatus.UNDER_REVIEW}
    )
    if current_work is not None:
        preferred.append(('work_item.update', current_work.work_item_id))
    preferred.append(('ownership.request_cowork', None))
    for action_code, target_ref in preferred:
        match = next(
            (
                action
                for action in allowed_actions
                if action.action_code == action_code
                and (target_ref is None or action.target_ref == target_ref)
            ),
            None,
        )
        if match is not None:
            return match
    return None


def _matches_view(item: WorkbenchClaimListItem, view: str | None) -> bool:
    if view in {None, 'all'}:
        return True
    if view == 'urgent':
        return item.priority_projection.level in {
            WorkPriorityLevel.IMMEDIATE,
            WorkPriorityLevel.URGENT,
        }
    if view == 'human_requests':
        return item.work_summary.queue_key == 'claimant_support'
    if view == 'awaiting_evidence':
        return any(value.kind == 'evidence' for value in item.work_summary.missing_information)
    return item.work_summary.queue_key == view


def _build_projection(
    repository: PersistenceRepository,
    principal: Principal,
    claim: WorkingClaim,
    *,
    include_detail: bool,
) -> WorkbenchClaimListItem | WorkbenchClaimDetail:
    evidence = repository.list_evidence(claim.claim_id, claim.customer_id)
    pending_evidence = _pending_evidence(evidence)
    handoffs = repository.list_handoffs(claim.claim_id, claim.customer_id)
    active_handoffs = _active_handoffs(handoffs)
    sessions = repository.list_sessions_for_claim(claim.claim_id, claim.customer_id)
    messages = _claim_messages(repository, claim, sessions)
    actions = repository.list_staff_actions(claim.claim_id)
    projected_risk_signals = risk_signals(repository, claim)
    external_tasks, external_limitation = _external_tasks(repository, claim.claim_id)
    computed_at = now_utc()
    collaboration_requests = repository.list_collaboration_requests(claim.claim_id)
    ownership = _ownership(repository, claim, principal, active_handoffs)
    missing = _missing_information(claim, pending_evidence)
    current_work = _current_work_item(active_handoffs, actions)
    allowed_actions = _allowed_actions(
        claim,
        ownership,
        active_handoffs,
        actions,
        projected_risk_signals,
        collaboration_requests,
        principal,
    )
    primary_action = _primary_action(
        allowed_actions,
        active_handoffs,
        current_work,
        projected_risk_signals,
    )
    claimant_messages = [item for item in messages if item.actor.value == 'claimant']
    work_summary = WorkbenchWorkSummary(
        queue_key=_queue_key(claim, active_handoffs),
        current_work_item=current_work,
        primary_action_code=primary_action.action_code if primary_action else None,
        primary_action_target_ref=primary_action.target_ref if primary_action else None,
        primary_blocker=next(
            (
                item.label
                for item in missing
                if item.attention is MissingInformationAttention.REQUIRED_NOW
            ),
            None,
        ),
        missing_information=missing,
        risk_signals=projected_risk_signals,
        incomplete_context=_incomplete_context(claim, sessions),
        unread_claimant_messages=0,
        last_claimant_activity_at=(
            max(item.created_at for item in claimant_messages) if claimant_messages else None
        ),
        external_wait_count=len(external_tasks),
    )
    tags = project_staff_tags(
        claim,
        evidence=evidence,
        handoffs=handoffs,
        review_signals=repository.list_review_signals(claim.claim_id, claim.customer_id),
        signal_decisions=repository.list_signal_decisions(claim.claim_id),
    )
    base = dict(
        claim_id=claim.claim_id,
        display_reference=claim.external_claim.claim_number
        if claim.external_claim and claim.external_claim.claim_number
        else claim.claim_id,
        revision=claim.revision,
        claimant=WorkbenchClaimantSummary(customer_id=claim.customer_id),
        incident=WorkbenchIncidentSummary(
            family=claim.incident_type,
            summary=_incident_summary(claim),
        ),
        lifecycle_state=_lifecycle(claim, active_handoffs, pending_evidence),
        workflow_state=claim.claim_state.workflow_state,
        ownership=ownership,
        priority_projection=_priority(claim, active_handoffs, computed_at),
        work_summary=work_summary,
        integration_summary=_integration_summary(claim, external_tasks),
        tags=tags,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
    if not include_detail:
        return WorkbenchClaimListItem(**base)
    unavailable_external = external_limitation is not None
    return WorkbenchClaimDetail(
        **base,
        active_session_id=claim.active_session_id,
        claim_state=claim.claim_state,
        allowed_actions=allowed_actions,
        section_summaries=WorkbenchSectionSummaries(
            fields=WorkbenchSectionSummary(
                status=ResourceAvailability.AVAILABLE,
                total=len(claim.form),
                needs_attention=sum(
                    field.status is not FormStatus.CONFIRMED for field in claim.form.values()
                ),
            ),
            conversation=WorkbenchSectionSummary(
                status=ResourceAvailability.AVAILABLE,
                total=len(messages),
                session_count=len(sessions),
                unread_count=0,
            ),
            evidence=WorkbenchSectionSummary(
                status=ResourceAvailability.AVAILABLE,
                total=len(evidence),
                needs_attention=len(pending_evidence),
            ),
            reference_checks=WorkbenchSectionSummary(
                status=ResourceAvailability.AVAILABLE,
                total=len(repository.list_retrieval_records(claim.claim_id, claim.customer_id)),
                needs_attention=len(projected_risk_signals),
            ),
            external_services=WorkbenchSectionSummary(
                status=(
                    ResourceAvailability.UNAVAILABLE
                    if unavailable_external
                    else ResourceAvailability.AVAILABLE
                ),
                total=len(external_tasks),
                needs_attention=sum(
                    item.status is not ExternalTaskOperationStatus.ACCEPTED
                    for item in external_tasks
                ),
                limitation=external_limitation,
            ),
            activity=WorkbenchSectionSummary(
                status=ResourceAvailability.AVAILABLE,
                total=2 + len(messages) + len(handoffs) + len(actions),
            ),
        ),
        customer_next_step=claim.customer_next_step,
    )


def _incident_summary(claim: WorkingClaim) -> str:
    for code in ('incident.description', 'incident.summary', 'loss.description'):
        field = claim.form.get(code)
        if field is not None and isinstance(field.value, str) and field.value.strip():
            return field.value.strip()
    family = claim.incident_type or 'unconfirmed'
    return f'{family.replace("_", " ").title()} incident; details are still being collected.'


def list_workbench_claims(
    repository: PersistenceRepository,
    principal: Principal,
    view: str | None = None,
    tag: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> WorkbenchClaimListResponse:
    if principal.actor_type != 'staff':
        raise _staff_access_required()
    if tag is not None:
        try:
            get_staff_tag_definition(tag)
        except ValueError as error:
            raise ApiError(
                status_code=400,
                code='INVALID_TAG_FILTER',
                message='The requested staff tag is not published.',
                details=[ErrorDetail(field='tag', reason=tag)],
            ) from error
    items: list[WorkbenchClaimListItem] = []
    for claim in repository.list_claims_internal():
        projected = _build_projection(repository, principal, claim, include_detail=False)
        assert isinstance(projected, WorkbenchClaimListItem)
        if not _matches_view(projected, view):
            continue
        if tag is not None and all(item.code != tag for item in projected.tags):
            continue
        items.append(projected)
    items.sort(
        key=lambda item: (
            item.priority_projection.rank,
            item.priority_projection.due_at or item.created_at,
            item.claim_id,
        )
    )
    offset = decode_cursor(cursor)
    page_items = items[offset : offset + limit]
    next_offset = offset + len(page_items)
    next_cursor = encode_cursor(next_offset) if next_offset < len(items) else None
    return WorkbenchClaimListResponse(items=page_items, page={'next_cursor': next_cursor})


def get_workbench_claim_detail(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkbenchClaimDetail:
    claim = _authorised_claim(repository, principal, claim_id)
    projected = _build_projection(repository, principal, claim, include_detail=True)
    assert isinstance(projected, WorkbenchClaimDetail)
    return projected


def list_workbench_fields(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchFieldsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    items = [
        WorkbenchFieldItem(code=code, field=field) for code, field in sorted(claim.form.items())
    ]
    return _page(items, limit, cursor)


def list_workbench_sessions(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchSessionsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    sessions = repository.list_sessions_for_claim(claim_id, claim.customer_id)
    sessions.sort(key=lambda item: (item.started_at, item.session_id))
    return _page([_workbench_session(item) for item in sessions], limit, cursor)


def list_workbench_collaboration_requests(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchCollaborationRequestsResponse:
    _authorised_claim(repository, principal, claim_id)
    requests = repository.list_collaboration_requests(claim_id)
    requests.sort(key=lambda item: (item.created_at, item.request_id))
    return _page(requests, limit, cursor)


def list_workbench_conversations(
    repository: PersistenceRepository,
    principal: Principal,
    limit: int,
    cursor: str | None,
) -> WorkbenchConversationsResponse:
    if principal.actor_type != 'staff':
        raise _staff_access_required()
    items: list[WorkbenchConversationSummary] = []
    for claim in repository.list_claims_internal():
        handoffs = repository.list_handoffs(claim.claim_id, claim.customer_id)
        ownership = _ownership(repository, claim, principal, _active_handoffs(handoffs))
        if ownership.current_staff_access is CurrentStaffAccess.READ_ONLY:
            continue
        display_reference = (
            claim.external_claim.claim_number
            if claim.external_claim and claim.external_claim.claim_number
            else claim.claim_id
        )
        for session in repository.list_sessions_for_claim(claim.claim_id, claim.customer_id):
            items.append(
                WorkbenchConversationSummary(
                    conversation_id=f'claim:{session.session_id}',
                    kind=WorkbenchConversationKind.CLAIM,
                    claim_id=claim.claim_id,
                    display_reference=display_reference,
                    session_id=session.session_id,
                    status=session.status.value,
                    title=f'Claim {display_reference}',
                    summary=session.summary or _incident_summary(claim),
                    updated_at=session.last_active_at,
                )
            )
    for agent_session in repository.list_staff_agent_sessions(principal.subject):
        messages = repository.list_staff_agent_messages(agent_session.session_id, principal.subject)
        messages.sort(
            key=lambda item: (
                item.created_at,
                0 if item.role is StaffAgentMessageRole.STAFF else 1,
                item.message_id,
            )
        )
        summary = messages[-1].content if messages else None
        items.append(
            WorkbenchConversationSummary(
                conversation_id=f'staff_agent:{agent_session.session_id}',
                kind=WorkbenchConversationKind.STAFF_AGENT,
                session_id=agent_session.session_id,
                status='active',
                title=agent_session.title,
                summary=summary,
                updated_at=agent_session.updated_at,
            )
        )
    items.sort(key=lambda item: (item.updated_at, item.conversation_id), reverse=True)
    return _page(items, limit, cursor)


def list_workbench_messages(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchMessagesResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    session = repository.get_session(claim_id, session_id, claim.customer_id)
    if session is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The session was not found.'
        )
    messages = repository.list_messages(claim_id, session_id, claim.customer_id)
    actor_order = {'claimant': 0, 'agent': 1, 'staff': 2, 'system': 3}
    messages.sort(
        key=lambda item: (item.created_at, actor_order[item.actor.value], item.message_id)
    )
    return _page(messages, limit, cursor)


def list_workbench_evidence(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchEvidenceResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    items = repository.list_evidence(claim_id, claim.customer_id)
    items.sort(key=lambda item: (item.created_at, item.evidence_id))
    return _page(items, limit, cursor)


def list_workbench_retrievals(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchRetrievalsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    items = repository.list_retrieval_records(claim_id, claim.customer_id)
    items.sort(key=lambda item: (item.source.retrieved_at, item.retrieval_id))
    return _page(items, limit, cursor)


def list_workbench_signals(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchSignalsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    decisions = repository.list_signal_decisions(claim_id)
    by_signal: dict[str, list[SignalDecisionRecord]] = {}
    for decision in decisions:
        by_signal.setdefault(decision.signal_id, []).append(decision)
    retrievals = {
        item.retrieval_id: item
        for item in repository.list_retrieval_records(claim_id, claim.customer_id)
    }
    items: list[WorkbenchSignalDetail] = []
    projected_by_id = {item.signal_id: item for item in risk_signals(repository, claim)}
    for signal in _signal_sources(repository, claim):
        signal_id = str(signal.get('signal_id') or signal.get('code') or '')
        if not signal_id:
            continue
        projected = projected_by_id[signal_id]
        source_refs = signal.get('source_refs')
        refs = [str(value) for value in source_refs] if isinstance(source_refs, list) else []
        reason_codes = signal.get('reason_codes')
        items.append(
            WorkbenchSignalDetail(
                **projected.model_dump(),
                reason_codes=(
                    [str(value) for value in reason_codes] if isinstance(reason_codes, list) else []
                ),
                decisions=[item.model_dump(mode='json') for item in by_signal.get(signal_id, [])],
                source_evidence=[
                    retrievals[ref].model_dump(mode='json') for ref in refs if ref in retrievals
                ],
                created_at=signal.get('created_at'),
            )
        )
    items.sort(key=lambda item: (item.created_at or claim.created_at, item.signal_id))
    return _page(items, limit, cursor)


def list_workbench_handoffs(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchHandoffsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    items = repository.list_handoffs(claim_id, claim.customer_id)
    items.sort(key=lambda item: (item.created_at, item.handoff_id))
    return _page([workbench_handoff(item) for item in items], limit, cursor)


def list_workbench_work_items(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchWorkItemsResponse:
    _authorised_claim(repository, principal, claim_id)
    items = repository.list_staff_actions(claim_id)
    items.sort(key=lambda item: (item.created_at, item.action_id))
    return _page(items, limit, cursor)


def list_workbench_customer_updates(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchCustomerUpdatesResponse:
    _authorised_claim(repository, principal, claim_id)
    items = repository.list_customer_updates(claim_id)
    items.sort(key=lambda item: (item.created_at, item.update_id))
    return _page(items, limit, cursor)


def _external_lifecycle(
    task: ExternalTaskRecord,
    request: Any | None,
) -> WorkbenchExternalLifecycle:
    status = task.status
    if status is ExternalTaskOperationStatus.PREPARED:
        label = 'Pending'
        detail = 'The request is prepared and has not been submitted.'
        verification = 'not_started'
        owner = WorkbenchResponsibility.CLAIMS_PROFESSIONAL
        next_action = 'Review the projected disclosure, authority, and consent before submission.'
        attention = False
    elif status is ExternalTaskOperationStatus.ACCEPTED:
        label = 'Completion not confirmed'
        detail = 'The provider acknowledged the request; no verified completed result is recorded.'
        verification = 'pending_verification'
        owner = WorkbenchResponsibility.EXTERNAL_PARTY
        next_action = 'Track the provider result and verify it before reconciling Claim State.'
        attention = False
    elif status is ExternalTaskOperationStatus.RETRYABLE_FAILURE:
        label = 'Failed'
        detail = 'The request failed before a verified result; the same operation may be retried.'
        verification = 'failed_unverified'
        owner = WorkbenchResponsibility.CLAIMS_PROFESSIONAL
        next_action = 'Correct the dependency problem, then retry with the same operation identity.'
        attention = True
    elif status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        label = 'Outcome not confirmed'
        detail = 'Submission may have occurred; the result remains unknown.'
        verification = 'reconciliation_required'
        owner = WorkbenchResponsibility.CLAIMS_PROFESSIONAL
        next_action = 'Reconcile by operation or provider reference before any retry.'
        attention = True
    else:
        label = 'Failed'
        detail = 'The request failed and requires staff review.'
        verification = 'review_required'
        owner = WorkbenchResponsibility.CLAIMS_PROFESSIONAL
        next_action = 'Review the failure before another request is attempted.'
        attention = True
    fixture = task.integration_source.value == 'fixture'
    limitation = (
        'Synthetic fixture record; no production provider completion is verified.'
        if fixture
        else None
    )
    return WorkbenchExternalLifecycle(
        stakeholder='external_party',
        service=task.service_identity,
        request_type=task.requested_action,
        authority_state='recorded' if request is not None else 'not_recorded',
        consent_state=(
            'recorded'
            if request is not None and request.authorisation.claimant_consent_ref
            else 'not_recorded'
        ),
        delivery_state=task.delivery.value,
        verification_state=verification,
        pending_owner=owner,
        status_label=label,
        status_detail=detail,
        result=task.provider_reference,
        limitation=limitation,
        next_action=next_action,
        needs_attention=attention,
    )


def list_workbench_external_requests(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchExternalRequestsResponse:
    _authorised_claim(repository, principal, claim_id)
    try:
        tasks = repository.list_external_tasks_internal(claim_id)
        requests = repository.list_external_task_requests_internal(claim_id)
    except RuntimeError:
        return WorkbenchResourcePage(
            items=[],
            page={'next_cursor': None},
            status=ResourceAvailability.UNAVAILABLE,
            limitation='External-service records are temporarily unavailable.',
        )
    by_task = {item.task_id: item for item in requests}
    items = []
    for task in tasks:
        external_request = by_task.get(task.task_id)
        items.append(
            WorkbenchExternalRequest(
                request=external_request,
                task=task,
                lifecycle=_external_lifecycle(task, external_request),
            )
        )
    items.sort(key=lambda item: (item.task.created_at, item.task.task_id))
    return _page(items, limit, cursor)


def list_workbench_events(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    limit: int,
    cursor: str | None,
) -> WorkbenchEventsResponse:
    claim = _authorised_claim(repository, principal, claim_id)
    sessions = repository.list_sessions_for_claim(claim_id, claim.customer_id)
    messages = _claim_messages(repository, claim, sessions)
    handoffs = repository.list_handoffs(claim_id, claim.customer_id)
    actions = repository.list_staff_actions(claim_id)
    updates = repository.list_customer_updates(claim_id)
    collaboration_requests = repository.list_collaboration_requests(claim_id)
    events = [
        WorkbenchActivityEvent(
            event_id=f'{claim_id}:created',
            event_type='claim.created',
            summary='Claim context created.',
            source_refs=[claim_id],
            created_at=claim.created_at,
            resulting_revision=1,
        )
    ]
    events.extend(
        WorkbenchActivityEvent(
            event_id=item.message_id,
            event_type='message.appended',
            actor_id=item.actor.value,
            summary=f'{item.actor.value.title()} message recorded.',
            source_refs=[item.message_id, item.session_id],
            created_at=item.created_at,
        )
        for item in messages
    )
    events.extend(
        WorkbenchActivityEvent(
            event_id=item.handoff_id,
            event_type=f'handoff.{item.status.value}',
            actor_id=item.assigned_to,
            summary=item.reason,
            source_refs=[item.handoff_id],
            created_at=item.resolved_at or item.accepted_at or item.created_at,
        )
        for item in handoffs
    )
    events.extend(
        WorkbenchActivityEvent(
            event_id=item.action_id,
            event_type=f'work_item.{item.status.value}',
            actor_id=item.completed_by or item.assigned_to,
            summary=item.requested_outcome,
            source_refs=[item.action_id, *item.source_refs],
            created_at=item.completed_at or item.created_at,
        )
        for item in actions
    )
    events.extend(
        WorkbenchActivityEvent(
            event_id=item.update_id,
            event_type='customer_update.recorded',
            actor_id=item.created_by,
            summary=item.summary,
            source_refs=[item.update_id, *item.related_refs],
            created_at=item.created_at,
        )
        for item in updates
    )
    events.extend(
        WorkbenchActivityEvent(
            event_id=item.request_id,
            event_type=f'ownership.{item.kind.value}.{item.status.value}',
            actor_id=item.resolved_by or item.requested_by,
            summary=item.reason,
            source_refs=[item.request_id],
            created_at=item.resolved_at or item.created_at,
        )
        for item in collaboration_requests
    )
    events.sort(key=lambda item: (item.created_at, item.event_id), reverse=True)
    return _page(events, limit, cursor)
