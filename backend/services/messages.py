from datetime import datetime

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AuthorityOutcome,
    ClaimantDecision,
    ClaimantMessage,
    CreateMessageRequest,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceState,
    EvidenceStatus,
    FormChange,
    FormSource,
    FormStatus,
    HandoffRecord,
    MessageListResponse,
    MessageRecord,
    MessageTurnResponse,
    MessageVisibility,
    NeededFor,
    PageInfo,
    ProposedFormChange,
    ResponsibleParty,
    StructuredFormField,
    SupportNeed,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.agent import (
    AgentTurnContext,
    AgentTurnProvider,
    authorised_state_changes,
    validate_proposal,
)
from backend.services.handoffs import (
    build_handoff,
    claimant_handoff,
    updated_claim_for_handoff,
)
from backend.services.support import (
    decode_cursor,
    encode_cursor,
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def _claimant_message(message: MessageRecord) -> ClaimantMessage:
    return ClaimantMessage(
        message_id=message.message_id,
        actor=message.actor,
        content=message.content,
        evidence_refs=message.evidence_refs,
        in_reply_to=message.in_reply_to,
        created_at=message.created_at,
    )


def _claimant_decision(decision: AgentDecisionRecord) -> ClaimantDecision:
    return ClaimantDecision(
        decision_id=decision.decision_id,
        action=decision.action,
        reason_codes=decision.reason_codes,
        customer_reason=decision.customer_reason,
        customer_next_step=decision.customer_next_step,
    )


def _message_turn_response(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    claimant_message: MessageRecord,
    decision: AgentDecisionRecord,
) -> MessageTurnResponse:
    messages = repository.list_messages(
        claim_id,
        claimant_message.session_id,
        principal.subject,
    )
    agent_message = next(
        (
            message
            for message in messages
            if message.actor is ActorType.AGENT
            and message.in_reply_to == claimant_message.message_id
        ),
        None,
    )
    if agent_message is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The persisted agent turn could not be restored.',
            retryable=True,
        )
    handoff = (
        repository.get_handoff(claim_id, decision.handoff_id, principal.subject)
        if decision.handoff_id is not None
        else None
    )
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=claimant_message.session_id,
        claim_revision=decision.resulting_revision,
        claimant_message=_claimant_message(claimant_message),
        agent_message=_claimant_message(agent_message),
        form_changes=[
            FormChange(field_code=field_code, field=field)
            for field_code, field in decision.form_changes.items()
        ],
        decision=_claimant_decision(decision),
        handoff=claimant_handoff(handoff).model_dump(mode='json') if handoff is not None else None,
    )


def _effective_next_step(
    proposed: CustomerNextStep,
    outcome: AuthorityOutcome,
) -> CustomerNextStep:
    if outcome is AuthorityOutcome.AUTHORISED:
        return proposed
    if outcome is AuthorityOutcome.REVIEW_REQUIRED:
        return CustomerNextStep(
            status='professional_review_required',
            summary='The proposed action requires professional review before it can continue.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        )
    return CustomerNextStep(
        status='action_not_applied',
        summary='The proposed action was not applied. Your current report remains available.',
        responsible_party=ResponsibleParty.NORTHWIND,
    )


def _build_form_changes(
    existing_form: dict[str, StructuredFormField],
    proposals: list[ProposedFormChange],
    claimant_message: MessageRecord,
    timestamp: datetime,
) -> dict[str, StructuredFormField]:
    form_changes: dict[str, StructuredFormField] = {}
    for proposal in proposals:
        if proposal.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an unregistered field.',
            )
        existing_field = existing_form.get(proposal.field_code)
        if existing_field is not None and existing_field.status is FormStatus.CONFIRMED:
            continue
        form_changes[proposal.field_code] = StructuredFormField(
            value=proposal.value,
            source=proposal.source,
            source_refs=[claimant_message.message_id],
            status=FormStatus.PROPOSED,
            needed_for=proposal.needed_for,
            confidence=proposal.confidence,
            updated_at=timestamp,
            updated_by=ActorReference(actor_type=ActorType.AGENT, actor_id='controlled_agent'),
        )
    return form_changes


def _pending_evidence_for_proposal(
    claim_id: str,
    proposal: object,
    claimant_message: MessageRecord,
    timestamp: datetime,
) -> EvidenceRecord | None:
    required_tools = getattr(proposal, 'required_tools', [])
    pending = next(
        (
            tool
            for tool in required_tools
            if tool.get('tool') == 'evidence_registry'
            and tool.get('operation') == 'record_pending_generation'
        ),
        None,
    )
    if pending is None:
        return None
    return EvidenceRecord(
        evidence_id=new_id('evd'),
        claim_id=claim_id,
        kind=str(pending.get('kind') or 'document'),
        status=EvidenceStatus.PENDING_GENERATION,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        related_fields=['authorities.police_report_reference'],
        needed_for=['later_action'],
        provenance={'reported_in_message_id': claimant_message.message_id},
        claimant_note=str(claimant_message.content.get('text') or ''),
        created_at=timestamp,
        updated_at=timestamp,
    )


