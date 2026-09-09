from dataclasses import replace
from datetime import datetime

from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.branch_registry import (
    BranchRuleEvaluator,
    validate_registered_field_value,
)
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.intake import intake_field_for_requirement, next_requirement_step
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AgentProposalSource,
    AssertionRelation,
    AuthorityOutcome,
    BranchEvaluationRecord,
    BranchEvaluationResult,
    BranchEvaluationStatus,
    ClaimantContentsItem,
    ClaimantDecision,
    ClaimantMessage,
    ContentsItem,
    Coverage,
    CreateMessageRequest,
    CustomerNextStep,
    DiscrepancyCandidate,
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
    QuestionRecord,
    ResponsibleParty,
    RuntimeTraceRecord,
    SessionRecord,
    StructuredFormField,
    SupportNeed,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    ClaimHistorySearchRequest,
    PolicyRetrievalRecord,
    PolicySearchRequest,
    RetrievalStatus,
)
from backend.domain.support_intent import detect_support_intent, support_need_for_intent
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
from backend.services.branching import (
    claimant_dynamic_form_projection,
    latest_applied_branch_evaluation,
)
from backend.services.claimant_form_projection import project_claimant_form_fields
from backend.services.fact_resolution import (
    provenance_messages_for_fields,
    resolve_contents_item_change,
    resolve_form_change,
)
from backend.services.handoffs import (
    build_handoff,
    claimant_handoff,
    updated_claim_for_handoff,
)
from backend.services.professional_reviews import build_policy_review_handoff
from backend.services.retrieval import search_claim_history, search_policy
from backend.services.runtime_agent_policy import (
    RuntimeAgentPolicyResolver,
    enforce_agent_proposal,
)
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError
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

_CONTEXT_TOOL_OPERATIONS = {
    'policy_history': frozenset({'search_policy'}),
    'claim_history': frozenset({'search_claim_history', 'lookup'}),
}
_ACTION_TOOL_OPERATIONS = {
    'evidence_registry': frozenset({'record_pending_generation'}),
    'professional_review': frozenset({'create_policy_review'}),
}


