from datetime import datetime

from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AgentProposalSource,
    AuthorityOutcome,
    BranchEvaluationResult,
    BranchEvaluationStatus,
    ClaimantDecision,
    ClaimantMessage,
    Coverage,
    CreateMessageRequest,
    CustomerNextStep,
    DynamicFormProjection,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceState,
    EvidenceStatus,
    FormChange,
    FormSource,
    FormStatus,
    HandoffRecord,
    HandoffType,
    MessageRecord,
    MessageTurnResponse,
    MessageVisibility,
    NeededFor,
    ProposedFormChange,
    ResponsibleParty,
    StructuredFormField,
    SupportNeed,
    WorkflowState,
)
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    ClaimHistorySearchRequest,
    PolicyRetrievalRecord,
    PolicySearchRequest,
    RetrievalStatus,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.agent import (
    AgentProposal,
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
from backend.services.professional_reviews import build_policy_review_handoff
from backend.services.retrieval import search_claim_history, search_policy
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

INTERNAL_ONLY_REASON_CODES = frozenset(
    {
        'SAFETY_STATUS_REQUIRED',
        'SAFETY_STATUS_UNCLEAR',
        'SAFETY_STATUS_RECORDED',
        'POLICY_WORDING_REVIEW_NEEDED',
        'PROFESSIONAL_REVIEW_REQUIRED',
        'EVIDENCE_PENDING_GENERATION',
        'ADDITIONAL_CONTEXT_RECORDED',
    }
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
        reason_codes=(
            []
            if decision.proposal_source is AgentProposalSource.MODEL_GATEWAY
            else [code for code in decision.reason_codes if code not in INTERNAL_ONLY_REASON_CODES]
        ),
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
    dynamic_form = None
    evaluations = repository.list_branch_evaluations(claim_id, principal.subject)
    valid_evaluation = next(
        (
            item
            for item in reversed(evaluations)
            if item.status in {BranchEvaluationStatus.EVALUATED, BranchEvaluationStatus.APPLIED}
        ),
        None,
    )
    if valid_evaluation is not None:
        dynamic_form = DynamicFormProjection(
            claim_id=claim_id,
            claim_revision=valid_evaluation.resulting_claim_revision
            or valid_evaluation.evaluated_against_claim_revision,
            registry_version=valid_evaluation.registry_version,
            selected_family=valid_evaluation.selected_family,
            active_branches=[
                result.branch_id
                for result in valid_evaluation.branch_results
                if result.status == 'active'
            ],
            fields=valid_evaluation.field_selection_results,
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
        handoff=(
            claimant_handoff(handoff).model_dump(mode='json')
            if handoff is not None
            and handoff.type is not HandoffType.PROFESSIONAL_REVIEW
            and handoff.support_need is not None
            else None
        ),
        dynamic_form=dynamic_form,
    )


def _message_only_response(
    claim_id: str,
    session_id: str,
    revision: int,
    message: MessageRecord,
) -> MessageTurnResponse:
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=session_id,
        claim_revision=revision,
        claimant_message=_claimant_message(message),
        form_changes=[],
        handoff=None,
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


_MODEL_FIELD_QUESTIONS: dict[str, tuple[str, str, str]] = {
    'incident.injury_or_danger': (
        'provide_safety_status',
        'Is anyone injured or in immediate danger?',
        'Tell us whether anyone is injured or in immediate danger.',
    ),
    'vehicle.drivable': (
        'provide_vehicle_status',
        'Is the vehicle safe to drive?',
        'Tell us whether the vehicle is safe to drive.',
    ),
    'incident.occurred_at': (
        'provide_incident_time',
        'About when did this happen?',
        'Tell us approximately when the incident happened.',
    ),
    'incident.location': (
        'provide_incident_location',
        'Where did the incident happen?',
        'Tell us where the incident happened.',
    ),
    'loss.description': (
        'describe_loss',
        'What was damaged or lost?',
        'Describe what was damaged or lost.',
    ),
}


def _validated_model_question(
    proposal: AgentProposal,
    current_form: dict[str, StructuredFormField],
) -> tuple[str, CustomerNextStep] | None:
    available_fields = {
        field_code
        for field_code, field in current_form.items()
        if field.status is not FormStatus.MISSING
    }
    available_fields.update(change.field_code for change in proposal.form_changes)
    if 'vehicle.damage_description' in available_fields:
        available_fields.add('loss.description')
    for field_code in proposal.customer_next_step.required_items:
        if field_code in available_fields:
            continue
        question = _MODEL_FIELD_QUESTIONS.get(field_code)
        if question is None:
            continue
        status, response_text, summary = question
        return (
            response_text,
            CustomerNextStep(
                status=status,
                summary=summary,
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=[field_code],
            ),
        )
    return None


def _safe_model_customer_content(
    proposal: AgentProposal,
    outcome: AuthorityOutcome,
    current_next_step: CustomerNextStep,
    current_form: dict[str, StructuredFormField],
) -> tuple[str, str, CustomerNextStep]:
    if outcome is AuthorityOutcome.REVIEW_REQUIRED:
        return (
            'The proposed action requires professional review.',
            'I have recorded what you shared. A Northwind claims professional must review the '
            'proposed next step before it can continue.',
            _effective_next_step(proposal.customer_next_step, outcome),
        )
    if outcome is AuthorityOutcome.BLOCKED:
        return (
            'The proposed action was not applied.',
            'I have recorded what you shared, but I could not safely apply the proposed next '
            'step. Your current report remains available.',
            _effective_next_step(proposal.customer_next_step, outcome),
        )

    validated_question = _validated_model_question(proposal, current_form)
    if proposal.action is AgentAction.ASK and validated_question is not None:
        question, next_step = validated_question
        return (
            'More incident information is needed.',
            f'Thanks. {question}',
            next_step,
        )
    if proposal.action is AgentAction.ASK:
        return (
            'More incident information is needed.',
            'Thanks. Please share the next incident detail you want Northwind to record.',
            CustomerNextStep(
                status='more_information_needed',
                summary='Provide the next incident detail.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    if proposal.action is AgentAction.CLARIFY:
        return (
            'A material incident detail needs clarification.',
            'Thanks. Please clarify or correct the incident detail before the report continues.',
            CustomerNextStep(
                status='clarification_needed',
                summary='Clarify or correct the incident detail.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    if proposal.action is AgentAction.CONFIRM and validated_question is not None:
        question, next_step = validated_question
        return (
            'Proposed incident details need claimant confirmation.',
            f'Thanks. Please review the proposed information. {question}',
            next_step,
        )
    if proposal.action is AgentAction.CONFIRM:
        return (
            'A proposed incident detail needs claimant confirmation.',
            'Thanks. Please review the proposed information and confirm or correct it.',
            CustomerNextStep(
                status='confirmation_needed',
                summary='Confirm or correct the proposed information.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        )
    return (
        'The claimant update was recorded without a high-impact decision.',
        'Thanks. I have recorded your update. You can continue when you are ready.',
        current_next_step,
    )


def _build_form_changes(
    existing_form: dict[str, StructuredFormField],
    proposals: list[ProposedFormChange],
    claimant_message: MessageRecord,
    timestamp: datetime,
    authority_outcome: AuthorityOutcome,
    proposal_source: AgentProposalSource,
    branch_evaluation: BranchEvaluationResult | None = None,
) -> dict[str, StructuredFormField]:
    form_changes: dict[str, StructuredFormField] = {}
    normalised_proposals = list(proposals)
    proposed_codes = {proposal.field_code for proposal in proposals}
    if (
        'vehicle.damage_description' in proposed_codes
        and 'loss.description' not in proposed_codes
        and (
            'loss.description' not in existing_form
            or existing_form['loss.description'].status is not FormStatus.CONFIRMED
        )
    ):
        vehicle_damage = next(
            proposal
            for proposal in proposals
            if proposal.field_code == 'vehicle.damage_description'
        )
        normalised_proposals.append(
            vehicle_damage.model_copy(update={'field_code': 'loss.description'})
        )

    for proposal in normalised_proposals:
        if proposal.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an unregistered field.',
            )
        if branch_evaluation is not None:
            selection = next(
                (
                    item
                    for item in branch_evaluation.field_selection
                    if item.field_code == proposal.field_code
                ),
                None,
            )
            if selection is None or selection.selection_state.value in {
                'inactive',
                'system_owned',
            }:
                raise ApiError(
                    status_code=409,
                    code='INVALID_FIELD_BRANCH',
                    message='The Agent proposed a field outside the active form branches.',
                )
        existing_field = existing_form.get(proposal.field_code)
        if existing_field is not None and existing_field.status is FormStatus.CONFIRMED:
            continue
        form_changes[proposal.field_code] = StructuredFormField(
            value=proposal.value,
            source=proposal.source,
            source_refs=[claimant_message.message_id],
            status=(
                proposal.status
                if authority_outcome is AuthorityOutcome.AUTHORISED
                and proposal.source is FormSource.CLAIMANT
                else FormStatus.PROPOSED
            ),
            needed_for=proposal.needed_for,
            confidence=proposal.confidence,
            updated_at=timestamp,
            updated_by=ActorReference(
                actor_type=ActorType.AGENT,
                actor_id=proposal_source.value,
            ),
        )
    return form_changes


def _policy_search_tool(proposal: AgentProposal) -> dict[str, object] | None:
    return next(
        (
            tool
            for tool in proposal.required_tools
            if tool.get('tool') == 'policy_history' and tool.get('operation') == 'search_policy'
        ),
        None,
    )


def _execute_policy_search(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    claim_id: str,
    customer_id: str,
    proposal: AgentProposal,
) -> PolicyRetrievalRecord | None:
    tool = _policy_search_tool(proposal)
    if tool is None:
        return None
    policy_reference = str(tool.get('policy_reference') or '')
    if not policy_reference:
        return None
    existing = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim_id, customer_id))
            if isinstance(record, PolicyRetrievalRecord)
            and record.facts.policy_reference == policy_reference
        ),
        None,
    )
    if existing is not None:
        return existing
    result = search_policy(
        repository,
        adapter,
        PolicySearchRequest(
            claim_id=claim_id,
            policy_reference=policy_reference,
            question=str(tool.get('question') or '') or None,
        ),
    )
    if result.status not in {RetrievalStatus.AMBIGUOUS, RetrievalStatus.EVIDENCE_FOUND}:
        return None
    return next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, PolicyRetrievalRecord) and record.retrieval_id == result.result_id
        ),
        None,
    )