def submit_message(
    repository: PersistenceRepository,
    agent: AgentTurnProvider,
    principal: Principal,
    claim_id: str,
    session_id: str,
    payload: CreateMessageRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> MessageTurnResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing_idempotency = repository.find_idempotency(principal.subject, route, key)
    if existing_idempotency is not None:
        if existing_idempotency.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing_idempotency.message_id is None or existing_idempotency.decision_id is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent message turn could not be restored.',
                retryable=True,
            )
        claimant_message = repository.get_message(
            claim_id,
            session_id,
            existing_idempotency.message_id,
            principal.subject,
        )
        decision = repository.get_agent_decision(
            claim_id,
            existing_idempotency.decision_id,
            principal.subject,
        )
        if claimant_message is None or decision is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent message turn could not be restored.',
                retryable=True,
            )
        return _message_turn_response(repository, principal, claim_id, claimant_message, decision)

    existing_client_message = repository.find_message_by_client_id(
        claim_id,
        payload.client_message_id,
        principal.subject,
    )
    if existing_client_message is not None:
        if existing_client_message.session_id != session_id:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The client_message_id belongs to a different session.',
            )
        expected_content = (
            payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'}
        )
        if (
            existing_client_message.content == expected_content
            and existing_client_message.evidence_refs == payload.evidence_refs
        ):
            decision = repository.find_agent_decision_for_trigger(
                claim_id,
                existing_client_message.message_id,
                principal.subject,
            )
            if decision is None:
                raise ApiError(
                    status_code=500,
                    code='INTERNAL_ERROR',
                    message='The deduplicated message turn could not be restored.',
                    retryable=True,
                )
            return _message_turn_response(
                repository,
                principal,
                claim_id,
                existing_client_message,
                decision,
            )
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The client_message_id has already been used for this claim.',
        )

    claim = repository.get_claim(claim_id, principal.subject)
    session = repository.get_session(claim_id, session_id, principal.subject)
    if claim is None or session is None:
        raise _session_not_found()
    if session.status.value != 'active':
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Messages can only be submitted to an active session.',
        )
    if claim.active_session_id != session_id:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Messages can only be submitted to the claim active session.',
        )
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    missing_evidence_refs = [
        evidence_id
        for evidence_id in payload.evidence_refs
        if repository.get_evidence(claim_id, evidence_id, principal.subject) is None
    ]
    if missing_evidence_refs:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more evidence references are invalid.',
            details=[
                ErrorDetail(field='evidence_refs', reason=f'Unknown evidence: {evidence_id}.')
                for evidence_id in missing_evidence_refs
            ],
        )

    timestamp = now_utc()
    claimant_message = MessageRecord(
        message_id=new_id('msg'),
        claim_id=claim_id,
        session_id=session_id,
        client_message_id=payload.client_message_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content=(
            payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'}
        ),
        evidence_refs=payload.evidence_refs,
        created_at=timestamp,
    )
    proposal = agent.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id=session_id,
            trigger_message_id=claimant_message.message_id,
            message_text=payload.content.text if payload.content is not None else None,
            evidence_refs=payload.evidence_refs,
        )
    )
    authority = validate_proposal(proposal)
    executed_state_changes = authorised_state_changes(proposal, authority)
    effective_next_step = _effective_next_step(proposal.customer_next_step, authority.outcome)
    form_changes = _build_form_changes(
        claim.form, proposal.form_changes, claimant_message, timestamp
    )
    pending_evidence = _pending_evidence_for_proposal(
        claim_id,
        proposal,
        claimant_message,
        timestamp,
    )
    if pending_evidence is not None:
        form_changes['authorities.police_report_reference'] = StructuredFormField(
            value=None,
            source=FormSource.CLAIMANT,
            source_refs=[claimant_message.message_id, pending_evidence.evidence_id],
            status=FormStatus.PENDING_GENERATION,
            needed_for=NeededFor.LATER_ACTION,
            confidence=1.0,
            updated_at=timestamp,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
        )
    if authority.outcome is AuthorityOutcome.BLOCKED:
        form_changes = {}

    next_action = claim.claim_state.next_action
    for state_change in executed_state_changes:
        if state_change.path == 'claim_state.next_action':
            raw_action = (
                state_change.to.value
                if isinstance(state_change.to, AgentAction)
                else state_change.to
            )
            next_action = AgentAction(str(raw_action))
    handoff: HandoffRecord | None = None
    if authority.outcome is AuthorityOutcome.AUTHORISED and proposal.action in {
        AgentAction.HANDOFF,
        AgentAction.URGENT_HANDOFF,
    }:
        support_need = (
            SupportNeed.URGENT
            if proposal.action is AgentAction.URGENT_HANDOFF
            else SupportNeed.HUMAN_REQUESTED
        )
        handoff, effective_next_step = build_handoff(
            repository,
            claim,
            support_need=support_need,
            reason=proposal.customer_reason,
            preferred_channel=None,
            source_message_id=claimant_message.message_id,
            reason_code=proposal.reason_codes[0],
        )
        updated_claim = updated_claim_for_handoff(claim, handoff, effective_next_step)
    else:
        updated_claim = claim.model_copy(
            update={
                'claim_state': claim.claim_state.model_copy(
                    update={
                        'next_action': next_action,
                        **(
                            {'evidence': EvidenceState.PENDING_GENERATION}
                            if pending_evidence is not None
                            else {}
                        ),
                    }
                ),
                'form': {**claim.form, **form_changes},
                'evidence_summary': (
                    claim.evidence_summary.model_copy(
                        update={'pending': claim.evidence_summary.pending + 1}
                    )
                    if pending_evidence is not None
                    else claim.evidence_summary
                ),
                'customer_next_step': effective_next_step,
                'revision': claim.revision + 1,
                'updated_at': timestamp,
            }
        )
    resulting_revision = updated_claim.revision
    updated_session = session.model_copy(
        update={
            'last_active_at': timestamp,
            'context_revision': resulting_revision,
        }
    )
    agent_message = MessageRecord(
        message_id=new_id('msg'),
        claim_id=claim_id,
        session_id=session_id,
        actor=ActorType.AGENT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': proposal.customer_response},
        in_reply_to=claimant_message.message_id,
        created_at=timestamp,
    )
    decision = AgentDecisionRecord(
        decision_id=new_id('dec'),
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id=claimant_message.message_id,
        action=proposal.action,
        reason_codes=proposal.reason_codes,
        customer_reason=proposal.customer_reason,
        customer_response=proposal.customer_response,
        state_changes=proposal.state_changes,
        proposed_signals=proposal.proposed_signals,
        required_tools=proposal.required_tools,
        next_action_requirements=proposal.next_action_requirements,
        handoff_priority=proposal.handoff_priority,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        customer_next_step=effective_next_step,
        authority=authority,
        form_changes=form_changes,
        resulting_revision=resulting_revision,
        created_at=timestamp,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
        handoff_id=handoff.handoff_id if handoff is not None else None,
    )
    try:
        repository.save_agent_turn(
            updated_claim,
            expected_revision,
            updated_session,
            claimant_message,
            agent_message,
            decision,
            idempotency,
            handoff,
            pending_evidence,
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
            message='The message turn was already accepted with different retry data.',
        ) from conflict
    return _message_turn_response(repository, principal, claim_id, claimant_message, decision)