def _validate_tool_requests(
    proposal: AgentProposal,
    branch_evaluation: BranchEvaluationResult,
) -> None:
    if len(proposal.required_tools) > 3:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent requested too many tools for one bounded turn.',
        )
    allowed_names = set(branch_evaluation.permitted_tools)
    seen: set[tuple[str, str]] = set()
    context_tool_count = sum(
        request.get('tool') in _CONTEXT_TOOL_OPERATIONS for request in proposal.required_tools
    )
    if context_tool_count > 1:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent requested more than one context lookup in a bounded turn.',
        )
    for request in proposal.required_tools:
        tool = request.get('tool')
        operation = request.get('operation')
        if not isinstance(tool, str) or not isinstance(operation, str):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent supplied an invalid structured tool request.',
            )
        operations = _CONTEXT_TOOL_OPERATIONS.get(tool) or _ACTION_TOOL_OPERATIONS.get(tool)
        identity = (tool, operation)
        if tool not in allowed_names or operations is None or operation not in operations:
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent requested an unregistered tool operation.',
            )
        if identity in seen:
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent repeated a tool operation in one bounded turn.',
            )
        seen.add(identity)
        if (
            tool == 'policy_history'
            and operation == 'search_policy'
            and (
                not isinstance(request.get('policy_reference'), str)
                or not str(request['policy_reference']).strip()
            )
        ):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent supplied an invalid policy lookup request.',
            )
        if tool == 'claim_history' and operation in {'search_claim_history', 'lookup'}:
            if (
                not isinstance(request.get('history_reference'), str)
                or not str(request['history_reference']).strip()
            ):
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid claim-history lookup request.',
                )
            limit = request.get('limit', 10)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an invalid claim-history result limit.',
                )
        if tool == 'evidence_registry' and request.get('kind') != 'police_report':
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent requested an unsupported pending-evidence operation.',
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
        action_code=decision.action_code,
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
    claim = repository.get_claim(claim_id, principal.subject)
    dynamic_form = (
        claimant_dynamic_form_projection(repository, claim) if claim is not None else None
    )
    projected_form_changes = (
        project_claimant_form_fields(
            repository,
            claim,
            decision.form_changes,
        )
        if claim is not None
        else decision.form_changes
    )
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=claimant_message.session_id,
        claim_revision=decision.resulting_revision,
        claimant_message=_claimant_message(claimant_message),
        agent_message=_claimant_message(agent_message),
        form_changes=[
            FormChange(field_code=field_code, field=field)
            for field_code, field in projected_form_changes.items()
        ],
        contents_item_changes=[
            _claimant_contents_item(item) for item in decision.contents_item_changes
        ],
        decision=_claimant_decision(decision),
        handoff=(
            claimant_handoff(handoff)
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


def _namespaced_turn_response(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    claim_revision: int,
    claimant_message: MessageRecord,
    agent_message: MessageRecord,
) -> MessageTurnResponse:
    """Build the claimant projection for a Runtime trace without a legacy decision."""
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _session_not_found()
    return MessageTurnResponse(
        claim_id=claim_id,
        session_id=claimant_message.session_id,
        claim_revision=claim_revision,
        claimant_message=_claimant_message(claimant_message),
        agent_message=_claimant_message(agent_message),
        form_changes=[],
        decision=None,
        handoff=None,
        dynamic_form=claimant_dynamic_form_projection(repository, claim),
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
        responsible_party=ResponsibleParty.SYSTEM,
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
    grounding_source_refs: set[str] | None = None,
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
        if proposal.relation is AssertionRelation.IRRELEVANT:
            continue
        if proposal.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an unregistered field.',
            )
        try:
            validate_registered_field_value(
                proposal.field_code,
                proposal.value,
                status=proposal.status,
            )
        except ValueError as error:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The Agent proposed an invalid registered-field value.',
                details=[ErrorDetail(field=proposal.field_code, reason=str(error))],
            ) from error
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
        if (
            existing_field is not None
            and existing_field.status is FormStatus.CONFIRMED
            and proposal.source is not FormSource.CLAIMANT
            and proposal.value == existing_field.value
        ):
            continue
        accepted_status = (
            proposal.status
            if authority_outcome is AuthorityOutcome.AUTHORISED
            and proposal.source is FormSource.CLAIMANT
            else FormStatus.PROPOSED
        )
        resolved = resolve_form_change(
            field_code=proposal.field_code,
            existing=existing_field,
            proposal=proposal,
            source_ref=claimant_message.message_id,
            message_text=str(claimant_message.content.get('text', '')) or None,
            timestamp=timestamp,
            accepted_status=accepted_status,
            updated_by=ActorReference(
                actor_type=ActorType.AGENT,
                actor_id=proposal_source.value,
            ),
        )
        if proposal.source is not FormSource.CLAIMANT and grounding_source_refs:
            assertions = list(resolved.assertions)
            if assertions:
                assertions[-1] = assertions[-1].model_copy(
                    update={
                        'source_refs': list(
                            dict.fromkeys(
                                [*assertions[-1].source_refs, *sorted(grounding_source_refs)]
                            )
                        )
                    }
                )
            resolved = resolved.model_copy(
                update={
                    'source_refs': list(
                        dict.fromkeys([*resolved.source_refs, *sorted(grounding_source_refs)])
                    ),
                    'assertions': assertions,
                }
            )
        form_changes[proposal.field_code] = resolved
    return form_changes