def _claim_history_search_tool(proposal: AgentProposal) -> dict[str, object] | None:
    return next(
        (
            tool
            for tool in proposal.required_tools
            if tool.get('tool') in {'policy_history', 'claim_history'}
            and tool.get('operation') in {'search_claim_history', 'lookup'}
        ),
        None,
    )


def _execute_claim_history_search(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    claim_id: str,
    customer_id: str,
    proposal: AgentProposal,
) -> ClaimHistoryRetrievalRecord | None:
    tool = _claim_history_search_tool(proposal)
    if tool is None:
        return None
    raw_reference = tool.get('history_reference')
    if not isinstance(raw_reference, str):
        return None
    history_reference = raw_reference.strip()
    if not history_reference:
        return None
    if 'limit' not in tool:
        limit = 10
    else:
        raw_limit = tool['limit']
        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
            return None
        limit = raw_limit
    if not 1 <= limit <= 50:
        return None
    existing = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim_id, customer_id))
            if isinstance(record, ClaimHistoryRetrievalRecord)
            and record.facts.history_reference == history_reference
        ),
        None,
    )
    if existing is not None:
        return existing
    result = search_claim_history(
        repository,
        adapter,
        ClaimHistorySearchRequest(
            claim_id=claim_id,
            history_reference=history_reference,
            purpose='relevant_history_review',
            limit=limit,
        ),
    )
    if result.status not in {RetrievalStatus.AMBIGUOUS, RetrievalStatus.EVIDENCE_FOUND}:
        return None
    return next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, ClaimHistoryRetrievalRecord)
            and record.retrieval_id == result.result_id
        ),
        None,
    )


