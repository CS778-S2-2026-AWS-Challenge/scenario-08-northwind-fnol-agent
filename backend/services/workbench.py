from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import (
    AgentDecisionRecord,
    MessageRecord,
    SessionRecord,
    WorkbenchClaimDetail,
    WorkbenchSession,
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


def _claim_messages_and_decisions(
    repository: PersistenceRepository,
    claim_id: str,
    customer_id: str,
    sessions: list[SessionRecord],
) -> tuple[list[MessageRecord], list[AgentDecisionRecord]]:
    messages: list[MessageRecord] = []
    decisions_by_id: dict[str, AgentDecisionRecord] = {}
    for session in sessions:
        session_messages = repository.list_messages(
            claim_id,
            session.session_id,
            customer_id,
        )
        messages.extend(session_messages)
        for message in session_messages:
            decision = repository.find_agent_decision_for_trigger(
                claim_id,
                message.message_id,
                customer_id,
            )
            if decision is not None:
                decisions_by_id[decision.decision_id] = decision

    messages.sort(key=lambda item: (item.created_at, item.message_id))
    decisions = sorted(
        decisions_by_id.values(),
        key=lambda item: (item.created_at, item.decision_id),
    )
    return messages, decisions


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
    messages, decisions = _claim_messages_and_decisions(
        repository,
        claim_id,
        claim.customer_id,
        sessions,
    )
    evidence = repository.list_evidence(claim_id, claim.customer_id)
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
        handoffs=[],
        staff_actions=[],
        customer_updates=[],
        external_claim=claim.external_claim,
        assessor_routing=claim.assessor_routing,
        customer_next_step=claim.customer_next_step,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
