from backend.adapters.handoff_dispatch import (
    HandoffDispatchAdapter,
    HandoffDispatchReceipt,
    HandoffDispatchUnavailable,
    local_queue_receipt,
)
from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    AgentAction,
    ClaimantHandoff,
    CreateSupportRequest,
    CustomerNextStep,
    CustomerSupport,
    FormStatus,
    HandoffDelivery,
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    MessageVisibility,
    PreferredChannel,
    ResponsibleParty,
    SupportNeed,
    SupportRequestResponse,
    Urgency,
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

ACTIVE_HANDOFF_STATUSES = {
    HandoffStatus.REQUESTED,
    HandoffStatus.QUEUED,
    HandoffStatus.ACCEPTED,
    HandoffStatus.IN_PROGRESS,
}


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def claimant_handoff(handoff: HandoffRecord) -> ClaimantHandoff:
    if handoff.support_need is None:
        raise ValueError('An internal handoff cannot be projected as a claimant support request.')
    return ClaimantHandoff(
        handoff_id=handoff.handoff_id,
        status=handoff.status,
        priority=handoff.priority,
        support_need=handoff.support_need,
        summary=handoff.packet.promised_next_step,
        created_at=handoff.created_at,
    )


def _response(
    handoff: HandoffRecord,
    claim: WorkingClaim,
    receipt: HandoffDispatchReceipt,
) -> SupportRequestResponse:
    return SupportRequestResponse(
        handoff=claimant_handoff(handoff),
        revision=claim.revision,
        customer_next_step=claim.customer_next_step,
        delivery=HandoffDelivery(
            state=receipt.state,
            limitations=list(receipt.limitations),
        ),
    )


def notify_staff_queue(
    dispatch: HandoffDispatchAdapter,
    handoff: HandoffRecord,
) -> HandoffDispatchReceipt:
    """Notify the staff queue system, falling back to the persisted queue.

    Dispatch runs only after the handoff is durable. A notification outage
    therefore degrades delivery, never the request: the Workbench queue is
    derived from persisted claim state, so staff still see the handoff.
    """

    try:
        return dispatch.dispatch(handoff)
    except HandoffDispatchUnavailable:
        return local_queue_receipt()


def _handoff_settings(
    support_need: SupportNeed,
) -> tuple[HandoffType, HandoffPriority, str, AgentAction, str, str]:
    if support_need is SupportNeed.URGENT:
        return (
            HandoffType.URGENT_SUPPORT,
            HandoffPriority.URGENT,
            'urgent_support',
            AgentAction.URGENT_HANDOFF,
            'URGENT_SUPPORT_REQUESTED',
            (
                'Move to a safer place if you can do so safely. Contact local emergency services '
                'yourself if immediate help is needed. Northwind urgent support has been requested '
                'with the details already provided.'
            ),
        )
    if support_need is SupportNeed.DISTRESS:
        return (
            HandoffType.HUMAN_SUPPORT,
            HandoffPriority.HIGH,
            'claimant_support',
            AgentAction.HANDOFF,
            'DISTRESS_SUPPORT_REQUESTED',
            'A Northwind support request has been prioritised with the details already provided.',
        )
    if support_need is SupportNeed.ACCESSIBILITY_REQUIRED:
        return (
            HandoffType.HUMAN_SUPPORT,
            HandoffPriority.HIGH,
            'claimant_support',
            AgentAction.HANDOFF,
            'ACCESSIBILITY_SUPPORT_REQUESTED',
            (
                'A Northwind accessibility support request has been prioritised with the details '
                'already provided.'
            ),
        )
    return (
        HandoffType.HUMAN_SUPPORT,
        HandoffPriority.STANDARD,
        'claimant_support',
        AgentAction.HANDOFF,
        'HUMAN_SUPPORT_REQUESTED',
        (
            'A Northwind support request has been queued with the details already provided. '
            'You do not need to restart your report.'
        ),
    )


def _claimant_handoff_trigger(support_need: SupportNeed) -> HandoffTrigger:
    return {
        SupportNeed.HUMAN_REQUESTED: HandoffTrigger.CLAIMANT_SUPPORT_REQUEST,
        SupportNeed.ACCESSIBILITY_REQUIRED: HandoffTrigger.ACCESSIBILITY_NEED,
        SupportNeed.DISTRESS: HandoffTrigger.DISTRESS_SIGNAL,
        SupportNeed.URGENT: HandoffTrigger.URGENT_SAFETY_RISK,
    }[support_need]


