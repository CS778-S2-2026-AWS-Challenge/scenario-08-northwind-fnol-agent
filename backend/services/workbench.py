"""Role-safe Workbench projections assembled from authoritative Claim records."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypeVar

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.external_services import (
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskResult,
    ExternalTaskResultVerification,
)
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
from backend.domain.tag_registry import (
    TAG_REGISTRY_VERSION,
    get_filterable_staff_tag_definition,
    list_filterable_staff_tag_definitions,
)
from backend.domain.workbench import (
    ActionAvailability,
    ClaimLifecycleState,
    CurrentStaffAccess,
    MissingInformationAttention,
    OwnershipState,
    ResourceAvailability,
    RiskAttentionLevel,
    SignalReviewStatus,
    WorkbenchActionConfirmation,
    WorkbenchActionInput,
    WorkbenchActionInputChoice,
    WorkbenchActionInputCondition,
    WorkbenchActivityEvent,
    WorkbenchAllowedAction,
    WorkbenchClaimantSummary,
    WorkbenchClaimDetail,
    WorkbenchClaimFilterMetadata,
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
    WorkbenchExternalResultEvidence,
    WorkbenchFieldItem,
    WorkbenchFieldsResponse,
    WorkbenchFilterOption,
    WorkbenchGapStatus,
    WorkbenchHandoffsResponse,
    WorkbenchIncidentSummary,
    WorkbenchIncompleteContext,
    WorkbenchIntegrationSummary,
    WorkbenchMessagesResponse,
    WorkbenchMissingInformation,
    WorkbenchOwnershipProjection,
    WorkbenchPriorityProjection,
    WorkbenchPriorityReason,
    WorkbenchQueueView,
    WorkbenchResourcePage,
    WorkbenchResponsibility,
    WorkbenchRetrievalsResponse,
    WorkbenchRiskSignal,
    WorkbenchSectionSummaries,
    WorkbenchSectionSummary,
    WorkbenchSessionsResponse,
    WorkbenchSignalDetail,
    WorkbenchSignalsResponse,
    WorkbenchSourceItem,
    WorkbenchSourceSummary,
    WorkbenchSourceSummaryStatus,
    WorkbenchStaffSummary,
    WorkbenchTagFilterOption,
    WorkbenchWaitingExternalService,
    WorkbenchWorkItemsResponse,
    WorkbenchWorkSummary,
    WorkPriorityLevel,
)
from backend.domain.workbench_action_registry import (
    WORK_ITEM_TYPE_REGISTRY,
    WORKBENCH_ACTION_REGISTRY_VERSION,
    get_workbench_action_definition,
    handoff_resolution_defaults,
    work_item_defaults,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import decode_cursor, encode_cursor, now_utc
from backend.services.tag_projection import project_staff_tags

ResourceT = TypeVar('ResourceT')

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

_QUEUE_VIEW_LABELS = {
    WorkbenchQueueView.ALL: 'All active work',
    WorkbenchQueueView.URGENT: 'Urgent',
    WorkbenchQueueView.HUMAN_REQUESTS: 'Staff assistance',
    WorkbenchQueueView.INCOMPLETE_CLAIMS: 'Incomplete claims',
    WorkbenchQueueView.READY_TO_PROGRESS: 'Ready to progress',
    WorkbenchQueueView.AWAITING_EVIDENCE: 'Awaiting evidence',
    WorkbenchQueueView.PROFESSIONAL_REVIEW: 'Professional review',
    WorkbenchQueueView.READY_TO_CREATE: 'Ready to create',
    WorkbenchQueueView.CREATED_ROUTED: 'Created and routed',
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
        question_budget=session.question_budget,
        question_turn_count=session.question_turn_count,
        requested_fact_count=session.requested_fact_count,
        repeated_question_count=session.repeated_question_count,
        remaining_question_budget=max(0, session.question_budget - session.question_turn_count),
        post_session_follow_up_required=session.post_session_follow_up_required,
        question_history=session.question_history,
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


def _human_label(value: str) -> str:
    return value.replace('.', ' ').replace('_', ' ').title()


def _unique_refs(*groups: Sequence[str | None]) -> list[str]:
    return list(dict.fromkeys(reference for group in groups for reference in group if reference))


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
    evidence_records: Sequence[EvidenceRecord],
    active_handoffs: Sequence[HandoffRecord],
    staff_actions: Sequence[StaffActionRecord],
    external_tasks: Sequence[ExternalTaskRecord],
    external_limitation: str | None,
) -> list[WorkbenchMissingInformation]:
    items: list[WorkbenchMissingInformation] = []
    represented_codes = set(claim.form)
    for code, field in claim.form.items():
        status = {
            FormStatus.MISSING: WorkbenchGapStatus.MISSING,
            FormStatus.DISPUTED: WorkbenchGapStatus.DISPUTED,
            FormStatus.PENDING_GENERATION: WorkbenchGapStatus.PENDING,
            FormStatus.UNAVAILABLE: WorkbenchGapStatus.UNAVAILABLE,
            FormStatus.PROPOSED: WorkbenchGapStatus.UNCERTAIN,
        }.get(field.status)
        if status is None:
            continue
        current = field.needed_for is NeededFor.CURRENT_ACTION
        items.append(
            WorkbenchMissingInformation(
                kind='field',
                code=code,
                label=_human_label(code),
                status=status,
                attention=(
                    MissingInformationAttention.REQUIRED_NOW
                    if current
                    else MissingInformationAttention.NEEDED_NEXT
                ),
                blocked_action=claim.claim_state.next_action.value if current else None,
                responsible_party=(
                    WorkbenchResponsibility.CLAIMS_PROFESSIONAL
                    if status is WorkbenchGapStatus.DISPUTED
                    else _responsibility(claim.customer_next_step.responsible_party)
                    if current
                    else WorkbenchResponsibility.CLAIMANT
                ),
                source_refs=field.source_refs,
            )
        )
    for evidence in evidence_records:
        represented_codes.update({evidence.evidence_id, evidence.kind})
        status = _evidence_gap_status(evidence)
        if status is None:
            continue
        current = NeededFor.CURRENT_ACTION in evidence.needed_for
        items.append(
            WorkbenchMissingInformation(
                kind='evidence',
                code=evidence.kind,
                label=_human_label(evidence.kind),
                status=status,
                attention=(
                    MissingInformationAttention.REQUIRED_NOW
                    if current
                    else MissingInformationAttention.NEEDED_NEXT
                ),
                blocked_action=(claim.claim_state.next_action.value if current else None),
                responsible_party=_responsibility(evidence.responsible_party),
                source_refs=[evidence.evidence_id],
            )
        )
    for handoff in active_handoffs:
        packet = handoff.packet
        packet_refs = _unique_refs([handoff.handoff_id], packet.source_refs)
        for status, values in (
            (WorkbenchGapStatus.MISSING, packet.missing_items),
            (WorkbenchGapStatus.PENDING, packet.pending_items),
            (WorkbenchGapStatus.CONFLICTING, packet.conflicts),
            (WorkbenchGapStatus.UNCERTAIN, packet.low_confidence_items),
        ):
            for code in values:
                if code in represented_codes:
                    continue
                items.append(
                    WorkbenchMissingInformation(
                        kind='handoff',
                        code=code,
                        label=_human_label(code),
                        status=status,
                        attention=MissingInformationAttention.REQUIRED_NOW,
                        responsible_party=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
                        source_refs=packet_refs,
                    )
                )
    for action in staff_actions:
        if action.status in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}:
            continue
        items.append(
            WorkbenchMissingInformation(
                kind='work_item',
                code=action.action_type,
                label=_human_label(action.action_type),
                status=WorkbenchGapStatus.PENDING,
                attention=MissingInformationAttention.REQUIRED_NOW,
                responsible_party=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
                source_refs=_unique_refs([action.action_id], action.source_refs),
            )
        )
    for task in external_tasks:
        status = _external_gap_status(task)
        if status is None:
            continue
        items.append(
            WorkbenchMissingInformation(
                kind='external_service',
                code=task.service_identity,
                label=_human_label(task.service_identity),
                status=status,
                attention=MissingInformationAttention.FOLLOW_UP,
                blocked_action=(
                    task.requested_action
                    if status in {WorkbenchGapStatus.UNAVAILABLE, WorkbenchGapStatus.UNCERTAIN}
                    else None
                ),
                responsible_party=WorkbenchResponsibility.EXTERNAL_PARTY,
                source_refs=_unique_refs(
                    [task.task_id, task.provider_reference, task.delivery_evidence]
                ),
            )
        )
    if external_limitation:
        items.append(
            WorkbenchMissingInformation(
                kind='external_service',
                code='external_service_records',
                label='External Service Records',
                status=WorkbenchGapStatus.UNAVAILABLE,
                attention=MissingInformationAttention.FOLLOW_UP,
                responsible_party=WorkbenchResponsibility.SYSTEM,
            )
        )
    unique = {(item.kind, item.code, item.status): item for item in items}
    attention_order = {
        MissingInformationAttention.REQUIRED_NOW: 0,
        MissingInformationAttention.NEEDED_NEXT: 1,
        MissingInformationAttention.FOLLOW_UP: 2,
    }
    return sorted(
        unique.values(),
        key=lambda item: (
            attention_order[item.attention],
            item.label.casefold(),
            item.status.value,
        ),
    )


def _evidence_gap_status(evidence: EvidenceRecord) -> WorkbenchGapStatus | None:
    if evidence.status is EvidenceStatus.INCONSISTENT:
        return WorkbenchGapStatus.CONFLICTING
    if evidence.file_status is EvidenceFileStatus.FAILED:
        return WorkbenchGapStatus.UNAVAILABLE
    if evidence.status in {
        EvidenceStatus.PENDING_GENERATION,
        EvidenceStatus.INCOMPLETE,
        EvidenceStatus.UNOFFICIAL,
    } or evidence.file_status in {
        EvidenceFileStatus.AWAITING_UPLOAD,
        EvidenceFileStatus.UPLOADING,
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
    }:
        return WorkbenchGapStatus.PENDING
    return None


def _external_gap_status(task: ExternalTaskRecord) -> WorkbenchGapStatus | None:
    if task.status is ExternalTaskOperationStatus.ACCEPTED:
        return None
    if task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        return WorkbenchGapStatus.UNCERTAIN
    if task.failure_code is ExternalTaskFailureCode.CONFLICTING:
        return WorkbenchGapStatus.CONFLICTING
    if task.status in {
        ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    }:
        return WorkbenchGapStatus.UNAVAILABLE
    return WorkbenchGapStatus.PENDING


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
            ExternalTaskOperationStatus.ACCEPTED,
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


def _registered_action(
    action_code: str,
    target_ref: str,
    revision: int,
    *,
    availability: ActionAvailability = ActionAvailability.CONFIRMATION_REQUIRED,
    blocked_reason: str | None = None,
    source_refs: Sequence[str] = (),
    payload_defaults: dict[str, Any] | None = None,
    additional_inputs: Sequence[WorkbenchActionInput] = (),
    result_state: str = 'awaiting_input',
) -> WorkbenchAllowedAction:
    definition = get_workbench_action_definition(action_code)
    inputs = [
        WorkbenchActionInput(
            field_code=item.field_code,
            label=item.label,
            control=item.control,
            required=item.required,
            required_when=(
                WorkbenchActionInputCondition(
                    field_code=item.required_when[0],
                    equals=item.required_when[1],
                )
                if item.required_when is not None
                else None
            ),
            choices=[
                WorkbenchActionInputChoice(value=value, label=label)
                for value, label in item.choices
            ],
        )
        for item in definition.inputs
    ]
    inputs.extend(additional_inputs)
    return WorkbenchAllowedAction(
        registry_version=WORKBENCH_ACTION_REGISTRY_VERSION,
        action_code=definition.action_code,
        target_type=definition.target_type.value,
        target_ref=target_ref,
        label=definition.label,
        purpose=definition.purpose,
        availability=availability,
        blocked_reason=blocked_reason,
        confirmation=WorkbenchActionConfirmation(
            level=definition.confirmation_level,
            message=definition.confirmation_message,
        ),
        expected_effects=list(definition.expected_effects),
        claimant_visible_effects=list(definition.claimant_visible_effects),
        failure_codes=list(definition.failure_codes),
        audit_requirements=list(definition.audit_requirements),
        source_refs=list(source_refs),
        inputs=inputs,
        payload_defaults=payload_defaults or {},
        result_state=result_state,
        based_on_revision=revision,
    )


def _allowed_actions(
    claim: WorkingClaim,
    ownership: WorkbenchOwnershipProjection,
    active_handoffs: Sequence[HandoffRecord],
    staff_actions: Sequence[StaffActionRecord],
    risk_signals: Sequence[WorkbenchRiskSignal],
    collaboration_requests: Sequence[ClaimCollaborationRequest],
    external_tasks: Sequence[ExternalTaskRecord],
    principal: Principal,
) -> list[WorkbenchAllowedAction]:
    actions: list[WorkbenchAllowedAction] = []
    if active_handoffs:
        handoff = active_handoffs[-1]
        if handoff.status is HandoffStatus.QUEUED:
            effective_owner = (
                ownership.primary_assignee.staff_id if ownership.primary_assignee else None
            )
            blocked = effective_owner not in {None, principal.subject}
            actions.append(
                _registered_action(
                    'human.accept_handoff',
                    handoff.handoff_id,
                    claim.revision,
                    availability=(
                        ActionAvailability.BLOCKED
                        if blocked
                        else ActionAvailability.CONFIRMATION_REQUIRED
                    ),
                    blocked_reason=(
                        'This work is assigned to another staff member.' if blocked else None
                    ),
                    source_refs=[handoff.handoff_id],
                    result_state='pending_confirmation',
                )
            )
        elif ownership.current_staff_access in {
            CurrentStaffAccess.PRIMARY,
            CurrentStaffAccess.COWORKER,
        }:
            actions.append(
                _registered_action(
                    'conversation.send_claimant_message',
                    claim.active_session_id or handoff.handoff_id,
                    claim.revision,
                    availability=(
                        ActionAvailability.CONFIRMATION_REQUIRED
                        if claim.active_session_id
                        else ActionAvailability.BLOCKED
                    ),
                    blocked_reason=None
                    if claim.active_session_id
                    else 'No active claimant session is available.',
                    source_refs=[handoff.handoff_id],
                )
            )
            if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
                actions.append(
                    _registered_action(
                        'human.resolve_handoff',
                        handoff.handoff_id,
                        claim.revision,
                        source_refs=[handoff.handoff_id],
                        payload_defaults=handoff_resolution_defaults(handoff),
                    )
                )
    if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
        for signal in risk_signals:
            if signal.status not in {SignalReviewStatus.OPEN, SignalReviewStatus.UNDER_REVIEW}:
                continue
            actions.append(
                _registered_action(
                    'signal.record_decision',
                    signal.signal_id,
                    claim.revision,
                    source_refs=signal.source_refs,
                    payload_defaults={'evidence_refs': signal.source_refs},
                )
            )
    if ownership.current_staff_access in {CurrentStaffAccess.PRIMARY, CurrentStaffAccess.COWORKER}:
        creation_source_refs = list(
            active_handoffs[-1].packet.source_refs if active_handoffs else []
        )
        for signal in risk_signals:
            creation_source_refs.extend(signal.source_refs)
        creation_source_refs = list(dict.fromkeys(creation_source_refs))
        actions.append(
            _registered_action(
                'work_item.create',
                claim.claim_id,
                claim.revision,
                source_refs=creation_source_refs,
            )
        )
    for staff_action in staff_actions:
        if staff_action.status in {StaffActionStatus.COMPLETED, StaffActionStatus.CANCELLED}:
            continue
        if staff_action.assigned_to != principal.subject:
            continue
        if staff_action.action_type not in WORK_ITEM_TYPE_REGISTRY:
            continue
        additional_inputs = []
        if work_item_defaults(staff_action)['customer_update'] is not None:
            additional_inputs.append(
                WorkbenchActionInput(
                    field_code='customer_update.summary',
                    label='Claimant update',
                    control='textarea',
                    required=False,
                    required_when=WorkbenchActionInputCondition(
                        field_code='status',
                        equals='completed',
                    ),
                )
            )
        actions.append(
            _registered_action(
                'work_item.update',
                staff_action.action_id,
                claim.revision,
                source_refs=staff_action.source_refs,
                additional_inputs=additional_inputs,
                payload_defaults=work_item_defaults(staff_action),
            )
        )
    if (
        ownership.current_staff_access is CurrentStaffAccess.READ_ONLY
        and ownership.primary_assignee
    ):
        actions.append(
            _registered_action('ownership.request_cowork', claim.claim_id, claim.revision)
        )
    if ownership.current_staff_access is CurrentStaffAccess.PRIMARY:
        requeue_blocker = None
        if any(item.status is StaffActionStatus.IN_PROGRESS for item in staff_actions):
            requeue_blocker = (
                'Complete or pause in-progress staff work before returning this Claim.'
            )
        elif any(
            item.status
            in {
                ExternalTaskOperationStatus.PREPARED,
                ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            }
            for item in external_tasks
        ):
            requeue_blocker = 'Resolve the active external operation before returning this Claim.'
        actions.extend(
            [
                _registered_action('ownership.invite_cowork', claim.claim_id, claim.revision),
                _registered_action('ownership.request_transfer', claim.claim_id, claim.revision),
                _registered_action(
                    'ownership.requeue',
                    claim.claim_id,
                    claim.revision,
                    availability=(
                        ActionAvailability.BLOCKED
                        if requeue_blocker
                        else ActionAvailability.CONFIRMATION_REQUIRED
                    ),
                    blocked_reason=requeue_blocker,
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
        actions.append(
            _registered_action(
                f'ownership.decide_{request.kind.value}',
                request.request_id,
                claim.revision,
                source_refs=[request.request_id],
            )
        )
    return actions


def _source_summary(
    claim: WorkingClaim,
    evidence_records: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
    staff_actions: Sequence[StaffActionRecord],
    allowed_actions: Sequence[WorkbenchAllowedAction],
    external_tasks: Sequence[ExternalTaskRecord],
    external_limitation: str | None,
) -> WorkbenchSourceSummary:
    items: list[WorkbenchSourceItem] = []
    source_labels = {
        'claimant': 'Claimant statement',
        'image': 'Image evidence',
        'document': 'Document evidence',
        'policy': 'Policy record',
        'claim_history': 'Claim history',
        'inference': 'Agent inference',
        'staff': 'Staff record',
        'external_system': 'External system',
        'fixture': 'Controlled fixture service',
        'configured_service': 'Configured external service',
    }
    for code, field in claim.form.items():
        label = _human_label(code)
        items.append(
            WorkbenchSourceItem(
                kind='field',
                record_ref=f'field:{code}',
                label=label,
                context=(
                    f'{label} is recorded for the {_human_label(field.needed_for.value).lower()}.'
                ),
                source_label=source_labels[field.source.value],
                status=field.status.value,
                source_refs=field.source_refs,
                needed_for=[field.needed_for.value],
                confidence=field.confidence,
                updated_at=field.updated_at,
            )
        )
    for evidence in evidence_records:
        related = [_human_label(code) for code in evidence.related_fields]
        context = (
            evidence.context_summary
            or evidence.claimant_note
            or (
                f'Evidence linked to {", ".join(related)}.'
                if related
                else 'Evidence recorded for this Claim.'
            )
        )
        provenance_refs = [
            value for value in evidence.provenance.values() if isinstance(value, str)
        ]
        items.append(
            WorkbenchSourceItem(
                kind='evidence',
                record_ref=evidence.evidence_id,
                label=_human_label(evidence.kind),
                context=context,
                source_label=source_labels[evidence.source.value],
                status=evidence.status.value,
                source_refs=_unique_refs([evidence.evidence_id], provenance_refs),
                related_fields=evidence.related_fields,
                needed_for=[str(value) for value in evidence.needed_for],
                responsible_party=_responsibility(evidence.responsible_party),
                updated_at=evidence.updated_at,
            )
        )
    for handoff in handoffs:
        items.append(
            WorkbenchSourceItem(
                kind='handoff',
                record_ref=handoff.handoff_id,
                label=f'{_human_label(handoff.type.value)} Handoff',
                context=handoff.requested_action,
                source_label='Claim handoff',
                status=handoff.status.value,
                source_refs=_unique_refs(
                    [handoff.handoff_id, handoff.source_message_id],
                    handoff.packet.source_refs,
                ),
                responsible_party=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
                updated_at=handoff.resolved_at or handoff.accepted_at or handoff.created_at,
            )
        )
    for work_item in staff_actions:
        items.append(
            WorkbenchSourceItem(
                kind='work_item',
                record_ref=work_item.action_id,
                label=_human_label(work_item.action_type),
                context=work_item.requested_outcome,
                source_label='Staff work item',
                status=work_item.status.value,
                source_refs=_unique_refs([work_item.action_id], work_item.source_refs),
                responsible_party=WorkbenchResponsibility.CLAIMS_PROFESSIONAL,
                updated_at=work_item.completed_at or work_item.created_at,
            )
        )
    for task in external_tasks:
        items.append(
            WorkbenchSourceItem(
                kind='external_service',
                record_ref=task.task_id,
                label=_human_label(task.service_identity),
                context=_human_label(task.requested_action),
                source_label=source_labels[task.integration_source.value],
                status=task.status.value,
                source_refs=_unique_refs(
                    [task.task_id, task.provider_reference, task.delivery_evidence]
                ),
                responsible_party=WorkbenchResponsibility.EXTERNAL_PARTY,
                updated_at=task.updated_at,
            )
        )
    for projected_action in allowed_actions:
        if not projected_action.source_refs:
            continue
        items.append(
            WorkbenchSourceItem(
                kind='authorised_action',
                record_ref=(f'{projected_action.action_code}:{projected_action.target_ref}'),
                label=projected_action.label,
                context=projected_action.purpose,
                source_label='Runtime action projection',
                status=projected_action.availability.value,
                source_refs=projected_action.source_refs,
            )
        )
    if items:
        status = (
            WorkbenchSourceSummaryStatus.PARTIAL
            if external_limitation
            else WorkbenchSourceSummaryStatus.AVAILABLE
        )
    else:
        status = (
            WorkbenchSourceSummaryStatus.UNAVAILABLE
            if external_limitation
            else WorkbenchSourceSummaryStatus.EMPTY
        )
    return WorkbenchSourceSummary(
        status=status,
        items=items,
        limitation=external_limitation,
    )


def require_workbench_action(
    repository: PersistenceRepository,
    principal: Principal,
    claim: WorkingClaim,
    expected_revision: int,
    action_code: str,
    target_ref: str,
) -> WorkbenchAllowedAction:
    """Resolve an executable action from the current Workbench projection.

    Args:
        repository: Authoritative persistence boundary.
        principal: Authenticated staff principal.
        claim: Current internal Claim record.
        expected_revision: Revision supplied by the mutation request.
        action_code: Exact registered action code represented by the endpoint.
        target_ref: Exact resource target represented by the endpoint.

    Returns:
        The current projected action envelope.

    Raises:
        ApiError: The revision is stale or the exact action is not executable.
    """
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    projection = _build_projection(repository, principal, claim, include_detail=True)
    assert isinstance(projection, WorkbenchClaimDetail)
    action = next(
        (
            item
            for item in projection.allowed_actions
            if item.action_code == action_code and item.target_ref == target_ref
        ),
        None,
    )
    if (
        action is None
        or action.availability is ActionAvailability.BLOCKED
        or action.based_on_revision != expected_revision
    ):
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The requested action is not available in the current Workbench projection.',
            details=[
                ErrorDetail(field='action_code', reason=action_code),
                ErrorDetail(field='target_ref', reason=target_ref),
            ],
        )
    if (
        action.availability is ActionAvailability.CONFIRMATION_REQUIRED
        and action.confirmation.level.value == 'none'
    ):
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The requested action has an invalid confirmation contract.',
            details=[ErrorDetail(field='action_code', reason=action_code)],
        )
    return action


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
                if handoff.status is HandoffStatus.QUEUED
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
                and action.availability is not ActionAvailability.BLOCKED
            ),
            None,
        )
        if match is not None:
            return match
    return None


def get_workbench_claim_filter_metadata(
    principal: Principal,
) -> WorkbenchClaimFilterMetadata:
    """Return the canonical options supported by the staff queue.

    Args:
        principal: Authenticated staff principal.

    Returns:
        Backend-owned labels and values for every queue filter.

    Raises:
        ApiError: The caller is not an authenticated staff principal.
    """

    if principal.actor_type != 'staff':
        raise _staff_access_required()
    return WorkbenchClaimFilterMetadata(
        views=[
            WorkbenchFilterOption(value=value.value, label=_QUEUE_VIEW_LABELS[value])
            for value in WorkbenchQueueView
        ],
        workflow_states=[
            WorkbenchFilterOption(
                value=value.value,
                label=value.value.replace('_', ' ').capitalize(),
            )
            for value in WorkflowState
        ],
        priorities=[
            WorkbenchFilterOption(value=value.value, label=value.value.capitalize())
            for value in WorkPriorityLevel
        ],
        tags=[
            WorkbenchTagFilterOption(
                value=definition.code,
                label=definition.staff_label,
                category=definition.category.value,
            )
            for definition in list_filterable_staff_tag_definitions()
        ],
        tag_registry_version=TAG_REGISTRY_VERSION,
    )


def _matches_view(item: WorkbenchClaimListItem, view: WorkbenchQueueView | None) -> bool:
    if view is None or view is WorkbenchQueueView.ALL:
        return True
    if view is WorkbenchQueueView.URGENT:
        return item.priority_projection.level in {
            WorkPriorityLevel.IMMEDIATE,
            WorkPriorityLevel.URGENT,
        }
    if view is WorkbenchQueueView.HUMAN_REQUESTS:
        return item.work_summary.queue_key == 'claimant_support'
    if view is WorkbenchQueueView.AWAITING_EVIDENCE:
        return any(
            value.kind == 'evidence' and value.status is WorkbenchGapStatus.PENDING
            for value in item.work_summary.missing_information
        )
    if view is WorkbenchQueueView.INCOMPLETE_CLAIMS:
        return item.work_summary.queue_key == 'incomplete_claims'
    if view is WorkbenchQueueView.READY_TO_CREATE:
        return item.lifecycle_state is ClaimLifecycleState.READY_TO_CREATE
    return item.work_summary.queue_key == view.value


def _matches_search(item: WorkbenchClaimListItem, search: str | None) -> bool:
    if search is None:
        return True
    query = search.strip().casefold()
    if not query:
        return True
    values = [
        item.claim_id,
        item.display_reference,
        item.incident.family,
        item.incident.summary,
        (
            item.work_summary.current_work_item.requested_outcome
            if item.work_summary.current_work_item is not None
            else None
        ),
    ]
    values.extend(tag.code for tag in item.tags)
    values.extend(tag.label for tag in item.tags)
    return any(query in value.casefold() for value in values if value)


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
    integration_summary = _integration_summary(claim, external_tasks)
    computed_at = now_utc()
    collaboration_requests = repository.list_collaboration_requests(claim.claim_id)
    ownership = _ownership(repository, claim, principal, active_handoffs)
    missing = _missing_information(
        claim,
        evidence,
        active_handoffs,
        actions,
        external_tasks,
        external_limitation,
    )
    current_work = _current_work_item(active_handoffs, actions)
    allowed_actions = _allowed_actions(
        claim,
        ownership,
        active_handoffs,
        actions,
        projected_risk_signals,
        collaboration_requests,
        external_tasks,
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
        external_wait_count=len(integration_summary.waiting_external_services),
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
        integration_summary=integration_summary,
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
        contents_items=claim.contents_items,
        source_summary=_source_summary(
            claim,
            evidence,
            handoffs,
            actions,
            allowed_actions,
            external_tasks,
            external_limitation,
        ),
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
    view: WorkbenchQueueView | None = None,
    workflow_state: WorkflowState | None = None,
    priority: WorkPriorityLevel | None = None,
    tag: str | None = None,
    search: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> WorkbenchClaimListResponse:
    if principal.actor_type != 'staff':
        raise _staff_access_required()
    if tag is not None:
        try:
            get_filterable_staff_tag_definition(tag)
        except ValueError as error:
            raise ApiError(
                status_code=400,
                code='INVALID_TAG_FILTER',
                message='The requested staff tag is not available as a queue filter.',
                details=[ErrorDetail(field='tag', reason=tag)],
            ) from error
    items: list[WorkbenchClaimListItem] = []
    for claim in repository.list_claims_internal():
        projected = _build_projection(repository, principal, claim, include_detail=False)
        assert isinstance(projected, WorkbenchClaimListItem)
        if not _matches_view(projected, view):
            continue
        if workflow_state is not None and projected.workflow_state is not workflow_state:
            continue
        if priority is not None and projected.priority_projection.level is not priority:
            continue
        if tag is not None and all(item.code != tag for item in projected.tags):
            continue
        if not _matches_search(projected, search):
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
    result: ExternalTaskResult | None = None,
    result_evidence: Sequence[EvidenceRecord] = (),
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
    if result is not None and status is not ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        verification = result.verification.value
        owner = WorkbenchResponsibility.CLAIMS_PROFESSIONAL
        if result.verification is ExternalTaskResultVerification.UNVERIFIED:
            label = 'Result awaiting verification'
            detail = 'A provider result is recorded but has not been checked against the Claim.'
            next_action = 'Verify the returned result against its evidence and the current Claim.'
            attention = True
        elif result.verification is ExternalTaskResultVerification.CONSISTENT:
            label = 'Result checked'
            detail = (
                'The returned result was checked as consistent evidence; it is not Claim State.'
            )
            next_action = 'Use the checked result only through an authorised Claim decision.'
            attention = False
        elif result.verification is ExternalTaskResultVerification.INCONSISTENT:
            label = 'Result conflicts with Claim'
            detail = 'The returned result was checked and conflicts with the Claim.'
            next_action = 'Review the conflicting result and cited evidence before continuing.'
            attention = True
        else:
            label = 'Result requires review'
            detail = 'The returned result needs professional review before it can be used.'
            next_action = 'Review the result, evidence, and checked Claim revision.'
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
        provider_reference=task.provider_reference,
        result=result.summary if result is not None else None,
        result_source=result.source if result is not None else None,
        result_verification_state=result.verification if result is not None else None,
        result_received_at=result.received_at if result is not None else None,
        result_verified_at=result.verified_at if result is not None else None,
        result_verified_against_revision=(
            result.verified_against_revision if result is not None else None
        ),
        result_evidence_ids=result.evidence_ids if result is not None else [],
        result_evidence=[
            WorkbenchExternalResultEvidence(
                evidence_id=item.evidence_id,
                status=item.status,
                file_status=item.file_status,
            )
            for item in result_evidence
        ],
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
    claim = _authorised_claim(repository, principal, claim_id)
    try:
        tasks = repository.list_external_tasks_internal(claim_id)
        requests = repository.list_external_task_requests_internal(claim_id)
        results = repository.list_external_task_results_internal(claim_id)
        evidence = repository.list_evidence(claim_id, claim.customer_id)
    except RuntimeError:
        return WorkbenchResourcePage(
            items=[],
            page={'next_cursor': None},
            status=ResourceAvailability.UNAVAILABLE,
            limitation='External-service records are temporarily unavailable.',
        )
    by_task = {item.task_id: item for item in requests}
    results_by_task = {item.task_id: item for item in results}
    evidence_by_id = {item.evidence_id: item for item in evidence}
    items = []
    for task in tasks:
        external_request = by_task.get(task.task_id)
        result = results_by_task.get(task.task_id)
        items.append(
            WorkbenchExternalRequest(
                request=external_request,
                task=task,
                lifecycle=_external_lifecycle(
                    task,
                    external_request,
                    result,
                    [
                        evidence_by_id[evidence_id]
                        for evidence_id in result.evidence_ids
                        if evidence_id in evidence_by_id
                    ]
                    if result is not None
                    else [],
                ),
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
