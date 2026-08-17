from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import (
    HandoffPriority,
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    WorkbenchClaimDetail,
    WorkbenchClaimListItem,
    WorkbenchClaimListResponse,
    WorkbenchHandoff,
    WorkbenchSession,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository


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
    claim_id: str,
    customer_id: str,
    sessions: list[SessionRecord],
) -> list[MessageRecord]:
    messages: list[MessageRecord] = []
    for session in sessions:
        messages.extend(
            repository.list_messages(
                claim_id,
                session.session_id,
                customer_id,
            )
        )

    actor_order = {'claimant': 0, 'agent': 1, 'staff': 2, 'system': 3}
    messages.sort(
        key=lambda item: (item.created_at, actor_order[item.actor.value], item.message_id)
    )
    return messages


def _queue_for_claim(claim: WorkingClaim) -> str:
    workflow_state = claim.claim_state.workflow_state
    return {
        WorkflowState.COLLECTING: 'new_untriaged',
        WorkflowState.READY_FOR_NEXT: 'ready_to_progress',
        WorkflowState.AWAITING_EVIDENCE: 'awaiting_evidence',
        WorkflowState.PROFESSIONAL_REVIEW: 'professional_review',
        WorkflowState.CREATED: 'created_routed',
    }[workflow_state]


def list_workbench_claims(
    repository: PersistenceRepository,
    principal: Principal,
    view: str | None = None,
) -> WorkbenchClaimListResponse:
    if principal.actor_type != 'staff':
        raise _staff_access_required()

    items: list[WorkbenchClaimListItem] = []
    for claim in repository.list_claims_internal():
        handoffs = repository.list_handoffs(claim.claim_id, claim.customer_id)
        open_handoffs = [
            handoff for handoff in handoffs if handoff.status.value not in {'resolved', 'cancelled'}
        ]
        queue = _queue_for_claim(claim)
        priority = max(
            (handoff.priority for handoff in open_handoffs),
            default=HandoffPriority.STANDARD,
            key=lambda value: list(HandoffPriority).index(value),
        )
        assignee_id = next(
            (handoff.assigned_to for handoff in open_handoffs if handoff.assigned_to),
            None,
        )
        if view and view != 'all' and view != queue:
            continue
        items.append(
            WorkbenchClaimListItem(
                claim_id=claim.claim_id,
                revision=claim.revision,
                customer_reference=claim.customer_id,
                incident_type=claim.incident_type,
                workflow_state=claim.claim_state.workflow_state,
                queue=queue,
                priority=priority,
                next_action=claim.claim_state.next_action,
                evidence_summary=claim.evidence_summary,
                open_handoff_count=len(open_handoffs),
                assignee_id=assignee_id,
                created_at=claim.created_at,
                updated_at=claim.updated_at,
            )
        )
    return WorkbenchClaimListResponse(items=items, page={'next_cursor': None})


def get_workbench_claim_detail(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkbenchClaimDetail:
    if principal.actor_type != 'staff':
        raise _staff_access_required()

    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()

    sessions = repository.list_sessions_for_claim(claim_id, claim.customer_id)
    messages = _claim_messages(
        repository,
        claim_id,
        claim.customer_id,
        sessions,
    )
    decisions = repository.list_agent_decisions(claim_id, claim.customer_id)
    evidence = repository.list_evidence(claim_id, claim.customer_id)
    signals_by_id: dict[str, dict[str, object]] = {}
    for decision in decisions:
        for signal in decision.proposed_signals:
            signal_id = str(signal.get('signal_id') or signal.get('code') or '')
            if signal_id:
                signals_by_id[signal_id] = dict(signal)
    for message in messages:
        if message.content.get('type') == 'review_signal':
            signal_id = str(message.content.get('signal_id') or message.content.get('code') or '')
            if signal_id:
                signals_by_id.setdefault(signal_id, dict(message.content))
    for signal_decision in repository.list_signal_decisions(claim_id):
        signal = signals_by_id.setdefault(
            signal_decision.signal_id,
            {'signal_id': signal_decision.signal_id},
        )
        signal.setdefault('decisions', [])
        decisions_list = signal['decisions']
        if isinstance(decisions_list, list):
            decisions_list.append(signal_decision.model_dump(mode='json'))
    signals = list(signals_by_id.values())
    handoffs = repository.list_handoffs(claim_id, claim.customer_id)

    return WorkbenchClaimDetail(
        claim_id=claim.claim_id,
        revision=claim.revision,
        customer_reference=claim.customer_id,
        channel=claim.channel,
        locale=claim.locale,
        incident_type=claim.incident_type,
        claim_state=claim.claim_state,
        form=claim.form,
        route=claim.route,
        active_session_id=claim.active_session_id,
        evidence_summary=claim.evidence_summary,
        evidence=evidence,
        sessions=[_workbench_session(session) for session in sessions],
        messages=messages,
        decisions=decisions,
        signals=signals,
        handoffs=[workbench_handoff(handoff) for handoff in handoffs],
        staff_actions=[
            item.model_dump(mode='json') for item in repository.list_staff_actions(claim_id)
        ],
        customer_updates=[
            item.model_dump(mode='json') for item in repository.list_customer_updates(claim_id)
        ],
        external_claim=claim.external_claim,
        assessor_routing=claim.assessor_routing,
        customer_next_step=claim.customer_next_step,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