def list_claim_messages(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    *,
    limit: int,
    cursor: str | None,
    before: datetime | None,
    after: datetime | None,
) -> MessageListResponse:
    if repository.get_session(claim_id, session_id, principal.subject) is None:
        raise _session_not_found()
    for field_name, timestamp in {'before': before, 'after': after}.items():
        if timestamp is not None and timestamp.utcoffset() is None:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message=f'The {field_name} filter must include a timezone offset.',
                details=[
                    ErrorDetail(
                        field=field_name,
                        reason='Use an ISO 8601 timestamp with a timezone offset.',
                    )
                ],
            )
    visible_messages = [
        message
        for message in repository.list_messages(
            claim_id,
            session_id,
            principal.subject,
        )
        if message.visibility is not MessageVisibility.INTERNAL_ONLY
    ]
    if before is not None:
        visible_messages = [message for message in visible_messages if message.created_at < before]
    if after is not None:
        visible_messages = [message for message in visible_messages if message.created_at > after]
    offset = decode_cursor(cursor)
    page_messages = visible_messages[offset : offset + limit]
    next_offset = offset + len(page_messages)
    next_cursor = encode_cursor(next_offset) if next_offset < len(visible_messages) else None
    return MessageListResponse(
        items=[_claimant_message(message) for message in page_messages],
        page=PageInfo(next_cursor=next_cursor),
    )