def _build_contents_item_changes(
    claim: WorkingClaim,
    proposal: AgentProposal,
    claimant_message: MessageRecord,
    timestamp: datetime,
    authority_outcome: AuthorityOutcome,
    branch_evaluation: BranchEvaluationResult,
) -> list[ContentsItem]:
    if not proposal.contents_item_changes or authority_outcome is not AuthorityOutcome.AUTHORISED:
        return []
    contents_available = branch_evaluation.selected_family == 'contents' or (
        'family.contents' in branch_evaluation.candidate_branches
    )
    if not contents_available:
        raise ApiError(
            status_code=409,
            code='INVALID_FIELD_BRANCH',
            message='The Agent proposed a contents item outside the contents claim branch.',
        )
    existing_by_id = {item.item_id: item for item in claim.contents_items}
    existing_by_description = {
        item.description.strip().casefold(): item for item in claim.contents_items
    }
    changes: list[ContentsItem] = []
    for item in proposal.contents_item_changes:
        existing = existing_by_id.get(item.item_id or '')
        if item.item_id is not None and existing is None:
            raise ApiError(
                status_code=409,
                code='INVALID_CONTENTS_ITEM_REFERENCE',
                message='The Agent referenced a contents item that is not in this claim.',
            )
        if existing is None:
            existing = existing_by_description.get(item.description.strip().casefold())
        claimant_supplied = bool(
            item.reported_text
            and item.reported_text.casefold()
            in str(claimant_message.content.get('text', '')).casefold()
        )
        contents_item = resolve_contents_item_change(
            existing=existing,
            proposal=item,
            item_id=existing.item_id if existing is not None else new_id('itm'),
            source_ref=claimant_message.message_id,
            message_text=str(claimant_message.content.get('text', '')) or None,
            timestamp=timestamp,
            accepted_status=FormStatus.PROPOSED,
            updated_by=ActorReference(
                actor_type=ActorType.AGENT,
                actor_id=proposal.proposal_source.value,
            ),
        )
        if not claimant_supplied:
            contents_item = contents_item.model_copy(update={'source': FormSource.INFERENCE})
        changes.append(contents_item)
    return changes


def _apply_contents_item_changes(
    existing: list[ContentsItem],
    changes: list[ContentsItem],
) -> list[ContentsItem]:
    changes_by_id = {item.item_id: item for item in changes}
    projected = [changes_by_id.pop(item.item_id, item) for item in existing]
    projected.extend(changes_by_id.values())
    return projected


def _claimant_contents_item(item: ContentsItem) -> ClaimantContentsItem:
    return ClaimantContentsItem(
        item_id=item.item_id,
        description=item.description,
        category=item.category,
        quantity=item.quantity,
        loss_type=item.loss_type,
        ownership=item.ownership,
        estimated_value=item.estimated_value,
        source=item.source,
        source_refs=[ref for ref in item.source_refs if ref.startswith(('msg_', 'evd_'))],
        status=item.status,
        needed_for=item.needed_for,
        resolution_state=item.resolution_state,
        updated_at=item.updated_at,
    )


def _question_fields(proposal: AgentProposal, next_step: CustomerNextStep) -> list[str]:
    values = (
        list(next_step.required_items)
        if next_step.required_items
        else list(proposal.next_action_requirements)
    )
    fields: list[str] = []
    for value in values:
        field_code = value.removeprefix('confirm:')
        if (field_code in REGISTERED_FIELD_CODES or field_code == 'contents.items') and (
            field_code not in fields
        ):
            fields.append(field_code)
    return fields


def _tool_source_refs(tool_results: list[dict[str, object]]) -> set[str]:
    refs: set[str] = set()
    for result in tool_results:
        raw_refs = result.get('source_refs')
        if isinstance(raw_refs, list):
            refs.update(str(ref) for ref in raw_refs)
    return refs


def _grounding_source_refs(tool_results: list[dict[str, object]]) -> set[str]:
    return _tool_source_refs(
        [
            result
            for result in tool_results
            if result.get('tool') in {'knowledge_search', 'policy_history', 'claim_history'}
            and result.get('status') == RetrievalStatus.EVIDENCE_FOUND.value
        ]
    )