def build_handoff(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    support_need: SupportNeed,
    reason: str,
    preferred_channel: PreferredChannel | None,
    source_message_id: str | None,
    reason_code: str | None = None,
) -> tuple[HandoffRecord, CustomerNextStep]:
    handoff_type, priority, queue, action, default_reason_code, promised_next_step = (
        _handoff_settings(support_need)
    )
    timestamp = now_utc()
    evidence = repository.list_evidence(claim.claim_id, claim.customer_id)
    messages = (
        repository.list_messages(
            claim.claim_id,
            claim.active_session_id,
            claim.customer_id,
        )
        if claim.active_session_id is not None
        else []
    )
    form_values = list(claim.form.items())
    incident_field = claim.form.get('incident.description')
    source_refs = sorted(
        {source_ref for field in claim.form.values() for source_ref in field.source_refs}
        | ({source_message_id} if source_message_id else set())
    )
    packet = HandoffPacket(
        incident_summary=(
            str(incident_field.value)
            if incident_field is not None and incident_field.status is FormStatus.CONFIRMED
            else None
        ),
        form_revision=claim.revision,
        form_snapshot=claim.form,
        evidence_refs=[record.evidence_id for record in evidence],
        missing_items=[code for code, field in form_values if field.status is FormStatus.MISSING],
        pending_items=[
            code for code, field in form_values if field.status is FormStatus.PENDING_GENERATION
        ]
        + [
            record.evidence_id for record in evidence if record.status.value == 'pending_generation'
        ],
        conflicts=[code for code, field in form_values if field.status is FormStatus.DISPUTED],
        low_confidence_items=[
            code
            for code, field in form_values
            if field.confidence is not None and field.confidence < 0.8
        ],
        source_refs=source_refs,
        prior_customer_updates=[
            str(message.content.get('text'))
            for message in messages
            if message.actor.value in {'agent', 'staff'}
            and message.visibility is not MessageVisibility.INTERNAL_ONLY
            and message.content.get('text')
        ],
        promised_next_step=promised_next_step,
    )
    handoff = HandoffRecord(
        handoff_id=new_id('hnd'),
        claim_id=claim.claim_id,
        type=handoff_type,
        status=HandoffStatus.QUEUED,
        priority=priority,
        queue=queue,
        support_need=support_need,
        trigger=_claimant_handoff_trigger(support_need),
        preferred_channel=preferred_channel,
        reason_codes=[reason_code or default_reason_code],
        reason=reason,
        requested_action=(
            'Respond to the immediate support need and continue the report '
            'from the preserved context.'
            if action is AgentAction.URGENT_HANDOFF
            else 'Contact the claimant and continue the report from the preserved context.'
        ),
        applied_rule='prototype_immediate_transfer',
        packet=packet,
        source_message_id=source_message_id,
        created_at=timestamp,
    )
    next_step = CustomerNextStep(
        status=(
            'urgent_support_queued'
            if action is AgentAction.URGENT_HANDOFF
            else 'human_support_queued'
        ),
        summary=promised_next_step,
        responsible_party=ResponsibleParty.NORTHWIND,
    )
    return handoff, next_step


def updated_claim_for_handoff(
    claim: WorkingClaim,
    handoff: HandoffRecord,
    next_step: CustomerNextStep,
) -> WorkingClaim:
    customer_support = (
        CustomerSupport.ACCESSIBILITY_REQUIRED
        if handoff.support_need is SupportNeed.ACCESSIBILITY_REQUIRED
        else CustomerSupport.HUMAN_REQUESTED
    )
    urgency = (
        Urgency.URGENT if handoff.support_need is SupportNeed.URGENT else claim.claim_state.urgency
    )
    action = (
        AgentAction.URGENT_HANDOFF
        if handoff.type is HandoffType.URGENT_SUPPORT
        else AgentAction.HANDOFF
    )
    return claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'claim_state': claim.claim_state.model_copy(
                update={
                    'customer_support': customer_support,
                    'urgency': urgency,
                    'workflow_state': WorkflowState.PROFESSIONAL_REVIEW,
                    'next_action': action,
                }
            ),
            'customer_next_step': next_step,
            'updated_at': handoff.created_at,
        }
    )


def create_support_request(
    repository: PersistenceRepository,
    dispatch: HandoffDispatchAdapter,
    principal: Principal,
    claim_id: str,
    payload: CreateSupportRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> SupportRequestResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/support-requests'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing_retry = repository.find_idempotency(principal.subject, route, key)
    if existing_retry is not None:
        if existing_retry.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        claim = repository.get_claim(claim_id, principal.subject)
        handoff = (
            repository.get_handoff(
                claim_id,
                existing_retry.handoff_id,
                principal.subject,
            )
            if existing_retry.handoff_id is not None
            else None
        )
        if claim is None or handoff is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent support request could not be restored.',
                retryable=True,
            )
        return _response(handoff, claim, notify_staff_queue(dispatch, handoff))

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    active_handoff = next(
        (
            handoff
            for handoff in reversed(repository.list_handoffs(claim_id, principal.subject))
            if handoff.status in ACTIVE_HANDOFF_STATUSES
            and handoff.support_need is payload.support_need
        ),
        None,
    )
    if active_handoff is not None:
        repository.save_idempotency(
            IdempotencyRecord(
                actor_id=principal.subject,
                route=route,
                key=key,
                request_fingerprint=fingerprint,
                claim_id=claim_id,
                session_id=claim.active_session_id or '',
                handoff_id=active_handoff.handoff_id,
            )
        )
        return _response(active_handoff, claim, notify_staff_queue(dispatch, active_handoff))

    handoff, next_step = build_handoff(
        repository,
        claim,
        support_need=payload.support_need,
        reason=payload.reason,
        preferred_channel=payload.preferred_channel,
        source_message_id=None,
    )
    updated_claim = updated_claim_for_handoff(claim, handoff, next_step)
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        handoff_id=handoff.handoff_id,
    )
    try:
        repository.save_handoff_mutation(
            updated_claim,
            expected_revision,
            handoff,
            idempotency,
        )
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
            message='The support request was already accepted with different retry data.',
        ) from conflict
    return _response(handoff, updated_claim, notify_staff_queue(dispatch, handoff))