def _professional_review_requested(proposal: AgentProposal) -> bool:
    return any(
        tool.get('tool') == 'professional_review'
        and tool.get('operation') == 'create_policy_review'
        for tool in proposal.required_tools
    )


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
        wait_type='claimant',
        responsible_party='claimant',
        context_summary='The document is expected later and is needed for a later action.',
        created_at=timestamp,
        updated_at=timestamp,
    )


def submit_message(
    repository: PersistenceRepository,
    agent: AgentTurnProvider,
    policy_history_adapter: PolicyHistoryAdapter,
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
        if existing_idempotency.response_payload is not None:
            return MessageTurnResponse.model_validate(existing_idempotency.response_payload)
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
                claim = repository.get_claim(claim_id, principal.subject)
                if claim is not None:
                    return _message_only_response(
                        claim_id, session_id, claim.revision, existing_client_message
                    )
                raise _session_not_found()
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
    active_handoff = next(
        (
            item
            for item in reversed(repository.list_handoffs(claim_id, principal.subject))
            if item.status.value not in {'resolved', 'cancelled'}
            and item.type is not HandoffType.PROFESSIONAL_REVIEW
            and item.support_need is not None
        ),
        None,
    )
    message_text = payload.content.text if payload.content is not None else ''
    if active_handoff is not None and not message_text.lstrip().lower().startswith('@agent'):
        timestamp = now_utc()
        claimant_message = MessageRecord(
            message_id=new_id('msg'),
            claim_id=claim_id,
            session_id=session_id,
            client_message_id=payload.client_message_id,
            actor=ActorType.CLAIMANT,
            visibility=MessageVisibility.SHARED,
            content=payload.content.model_dump(mode='json')
            if payload.content is not None
            else {'type': 'evidence_reference'},
            evidence_refs=payload.evidence_refs,
            created_at=timestamp,
        )
        updated_claim = claim.model_copy(
            update={'revision': claim.revision + 1, 'updated_at': timestamp}
        )
        updated_session = session.model_copy(
            update={'last_active_at': timestamp, 'context_revision': updated_claim.revision}
        )
        idempotency = IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session_id,
            message_id=claimant_message.message_id,
        )
        response = _message_only_response(
            claim_id, session_id, updated_claim.revision, claimant_message
        )
        idempotency = IdempotencyRecord(
            **{
                **idempotency.__dict__,
                'response_payload': response.model_dump(mode='json'),
            }
        )
        try:
            repository.save_message_mutation(
                updated_claim, expected_revision, updated_session, claimant_message, idempotency
            )
        except RevisionConflict as conflict:
            raise ApiError(
                status_code=409,
                code='REVISION_CONFLICT',
                message='The claim changed after this page was loaded.',
                retryable=True,
                current_revision=conflict.current_revision,
            ) from conflict
        return response
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
    branch_evaluation = BranchRuleEvaluator().evaluate(
        claim,
        latest_message=(payload.content.text if payload.content is not None else None),
        current_action=claim.claim_state.next_action,
        recomputation_reason='claimant_message',
    )
    persisted_review_signals = repository.list_review_signals(claim_id, principal.subject)
    proposal = agent.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id=session_id,
            trigger_message_id=claimant_message.message_id,
            message_text=(
                payload.content.text.lstrip()[len('@agent') :].lstrip()
                if payload.content is not None
                and payload.content.text.lstrip().lower().startswith('@agent')
                else payload.content.text
                if payload.content is not None
                else None
            ),
            evidence_refs=payload.evidence_refs,
            professional_review_required=any(
                signal.code == 'POLICY_RETRIEVAL_UNCERTAINTY' for signal in persisted_review_signals
            ),
            branch_evaluation=branch_evaluation,
        )
    )
    authority = validate_proposal(proposal)
    executed_state_changes = authorised_state_changes(proposal, authority)
    effective_customer_reason = proposal.customer_reason
    effective_customer_response = proposal.customer_response
    effective_next_step = _effective_next_step(proposal.customer_next_step, authority.outcome)
    if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY:
        (
            effective_customer_reason,
            effective_customer_response,
            effective_next_step,
        ) = _safe_model_customer_content(
            proposal,
            authority.outcome,
            claim.customer_next_step,
            claim.form,
        )
    form_changes = _build_form_changes(
        claim.form,
        proposal.form_changes,
        claimant_message,
        timestamp,
        authority.outcome,
        proposal.proposal_source,
        branch_evaluation,
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

    policy_retrieval = _execute_policy_search(
        repository,
        policy_history_adapter,
        claim_id,
        principal.subject,
        proposal,
    )
    _execute_claim_history_search(
        repository,
        policy_history_adapter,
        claim_id,
        principal.subject,
        proposal,
    )
    inferred_incident_type = claim.incident_type
    incident_type_change = form_changes.get('incident.type')
    if (
        inferred_incident_type is None
        and incident_type_change is not None
        and incident_type_change.source is FormSource.INFERENCE
        and incident_type_change.confidence is not None
        and incident_type_change.confidence >= 0.9
        and isinstance(incident_type_change.value, str)
    ):
        inferred_incident_type = incident_type_change.value.strip().lower()

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
        projected_form = {**claim.form, **form_changes}
        professional_review = _professional_review_requested(proposal)
        if professional_review:
            existing_retrievals = repository.list_retrieval_records(claim_id, principal.subject)
            existing_signals = repository.list_review_signals(claim_id, principal.subject)
            policy_record = next(
                (
                    item
                    for item in reversed(existing_retrievals)
                    if isinstance(item, PolicyRetrievalRecord) and item.uncertainty
                ),
                None,
            )
            review_signal = next(
                (
                    item
                    for item in reversed(existing_signals)
                    if policy_record is not None and policy_record.retrieval_id in item.source_refs
                ),
                None,
            )
            if policy_record is None or review_signal is None:
                raise ApiError(
                    status_code=409,
                    code='INVALID_STATE_TRANSITION',
                    message='A sourced policy review is required before professional review.',
                )
            projected_claim = claim.model_copy(
                update={
                    'form': projected_form,
                    'incident_type': inferred_incident_type,
                    'revision': claim.revision + 1,
                }
            )
            handoff, effective_next_step = build_policy_review_handoff(
                repository,
                projected_claim,
                retrieval=policy_record,
                signal=review_signal,
                source_message_id=claimant_message.message_id,
                pending_evidence=pending_evidence,
            )
        updated_claim = claim.model_copy(
            update={
                'claim_state': claim.claim_state.model_copy(
                    update={
                        'next_action': (
                            AgentAction.HANDOFF if professional_review else next_action
                        ),
                        **(
                            {'coverage': Coverage.REVIEW_REQUIRED}
                            if policy_retrieval is not None
                            else {}
                        ),
                        **(
                            {'workflow_state': WorkflowState.PROFESSIONAL_REVIEW}
                            if professional_review
                            else {}
                        ),
                        **(
                            {'evidence': EvidenceState.PENDING_GENERATION}
                            if pending_evidence is not None
                            else {}
                        ),
                    }
                ),
                'form': projected_form,
                'incident_type': inferred_incident_type,
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
        content={'type': 'text', 'text': effective_customer_response},
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
        customer_reason=effective_customer_reason,
        customer_response=effective_customer_response,
        state_changes=proposal.state_changes,
        proposed_signals=proposal.proposed_signals,
        required_tools=proposal.required_tools,
        next_action_requirements=proposal.next_action_requirements,
        handoff_priority=proposal.handoff_priority,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        customer_next_step=effective_next_step,
        authority=authority,
        proposal_source=proposal.proposal_source,
        model_provenance=proposal.model_provenance,
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