def _validate_failed_retrieval_changes(
    proposal: AgentProposal,
    message_text: str,
) -> None:
    failed_results = [
        result
        for result in proposal.tool_results
        if result.get('tool') in {'knowledge_search', 'policy_history', 'claim_history'}
        and result.get('status') != RetrievalStatus.EVIDENCE_FOUND.value
    ]
    if not failed_results:
        return
    unsupported_fields = [
        change.field_code
        for change in proposal.form_changes
        if change.source is not FormSource.CLAIMANT
    ]
    normalized_message = ' '.join(message_text.split()).casefold()
    unsupported_contents = [
        item.description
        for item in proposal.contents_item_changes
        if not item.reported_text
        or ' '.join(item.reported_text.split()).casefold() not in normalized_message
    ]
    if unsupported_fields or unsupported_contents:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The Agent used an unavailable context result as a new Claim fact.',
            retryable=False,
        )


def _apply_question_accounting(
    session: SessionRecord,
    proposal: AgentProposal,
    next_step: CustomerNextStep,
    response_text: str,
    trigger_message_id: str,
    timestamp: datetime,
) -> tuple[SessionRecord, CustomerNextStep, str]:
    asks_question = proposal.action in {AgentAction.ASK, AgentAction.CLARIFY} or (
        '?' in response_text and bool(_question_fields(proposal, next_step))
    )
    if not asks_question:
        return session, next_step, response_text
    if session.question_turn_count >= session.question_budget:
        paused_step = CustomerNextStep(
            status='question_budget_reached',
            summary='Your report is saved. Northwind may follow up on the remaining information.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
            required_items=list(next_step.required_items),
        )
        return (
            session.model_copy(update={'post_session_follow_up_required': True}),
            paused_step,
            'I have saved what you shared. Northwind may follow up on the remaining information.',
        )

    fields = _question_fields(proposal, next_step)
    previously_requested = {
        field_code for record in session.question_history for field_code in record.field_codes
    }
    repeated = bool(fields) and all(field_code in previously_requested for field_code in fields)
    question = QuestionRecord(
        question_id=new_id('qst'),
        trigger_message_id=trigger_message_id,
        field_codes=fields,
        purpose=proposal.action.value.lower(),
        repeated=repeated,
        asked_at=timestamp,
    )
    return (
        session.model_copy(
            update={
                'question_turn_count': session.question_turn_count + 1,
                'requested_fact_count': session.requested_fact_count + len(fields),
                'repeated_question_count': session.repeated_question_count + int(repeated),
                'question_history': [*session.question_history, question],
            }
        ),
        next_step,
        response_text,
    )


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
) -> tuple[PolicyRetrievalRecord | None, dict[str, object]] | None:
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
        return (
            existing,
            {
                'tool': 'policy_history',
                'status': (
                    RetrievalStatus.AMBIGUOUS.value
                    if existing.uncertainty
                    else RetrievalStatus.EVIDENCE_FOUND.value
                ),
                'source_refs': [existing.retrieval_id],
                'limitations': [],
            },
        )
    result = search_policy(
        repository,
        adapter,
        PolicySearchRequest(
            claim_id=claim_id,
            policy_reference=policy_reference,
            question=str(tool.get('question') or '') or None,
        ),
    )
    record = next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, PolicyRetrievalRecord) and record.retrieval_id == result.result_id
        ),
        None,
    )
    return (
        record,
        {
            'tool': 'policy_history',
            'status': result.status.value,
            'source_refs': [record.retrieval_id] if record is not None else [],
            'limitations': list(result.limitations),
        },
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
) -> tuple[ClaimHistoryRetrievalRecord | None, dict[str, object]] | None:
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
        return (
            existing,
            {
                'tool': 'claim_history',
                'status': (
                    RetrievalStatus.AMBIGUOUS.value
                    if existing.uncertainty
                    else RetrievalStatus.EVIDENCE_FOUND.value
                ),
                'source_refs': [existing.retrieval_id],
                'limitations': [],
            },
        )
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
    record = next(
        (
            record
            for record in repository.list_retrieval_records(claim_id, customer_id)
            if isinstance(record, ClaimHistoryRetrievalRecord)
            and record.retrieval_id == result.result_id
        ),
        None,
    )
    return (
        record,
        {
            'tool': 'claim_history',
            'status': result.status.value,
            'source_refs': [record.retrieval_id] if record is not None else [],
            'limitations': list(result.limitations),
        },
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


def _submit_namespaced_runtime_turn(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    claim: WorkingClaim,
    session: SessionRecord,
    claimant_message: MessageRecord,
    proposal: AgentProposal,
    authority: object,
    runtime_policy: object,
    branch_evaluator: BranchRuleEvaluator,
    previous_evaluation: BranchEvaluationRecord | None,
    message_text: str,
    route: str,
    key: str,
    fingerprint: str,
    expected_revision: int,
) -> MessageTurnResponse:
    """Persist the first namespaced, read-only Runtime turn.

    The target Runtime path deliberately does not create an ``AgentDecisionRecord`` or
    advance Claim revision. It records the conversation and Runtime trace while only
    updating Session activity, so ``claim.read`` remains observational.
    """

    runtime_trace: RuntimeTraceRecord | None = proposal.runtime_trace
    if runtime_trace is None or runtime_trace.status != 'succeeded':
        raise ApiError(
            status_code=503,
            code='AGENT_RUNTIME_UNAVAILABLE',
            message='The namespaced Agent Runtime did not produce a persistable result.',
            retryable=True,
        )
    timestamp = now_utc()
    updated_session = session.model_copy(
        update={'last_active_at': timestamp, 'context_revision': claim.revision}
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
    response = _namespaced_turn_response(
        repository,
        principal,
        claim_id,
        claim.revision,
        claimant_message,
        agent_message,
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
        runtime_trace_id=runtime_trace.trace_id,
        response_payload=response.model_dump(mode='json'),
    )
    try:
        repository.save_runtime_turn(
            claim,
            expected_revision,
            updated_session,
            claimant_message,
            agent_message,
            runtime_trace,
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
            message='The message turn was already accepted with different retry data.',
        ) from conflict
    return response


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
    runtime_agent_policy_resolver: RuntimeAgentPolicyResolver | None = None,
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
                runtime_trace = repository.find_runtime_trace_for_trigger(
                    claim_id,
                    existing_client_message.message_id,
                    principal.subject,
                )
                if runtime_trace is not None:
                    agent_message = next(
                        (
                            message
                            for message in repository.list_messages(
                                claim_id,
                                session_id,
                                principal.subject,
                            )
                            if message.actor is ActorType.AGENT
                            and message.in_reply_to == existing_client_message.message_id
                        ),
                        None,
                    )
                    if agent_message is None:
                        raise ApiError(
                            status_code=500,
                            code='INTERNAL_ERROR',
                            message='The Runtime message turn could not be restored.',
                            retryable=True,
                        )
                    claim = repository.get_claim(claim_id, principal.subject)
                    if claim is None:
                        raise _session_not_found()
                    return _namespaced_turn_response(
                        repository,
                        principal,
                        claim_id,
                        claim.revision,
                        existing_client_message,
                        agent_message,
                    )
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
    if active_handoff is not None:
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
    try:
        runtime_policy = (
            runtime_agent_policy_resolver.resolve_for_turn()
            if runtime_agent_policy_resolver is not None
            else None
        )
    except RuntimeConfigurationResolutionError as error:
        raise ApiError(
            status_code=503,
            code='AGENT_RUNTIME_CONFIGURATION_UNAVAILABLE',
            message='The active Agent runtime configuration cannot be loaded safely.',
            retryable=False,
        ) from error
    branch_evaluator = (
        runtime_policy.branch_evaluator() if runtime_policy else BranchRuleEvaluator()
    )
    previous_evaluation = latest_applied_branch_evaluation(repository, claim)
    branch_evaluation = branch_evaluator.evaluate(
        claim,
        latest_message=(payload.content.text if payload.content is not None else None),
        trigger_source_refs=[claimant_message.message_id],
        current_action=claim.claim_state.next_action,
        recomputation_reason='claimant_message',
        previous_evaluation=previous_evaluation,
    )
    persisted_review_signals = repository.list_review_signals(claim_id, principal.subject)
    agent_context = AgentTurnContext(
        claim=claim,
        session_id=session_id,
        model_profile_id=session.model_profile_id,
        trigger_message_id=claimant_message.message_id,
        message_text=payload.content.text if payload.content is not None else None,
        evidence_refs=payload.evidence_refs,
        professional_review_required=any(
            signal.code == 'POLICY_RETRIEVAL_UNCERTAINTY' for signal in persisted_review_signals
        ),
        branch_evaluation=branch_evaluation,
        runtime_configuration_snapshot=(
            runtime_policy.runtime_snapshot if runtime_policy is not None else None
        ),
        runtime_policy=runtime_policy,
        provenance_messages=tuple(
            provenance_messages_for_fields(
                repository,
                claim_id=claim_id,
                customer_id=principal.subject,
                fields=claim.form.values(),
            )
        ),
    )
    proposal = agent.propose_turn(agent_context)
    if runtime_policy is not None:
        enforce_agent_proposal(runtime_policy, proposal)
    preliminary_authority = validate_proposal(proposal)
    if preliminary_authority.outcome is AuthorityOutcome.AUTHORISED:
        _validate_tool_requests(proposal, branch_evaluation)

    context_tool_results = list(proposal.tool_results)
    requested_context_tools = {
        str(request.get('tool'))
        for request in proposal.required_tools
        if preliminary_authority.outcome is AuthorityOutcome.AUTHORISED
        and request.get('tool') in _CONTEXT_TOOL_OPERATIONS
    }
    if requested_context_tools:
        if any(
            result.get('tool') in {'knowledge_search', 'policy_history', 'claim_history'}
            for result in context_tool_results
        ):
            raise ApiError(
                status_code=503,
                code='AGENT_TOOL_NOT_PERMITTED',
                message='The Agent attempted a second context-tool round.',
            )
        policy_outcome = _execute_policy_search(
            repository,
            policy_history_adapter,
            claim_id,
            principal.subject,
            proposal,
        )
        history_outcome = _execute_claim_history_search(
            repository,
            policy_history_adapter,
            claim_id,
            principal.subject,
            proposal,
        )
        for tool, outcome in (
            ('policy_history', policy_outcome),
            ('claim_history', history_outcome),
        ):
            if tool not in requested_context_tools:
                continue
            if outcome is None:
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent supplied an incomplete context-tool request.',
                )
            _record, tool_result = outcome
            context_tool_results.append(tool_result)
        if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY:
            proposal = agent.propose_turn(
                replace(agent_context, tool_results=tuple(context_tool_results))
            )
            if runtime_policy is not None:
                enforce_agent_proposal(runtime_policy, proposal)
            replanned_authority = validate_proposal(proposal)
            if replanned_authority.outcome is AuthorityOutcome.AUTHORISED:
                _validate_tool_requests(proposal, branch_evaluation)
            if replanned_authority.outcome is AuthorityOutcome.AUTHORISED and any(
                request.get('tool') in _CONTEXT_TOOL_OPERATIONS
                for request in proposal.required_tools
            ):
                raise ApiError(
                    status_code=503,
                    code='AGENT_TOOL_NOT_PERMITTED',
                    message='The Agent attempted a second context-tool round.',
                )
            proposal = replace(
                proposal,
                tool_results=[*context_tool_results, *proposal.tool_results],
            )
        else:
            proposal = replace(proposal, tool_results=context_tool_results)
    _validate_failed_retrieval_changes(proposal, message_text)
    authority = validate_proposal(proposal)
    if proposal.action_code is not None:
        return _submit_namespaced_runtime_turn(
            repository,
            principal,
            claim_id,
            session_id,
            claim,
            session,
            claimant_message,
            proposal,
            authority,
            runtime_policy,
            branch_evaluator,
            previous_evaluation,
            message_text,
            route,
            key,
            fingerprint,
            expected_revision,
        )
    if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY:
        raise ApiError(
            status_code=422,
            code='LEGACY_AGENT_ACTION_DEPRECATED',
            message='Model responses using the deprecated legacy action contract are rejected.',
            retryable=False,
        )
    executed_state_changes = authorised_state_changes(proposal, authority)
    effective_customer_reason = proposal.customer_reason
    effective_customer_response = proposal.customer_response
    effective_next_step = _effective_next_step(proposal.customer_next_step, authority.outcome)
    form_changes = _build_form_changes(
        claim.form,
        proposal.form_changes,
        claimant_message,
        timestamp,
        authority.outcome,
        proposal.proposal_source,
        branch_evaluation,
        _grounding_source_refs(proposal.tool_results),
    )
    contents_item_changes = _build_contents_item_changes(
        claim,
        proposal,
        claimant_message,
        timestamp,
        authority.outcome,
        branch_evaluation,
    )
    conflicting_fields = [
        field_code
        for field_code, field in form_changes.items()
        if field.status is FormStatus.DISPUTED
    ]
    conflicting_contents = [
        item for item in contents_item_changes if item.status is FormStatus.DISPUTED
    ]
    clarification_items = [
        *conflicting_fields,
        *(['contents.items'] if conflicting_contents else []),
    ]
    if clarification_items:
        effective_customer_reason = 'A material incident detail needs clarification.'
        effective_customer_response = (
            'I have two different versions of an incident detail. Which version should '
            'Northwind use?'
        )
        effective_next_step = CustomerNextStep(
            status='clarification_needed',
            summary='Clarify the conflicting incident detail.',
            responsible_party=ResponsibleParty.CLAIMANT,
            required_items=clarification_items,
        )
    discrepancy_candidates = [
        DiscrepancyCandidate(
            candidate_id=new_id('dsc'),
            field_code=field_code,
            source_refs=form_changes[field_code].source_refs,
            created_at=timestamp,
        )
        for field_code in conflicting_fields
        if len(form_changes[field_code].source_refs) >= 2
    ]
    discrepancy_candidates.extend(
        DiscrepancyCandidate(
            candidate_id=new_id('dsc'),
            field_code='contents.items',
            source_refs=item.source_refs,
            created_at=timestamp,
        )
        for item in conflicting_contents
        if len(item.source_refs) >= 2
    )
    session_after_questions = session
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
        contents_item_changes = []

    policy_retrieval = next(
        (
            record
            for record in reversed(repository.list_retrieval_records(claim_id, principal.subject))
            if isinstance(record, PolicyRetrievalRecord)
            and record.retrieval_id in _tool_source_refs(proposal.tool_results)
        ),
        None,
    )
    inferred_incident_type = claim.incident_type
    proposed_family = form_changes.get('claim.product_family')
    if (
        proposed_family is not None
        and proposed_family.status is FormStatus.CONFIRMED
        and isinstance(proposed_family.value, str)
        and proposed_family.value in {'motor', 'home', 'contents'}
    ):
        inferred_incident_type = proposed_family.value

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
        detected_support_need = support_need_for_intent(detect_support_intent(message_text))
        support_need = (
            SupportNeed.URGENT
            if proposal.action is AgentAction.URGENT_HANDOFF
            else detected_support_need or SupportNeed.HUMAN_REQUESTED
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
        projected_contents = _apply_contents_item_changes(
            claim.contents_items,
            contents_item_changes,
        )
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
                    'contents_items': projected_contents,
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
        has_confirmation_work = any(
            field.status in {FormStatus.PROPOSED, FormStatus.DISPUTED}
            for field in form_changes.values()
        ) or any(
            item.status in {FormStatus.PROPOSED, FormStatus.DISPUTED}
            for item in contents_item_changes
        )
        if (
            not professional_review
            and not has_confirmation_work
            and (form_changes or contents_item_changes or pending_evidence is not None)
            and not any(
                code in proposal.reason_codes
                for code in {'SAFETY_STATUS_RECORDED', 'POLICY_WORDING_REVIEW_NEEDED'}
            )
        ):
            projected_claim = claim.model_copy(
                update={
                    'form': projected_form,
                    'contents_items': projected_contents,
                    'incident_type': inferred_incident_type,
                }
            )
            requirements = branch_evaluator.evaluate(
                projected_claim,
                latest_message=message_text,
                trigger_source_refs=[claimant_message.message_id],
                current_action=next_action,
                recomputation_reason='agent_turn_progress_preview',
                previous_evaluation=previous_evaluation,
            ).requirements
            effective_next_step = next_requirement_step(requirements)
            if requirements.ready:
                effective_customer_response = (
                    'Thanks. I have saved those details. Your confirmed report is ready for '
                    'claim creation.'
                )
            else:
                next_field = intake_field_for_requirement(requirements.next_required_item)
                if next_field is not None:
                    effective_customer_response = (
                        f'{effective_customer_response.rstrip()} {next_field.prompt}'
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
                'contents_items': projected_contents,
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
    session_after_questions, effective_next_step, effective_customer_response = (
        _apply_question_accounting(
            session_after_questions,
            proposal,
            effective_next_step,
            effective_customer_response,
            claimant_message.message_id,
            timestamp,
        )
    )
    if updated_claim.customer_next_step != effective_next_step:
        updated_claim = updated_claim.model_copy(update={'customer_next_step': effective_next_step})
    resulting_revision = updated_claim.revision
    updated_session = session_after_questions.model_copy(
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
        tool_results=proposal.tool_results,
        next_action_requirements=proposal.next_action_requirements,
        handoff_priority=proposal.handoff_priority,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        customer_next_step=effective_next_step,
        authority=authority,
        proposal_source=proposal.proposal_source,
        model_provenance=proposal.model_provenance,
        runtime_configuration=(runtime_policy.provenance() if runtime_policy else None),
        form_changes=form_changes,
        contents_item_changes=contents_item_changes,
        resulting_revision=resulting_revision,
        created_at=timestamp,
        discrepancy_candidates=discrepancy_candidates,
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
    applied_evaluation = branch_evaluator.evaluate(
        updated_claim,
        latest_message=(payload.content.text if payload.content is not None else None),
        trigger_source_refs=[claimant_message.message_id],
        current_action=updated_claim.claim_state.next_action,
        recomputation_reason='agent_turn_applied',
        previous_evaluation=previous_evaluation,
    )
    evaluation_record = BranchEvaluationRecord(
        evaluation_id=new_id('brn'),
        claim_id=claim_id,
        session_id=session_id,
        turn_id=claimant_message.message_id,
        evaluated_against_claim_revision=applied_evaluation.evaluated_against_claim_revision,
        resulting_claim_revision=resulting_revision,
        field_registry_version=applied_evaluation.field_registry_version,
        branch_rules_version=applied_evaluation.branch_rules_version,
        selected_family=applied_evaluation.selected_family,
        unresolved_family_conflict=applied_evaluation.unresolved_family_conflict,
        branch_results=applied_evaluation.branch_results,
        field_selection_results=applied_evaluation.field_selection,
        work_item_intents=applied_evaluation.work_item_intents,
        handoff_intents=applied_evaluation.handoff_intents,
        evidence_intents=applied_evaluation.evidence_intents,
        consent_intents=applied_evaluation.consent_intents,
        integration_intents=applied_evaluation.integration_intents,
        interruption_result=applied_evaluation.interruption_result,
        permitted_actions=applied_evaluation.permitted_actions,
        permitted_tools=applied_evaluation.permitted_tools,
        requirements=applied_evaluation.requirements,
        recomputation_reason=applied_evaluation.recomputation_reason,
        status=BranchEvaluationStatus.APPLIED,
        created_at=timestamp,
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
            evaluation_record,
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
