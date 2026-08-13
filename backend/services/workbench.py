from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import (
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    Urgency,
    WorkbenchClaimDetail,
    WorkbenchClaimItem,
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


def _workbench_handoff(handoff: HandoffRecord) -> WorkbenchHandoff:
    return WorkbenchHandoff(
        handoff_id=handoff.handoff_id,
        claim_id=handoff.claim_id,
        type=handoff.type,
        status=handoff.status,
        priority=handoff.priority,
        queue=handoff.queue,
        support_need=handoff.support_need,
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

    messages.sort(key=lambda item: (item.created_at, item.message_id))
    return messages


def _queue_for(claim: WorkingClaim) -> str:
    if claim.claim_state.workflow_state == WorkflowState.PROFESSIONAL_REVIEW:
        return 'professional_review'
    if claim.claim_state.workflow_state == WorkflowState.AWAITING_EVIDENCE:
        return 'awaiting_evidence'
    if claim.claim_state.workflow_state == WorkflowState.READY_FOR_NEXT:
        return 'ready_to_progress'
    if claim.claim_state.workflow_state == WorkflowState.CREATED:
        return 'created_routed'
    return 'new_untriaged'


def _priority_for(claim: WorkingClaim) -> str:
    if claim.claim_state.urgency == Urgency.URGENT:
        return 'urgent'
    return 'standard'


def _internal_flags_for(claim: WorkingClaim) -> list[str]:
    if claim.claim_state.fraud_signal.value == 'review_required':
        return ['FRAUD_REVIEW_REQUIRED']
    return []


def list_workbench_claims(
    repository: PersistenceRepository,
    principal: Principal,
    view: str | None = None,
) -> WorkbenchClaimListResponse:
    """List all claims available to staff workbench.

    Returns a summary view of each claim suitable for workbench queue display.
    This is a lightweight projection compared to get_workbench_claim_detail.
    """
    if principal.actor_type != 'staff':
        raise _staff_access_required()

    claims = repository.list_claims()
    items: list[WorkbenchClaimItem] = []
    for claim in claims:
        queue = _queue_for(claim)
        if view is not None and view != 'all' and queue != view:
            continue
        handoffs = repository.list_handoffs(claim.claim_id, claim.customer_id)
        assigned_handoff = next(
            (handoff for handoff in handoffs if handoff.assigned_to),
            None,
        )
        items.append(
            WorkbenchClaimItem(
                claim_id=claim.claim_id,
                revision=claim.revision,
                customer_reference=claim.customer_id,
                incident_type=claim.incident_type,
                workflow_state=claim.claim_state.workflow_state,
                customer_next_step=claim.customer_next_step,
                assigned_to=assigned_handoff.assigned_to if assigned_handoff else None,
                internal_flags=_internal_flags_for(claim),
                queue=queue,
                priority=_priority_for(claim),
                created_at=claim.created_at,
                updated_at=claim.updated_at,
            )
        )

    return WorkbenchClaimListResponse(items=items, page=None)


def get_workbench_claim_detail(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkbenchClaimDetail:
    """Get complete workbench detail for a claim.

    Reads and projects all persisted claim state: sessions, messages,
    evidence, decisions, signals, handoffs, external routing results,
    and customer next steps.
    """
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
    handoffs = repository.list_handoffs(claim_id, claim.customer_id)
    signals = [signal for decision in decisions for signal in decision.proposed_signals]

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
        handoffs=[_workbench_handoff(handoff) for handoff in handoffs],
        staff_actions=[],
        customer_updates=[],
        external_claim=claim.external_claim,
        assessor_routing=claim.assessor_routing,
        customer_next_step=claim.customer_next_step,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
