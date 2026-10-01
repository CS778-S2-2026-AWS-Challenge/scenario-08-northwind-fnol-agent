"""Claimant turn reduction and shared progress decisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from backend.core.errors import ApiError
from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.external_service_registry import ExternalLifecycleStatus
from backend.domain.field_registry import trusted_origin_assertion
from backend.domain.ids import new_id
from backend.domain.intake import next_requirement_step
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AgentProposalSource,
    AuthorityOutcome,
    BranchEvaluationRecord,
    BranchEvaluationStatus,
    ConfirmationRequestRecord,
    ContentsItem,
    Coverage,
    CustomerNextStep,
    CustomerSupport,
    DiscrepancyCandidate,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceState,
    EvidenceStatus,
    FormSource,
    FormStatus,
    HandoffRecord,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    ProposedFormChange,
    ResponsibleParty,
    SessionRecord,
    StructuredFormField,
    SupportNeed,
    Urgency,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.recovery_policy_registry import RecoveryTrigger, classify_recovery
from backend.domain.retrieval import PolicyRetrievalRecord, ReviewSignalRecord
from backend.domain.runtime import (
    ActionEnvelopeRecord,
    AgentProposalRecord,
    ExecutionPlanRecord,
    ExternalLifecycleContextCoordinate,
    RuntimeTurnRecords,
    RuntimeWorkItemRecord,
    ToolResultRecord,
    TurnPlanRecord,
    TurnResultRecord,
)
from backend.domain.support_intent import detect_support_intent, support_need_for_intent
from backend.repositories.protocols import IdempotencyRecord
from backend.services.claim_participants import synchronize_participants
from backend.services.external_service_offers import (
    build_offer_metadata,
    detected_service_intents,
    offer_work_item,
)
from backend.services.fact_resolution import (
    confirm_contents_item,
    confirm_form_field,
    resolve_form_change,
)
from backend.services.handoffs import prepare_support_handoff, updated_claim_for_handoff
from backend.services.policy_judgment import policy_judgment_signals
from backend.services.professional_reviews import build_policy_review_handoff

if TYPE_CHECKING:
    from backend.services.turn_proposal_validation import ValidatedTurn


def _recovery_policy_ref(trigger: RecoveryTrigger) -> str:
    policy = classify_recovery(trigger)
    return f'recovery-policy:{policy.policy_id}:{policy.version}'


@dataclass(frozen=True, slots=True)
class TurnRecords:
    customer_reason: str
    form_changes: dict[str, StructuredFormField]
    contents_item_changes: list[ContentsItem]
    discrepancy_candidates: list[DiscrepancyCandidate]
    pending_evidence: EvidenceRecord | None
    professional_review: bool
    agent_message: MessageRecord
    decision: AgentDecisionRecord
    idempotency: IdempotencyRecord
    evaluation_record: BranchEvaluationRecord
    runtime_records: RuntimeTurnRecords
    live_mutation_command: Any
    review_signals: list[ReviewSignalRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    claim: WorkingClaim
    agent_message_text: str
    handoff: HandoffRecord | None
    confirmation_request: ConfirmationRequestRecord | None
    branch_evaluation: Any
    records: TurnRecords
    session: SessionRecord
    rejected_parts: list[dict[str, str]]
    offers: list[Any] = field(default_factory=list)


def shown_values_fingerprint(
    form: dict[str, StructuredFormField],
    field_codes: list[str],
    contents_items: list[ContentsItem] | None = None,
) -> str:
    payload: list[tuple[Any, ...]] = [
        (code, form[code].value, form[code].current_assertion_id)
        for code in sorted(field_codes)
        if code in form
    ]
    if 'contents.items' in field_codes:
        payload.append(
            (
                'contents.items',
                [
                    item.model_dump(
                        mode='json',
                        include={
                            'item_id',
                            'description',
                            'category',
                            'quantity',
                            'brand',
                            'model',
                            'loss_type',
                            'ownership',
                            'estimated_value',
                            'current_assertion_id',
                        },
                    )
                    for item in sorted(contents_items or [], key=lambda item: item.item_id)
                ],
            )
        )
    return sha256(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()).hexdigest()


_EXPLICIT_BATCH_ACCEPT_PATTERN = re.compile(
    r'^\s*(?:(?:yes|yep|yeah)(?:\s*,?\s+(?:all (?:correct|right)'
    r"|that(?:'s| is) (?:all )?(?:correct|right)))?"
    r"|correct|that(?:'s|s| is)? (?:all )?(?:correct|right)|all correct|confirm(?:ed)?"
    r"|looks? good|that(?:'s|s| is)? everything|是|对|没问题)\s*[.!\u3002\uff01]?\s*$",
    re.IGNORECASE,
)


def is_explicit_batch_accept(message_text: str) -> bool:
    """Accept only an unqualified short acceptance of the displayed batch."""
    return bool(
        _EXPLICIT_BATCH_ACCEPT_PATTERN.fullmatch(message_text.strip().replace('\u2019', "'"))
    )


def can_confirm(
    claim: WorkingClaim,
    merged_form: dict[str, StructuredFormField],
    confirmation: ConfirmationRequestRecord | None,
    *,
    revision_before_message: int,
    message_text: str,
    explicit_field_selection: bool = False,
    contents_items: list[ContentsItem] | None = None,
) -> bool:
    return bool(
        confirmation is not None
        and bool(confirmation.field_codes)
        and confirmation.claim_id == claim.claim_id
        and confirmation.claim_revision == revision_before_message
        and (
            explicit_field_selection or claim.customer_next_step.status == 'confirmation_requested'
        )
        and confirmation.shown_values_fingerprint
        == shown_values_fingerprint(merged_form, confirmation.field_codes, contents_items)
        and (explicit_field_selection or is_explicit_batch_accept(message_text))
    )


def confirm_field(
    field: StructuredFormField, message: MessageRecord, timestamp: datetime, customer_id: str
) -> StructuredFormField:
    return confirm_form_field(
        field,
        timestamp=timestamp,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=customer_id),
        source_ref=message.message_id,
    )


def compose_reply(
    safety_interrupt: Any,
    open_handoffs: tuple[HandoffRecord, ...],
    model_reply: str,
    next_question: str | None,
    *,
    model_authored: bool = False,
) -> str:
    """Assemble the claimant-visible text.

    For a model-authored turn the model's reply is the whole conversation; the
    only Runtime words allowed in front of it are the safety notice, which is
    fixed wording the model is told not to repeat. Controlled fixtures keep the
    older composition because their replies are templates, not conversation.
    """

    parts = []
    if safety_interrupt is not None:
        parts.append(safety_interrupt.safety_notice)
    elif open_handoffs and not model_authored:
        parts.append('Northwind support has your request. You can keep adding details here.')
    parts.append(model_reply.strip())
    if model_authored:
        return ' '.join(part for part in parts if part)
    if next_question and next_question not in model_reply:
        parts.append(next_question)
    if open_handoffs and next_question:
        parts.append('You can answer when you are ready; your support request will continue.')
    return ' '.join(part for part in parts if part)


def detect_pending_evidence(
    claim: WorkingClaim, message: MessageRecord, timestamp: datetime
) -> EvidenceRecord | None:
    from backend.services.agent import PENDING_POLICE_REPORT_PATTERNS

    text = str(message.content.get('text') or '')
    current = claim.form.get('authorities.police_report_reference')
    if current is not None and current.status in {
        FormStatus.PENDING_GENERATION,
        FormStatus.CONFIRMED,
    }:
        return None
    if not any(pattern.search(text) for pattern in PENDING_POLICE_REPORT_PATTERNS):
        return None
    return EvidenceRecord(
        evidence_id=new_id('evd'),
        claim_id=claim.claim_id,
        kind='police_report',
        status=EvidenceStatus.PENDING,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        related_fields=['authorities.police_report_reference'],
        needed_for=['later_action'],
        provenance={'reported_in_message_id': message.message_id},
        claimant_note=text,
        wait_type='claimant',
        responsible_party='claimant',
        context_summary='The police report is expected later; intake can continue.',
        created_at=timestamp,
        updated_at=timestamp,
    )


def recompute_progress(
    claim: WorkingClaim,
    evaluation: Any,
    *,
    open_handoffs: tuple[HandoffRecord, ...] = (),
    proposed_next_step: CustomerNextStep | None = None,
) -> tuple[WorkflowState, CustomerNextStep]:
    if (
        claim.terminal_disposition is not None
        or claim.claim_state.workflow_state is WorkflowState.CREATED
    ):
        return claim.claim_state.workflow_state, claim.customer_next_step
    if (
        claim.claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW
        and proposed_next_step is not None
        and proposed_next_step.status == 'professional_review_queued'
    ):
        # The controlled PRES-02 policy-review contract remains an explicit
        # compatibility path; v8 does not propose this legacy status.
        return claim.claim_state.workflow_state, proposed_next_step
    active_handoff = next(
        (
            item
            for item in reversed(open_handoffs)
            if item.status.value not in {'resolved', 'cancelled'}
        ),
        None,
    )
    if active_handoff is not None:
        return claim.claim_state.workflow_state, CustomerNextStep(
            status='awaiting_staff',
            summary=active_handoff.packet.promised_next_step,
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
            required_items=list(proposed_next_step.required_items) if proposed_next_step else [],
        )
    if claim.claim_state.workflow_state not in {
        WorkflowState.COLLECTING,
        WorkflowState.READY_FOR_NEXT,
    }:
        return claim.claim_state.workflow_state, claim.customer_next_step
    state = (
        WorkflowState.READY_FOR_NEXT if evaluation.requirements.ready else WorkflowState.COLLECTING
    )
    return state, proposed_next_step or next_requirement_step(evaluation.requirements)


def model_turn_next_step(requirements: Any, *, action: str) -> CustomerNextStep:
    """Project a model-authored turn that asked nothing into the next-step contract.

    The summary is a neutral progress label, never a question: the model owns
    every question the claimant sees. ``required_items`` still lists what the
    report is waiting on so the form panel can show it.
    """

    if action == 'summarize':
        # The model read the report back; a plain "yes" next turn binds to it.
        return CustomerNextStep(
            status='confirmation_requested',
            summary='Review the summary above.',
            responsible_party=ResponsibleParty.CLAIMANT,
            required_items=list(requirements.recorded),
        )
    if requirements.ready:
        return CustomerNextStep(
            status='ready_to_create',
            summary='Your report is ready to send to the claims team.',
            responsible_party=ResponsibleParty.CLAIMANT,
        )
    return CustomerNextStep(
        status='more_information_needed',
        summary='Collecting details.',
        responsible_party=ResponsibleParty.CLAIMANT,
        required_items=list(requirements.unresolved),
    )


def apply_progress(
    claim: WorkingClaim,
    evaluation: Any,
    *,
    open_handoffs: tuple[HandoffRecord, ...] = (),
    proposed_next_step: CustomerNextStep | None = None,
    authorized_next_step: CustomerNextStep | None = None,
    authorized_workflow_state: WorkflowState | None = None,
) -> WorkingClaim:
    if authorized_next_step is not None:
        claim = claim.model_copy(update={'customer_next_step': authorized_next_step})
    state, step = recompute_progress(
        claim, evaluation, open_handoffs=open_handoffs, proposed_next_step=proposed_next_step
    )
    if authorized_workflow_state is not None:
        state = authorized_workflow_state
    return claim.model_copy(
        update={
            'claim_state': claim.claim_state.model_copy(update={'workflow_state': state}),
            'customer_next_step': step,
        }
    )


def reduce_turn(
    claim: WorkingClaim,
    validated: ValidatedTurn | None,
    *,
    branch_evaluator: BranchRuleEvaluator,
    safety_interrupt: Any,
    open_handoffs: tuple[HandoffRecord, ...],
    session: SessionRecord,
    claimant_message: MessageRecord,
    eligible_service_ids: frozenset[str],
    timestamp: datetime,
    revision_before_message: int,
    confirmation_before_message: ConfirmationRequestRecord | None,
    proposal: Any,
    authority: Any,
    repository: Any,
    principal: Any,
    branch_evaluation: Any,
    previous_evaluation: Any,
    turn_evidence: tuple[Any, ...],
    message_text: str,
    runtime_trace: Any,
    runtime_policy: Any,
    prepared_action_code: str | None,
    key: str,
    fingerprint: str,
    request_checkpoint: IdempotencyRecord,
    turn_route: Any,
    agent_context: Any,
    selected_external_service_intents: list[dict[str, str]],
    turn_family_resolution: Any,
    external_capability_dispatcher: Any,
) -> TurnOutcome:
    """Reduce facts and authority into one next Claim; persistence is a separate CAS."""
    from backend.services import messages as helpers
    from backend.services.agent import authorised_state_changes
    from backend.services.controlled_turn_compatibility import (
        _effective_next_step,
        _safe_model_customer_content,
    )

    _build_form_changes = helpers._build_form_changes
    _grounding_source_refs = helpers._grounding_source_refs
    _build_contents_item_changes = helpers._build_contents_item_changes
    _pending_evidence_for_proposal = helpers._pending_evidence_for_proposal
    _tool_source_refs = helpers._tool_source_refs
    _apply_contents_item_changes = helpers._apply_contents_item_changes
    _professional_review_requested = helpers._professional_review_requested
    _apply_question_accounting = helpers._apply_question_accounting
    _live_mutation_command = helpers._live_mutation_command
    claim_id = claim.claim_id
    session_id = session.session_id
    expected_revision = claim.revision
    checkpoint_idempotency = request_checkpoint
    route = request_checkpoint.route
    confirmation_revision_before_message = revision_before_message

    executed_state_changes = authorised_state_changes(proposal, authority)
    effective_customer_reason = proposal.customer_reason
    effective_customer_response = (
        validated.reply if validated is not None else proposal.customer_response
    )
    effective_next_step = (
        model_turn_next_step(branch_evaluation.requirements, action=validated.action)
        if validated is not None
        else _effective_next_step(proposal.customer_next_step, authority.outcome)
    )
    if (
        proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY
        and validated is None
        and authority.outcome is not AuthorityOutcome.AUTHORISED
    ):
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
        _grounding_source_refs(proposal.tool_results),
        {item.evidence_id: item.media_type for item in turn_evidence},
    )
    contents_item_changes = _build_contents_item_changes(
        claim,
        proposal,
        claimant_message,
        timestamp,
        authority.outcome,
        branch_evaluation,
        {item.evidence_id: item.media_type for item in turn_evidence},
    )
    projected_confirmation_form = {**claim.form, **form_changes}
    projected_confirmation_contents = _apply_contents_item_changes(
        claim.contents_items, contents_item_changes
    )
    # loss.description restates the same loss motor/contents already record at item level
    # (the vehicle's confirmed damage, a contents item's own description). Runtime derives
    # it here from that already-confirmed source instead of asking the claimant to state
    # the same loss twice; it lands as an inference, so needs_confirmation still requires
    # the claimant to see and accept it in the next batch confirmation before it counts as
    # a claimant-stated fact -- Runtime proposes, the claimant still decides.
    if 'loss.description' not in projected_confirmation_form:
        derived_loss_description: str | None = None
        # The originating item-level assertion. The derived fact keeps that assertion's
        # own source refs and the claimant's own words, not the current message: the
        # vehicle damage or contents item may have been stated turns ago, and the audit
        # trail must point at the message that actually supported it.
        origin_source_refs: list[str] = []
        origin_reported_text: str | None = None
        # This turn's own family proposal, not the pre-turn branch_evaluation: on the
        # very turn that confirms both product_family and the item-level fact together
        # (the common case), the evaluation Runtime was handed before this message
        # arrived has not seen either yet.
        current_product_family_field = projected_confirmation_form.get('claim.product_family')
        current_product_family = (
            current_product_family_field.value
            if current_product_family_field is not None
            else claim.incident_type
        )
        # trusted_origin_assertion is the same predicate branch_registry._required_set uses
        # to decide whether to stop requiring the field, so the two paths always agree: a
        # confirmed field/item with no current assertion, or one recorded with no source
        # refs of its own (a legacy record), is not derived from here, and is not silently
        # dropped from requirements there either. Provenance comes from that current
        # assertion only -- the field-level source_refs list is cumulative across the
        # assertion history, so after a correction it still names the superseded message,
        # and citing that as support for the corrected value would be false.
        if current_product_family == 'motor':
            vehicle_damage = projected_confirmation_form.get('vehicle.damage_description')
            if vehicle_damage is not None and vehicle_damage.status is FormStatus.CONFIRMED:
                origin_assertion = trusted_origin_assertion(
                    vehicle_damage.current_assertion_id, vehicle_damage.assertions
                )
                if origin_assertion is not None:
                    derived_loss_description = str(vehicle_damage.value)
                    origin_source_refs = list(origin_assertion.source_refs)
                    origin_reported_text = origin_assertion.reported_text
        elif current_product_family == 'contents':
            # Any confirmed item with a trusted origin, in any position, not only the first.
            confirmed_item = next(
                (
                    item
                    for item in projected_confirmation_contents
                    if item.status is FormStatus.CONFIRMED
                    and trusted_origin_assertion(item.current_assertion_id, item.assertions)
                    is not None
                ),
                None,
            )
            if confirmed_item is not None:
                origin_item_assertion = trusted_origin_assertion(
                    confirmed_item.current_assertion_id, confirmed_item.assertions
                )
                assert origin_item_assertion is not None  # guaranteed by the generator filter above
                derived_loss_description = confirmed_item.description
                origin_source_refs = list(origin_item_assertion.source_refs)
                origin_reported_text = origin_item_assertion.reported_text
        if derived_loss_description is not None:
            derived = resolve_form_change(
                field_code='loss.description',
                existing=None,
                proposal=ProposedFormChange(
                    field_code='loss.description',
                    value=derived_loss_description,
                    source=FormSource.INFERENCE,
                    status=FormStatus.PROPOSED,
                    needed_for=NeededFor.CURRENT_ACTION,
                    reported_text=origin_reported_text,
                ),
                source_ref=origin_source_refs[0],
                message_text=None,
                timestamp=timestamp,
                accepted_status=FormStatus.PROPOSED,
                updated_by=ActorReference(actor_type=ActorType.AGENT, actor_id='runtime'),
            )
            # resolve_form_change records one source ref per assertion; carry every ref the
            # originating assertion had so a multi-source origin is not narrowed to one.
            derived = derived.model_copy(
                update={
                    'source_refs': origin_source_refs,
                    'assertions': [
                        item.model_copy(update={'source_refs': origin_source_refs})
                        for item in derived.assertions
                    ],
                }
            )
            form_changes['loss.description'] = derived
            projected_confirmation_form['loss.description'] = derived
    batch_confirmed = confirmation_before_message is not None and can_confirm(
        claim,
        projected_confirmation_form,
        confirmation_before_message,
        revision_before_message=revision_before_message,
        message_text=message_text,
        contents_items=projected_confirmation_contents,
    )
    if batch_confirmed and confirmation_before_message is not None:
        for field_code in confirmation_before_message.field_codes:
            if field_code in projected_confirmation_form:
                form_changes[field_code] = confirm_field(
                    projected_confirmation_form[field_code],
                    claimant_message,
                    timestamp,
                    claim.customer_id,
                )
            elif field_code == 'contents.items':
                contents_item_changes = [
                    confirm_contents_item(
                        item,
                        timestamp=timestamp,
                        updated_by=ActorReference(
                            actor_type=ActorType.CLAIMANT, actor_id=claim.customer_id
                        ),
                        source_ref=claimant_message.message_id,
                    )
                    if item.status is FormStatus.PROPOSED
                    else item
                    for item in projected_confirmation_contents
                ]
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
        if validated is None:
            # Controlled fixtures have no conversational reply of their own.
            # A model-authored turn keeps its reply; the disputed fields are
            # surfaced to the model through the next turn's form projection.
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
    pending_evidence = (
        detect_pending_evidence(claim, claimant_message, timestamp)
        if validated is not None
        else _pending_evidence_for_proposal(claim_id, proposal, claimant_message, timestamp)
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
        and proposed_family.status in {FormStatus.CONFIRMED, FormStatus.PROPOSED}
        and isinstance(proposed_family.value, str)
        and proposed_family.value in {'motor', 'home', 'contents'}
        and (claim.incident_type is None or proposed_family.status is FormStatus.CONFIRMED)
    ):
        # The model's understood family drives the report from the first turn;
        # a confirmed family may still correct an earlier inferred one.
        inferred_incident_type = proposed_family.value

    next_action = claim.claim_state.next_action
    state_updates: dict[str, Any] = {}
    for state_change in executed_state_changes:
        if state_change.path == 'claim_state.next_action':
            raw_action = (
                state_change.to.value
                if isinstance(state_change.to, AgentAction)
                else state_change.to
            )
            next_action = AgentAction(str(raw_action))
        elif state_change.path == 'claim_state.urgency' and state_change.to == 'urgent':
            if claim.claim_state.urgency is not Urgency.IMMEDIATE_SAFETY_RISK:
                state_updates['urgency'] = Urgency.URGENT
        elif state_change.path == 'claim_state.customer_support' and not open_handoffs:
            state_updates['customer_support'] = CustomerSupport(state_change.to)
    handoff: HandoffRecord | None = None
    professional_review = False
    projected_form = {**claim.form, **form_changes}
    projected_contents = _apply_contents_item_changes(claim.contents_items, contents_item_changes)
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
        handoff, effective_next_step, _handoff_changed = prepare_support_handoff(
            repository,
            claim.model_copy(
                update={
                    'form': projected_form,
                    'contents_items': projected_contents,
                    'incident_type': inferred_incident_type,
                }
            ),
            support_need=support_need,
            reason=proposal.customer_reason,
            preferred_channel=None,
            source_message_id=claimant_message.message_id,
            reason_code=proposal.reason_codes[0],
        )
        updated_claim = updated_claim_for_handoff(claim, handoff, effective_next_step)
        updated_claim = updated_claim.model_copy(
            update={
                'updated_at': timestamp,
                'form': projected_form,
                'contents_items': projected_contents,
                'incident_type': inferred_incident_type,
            }
        )
    else:
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
        updated_claim = claim.model_copy(
            update={
                'claim_state': claim.claim_state.model_copy(
                    update={
                        **state_updates,
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
                            {'evidence': EvidenceState.PENDING}
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
                'revision': claim.revision + 1,
                'updated_at': timestamp,
            }
        )
    updated_claim = synchronize_participants(updated_claim, form_changes)
    # A handoff owns responsibility; later model next-action proposals cannot
    # release it or create a second owner.
    if open_handoffs and handoff is None:
        updated_claim = updated_claim.model_copy(
            update={
                'claim_state': updated_claim.claim_state.model_copy(
                    update={
                        'workflow_state': claim.claim_state.workflow_state,
                        'next_action': claim.claim_state.next_action,
                    }
                )
            }
        )
    if proposal.validated_turn is not None:
        branch_evaluator = (
            runtime_policy.branch_evaluator(model_family_judgment=True)
            if runtime_policy is not None
            else BranchRuleEvaluator(model_family_judgment=True)
        )
    applied_evaluation = branch_evaluator.evaluate(
        updated_claim,
        latest_message=(message_text),
        trigger_source_refs=[claimant_message.message_id],
        current_action=updated_claim.claim_state.next_action,
        recomputation_reason='agent_turn_applied',
        previous_evaluation=previous_evaluation,
    )
    question = None
    if validated is not None:
        # The model decides whether this turn asks and what it asks. Runtime
        # projects that choice into the next step; it never substitutes a
        # template question of its own.
        if validated.next_question is not None:
            question = validated.next_question.wording
            effective_next_step = CustomerNextStep(
                status='more_information_needed',
                summary=question,
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=list(validated.next_question.field_codes),
            )
        else:
            effective_next_step = model_turn_next_step(
                applied_evaluation.requirements, action=validated.action
            )
    elif (
        proposal.proposal_source is AgentProposalSource.CONTROLLED_AGENT
        and authority.outcome is AuthorityOutcome.AUTHORISED
        and updated_claim.claim_state.workflow_state
        in {WorkflowState.COLLECTING, WorkflowState.READY_FOR_NEXT}
        and updated_claim.terminal_disposition is None
        and not open_handoffs
        and handoff is None
        and not clarification_items
        and effective_next_step.responsible_party is ResponsibleParty.CLAIMANT
        and effective_next_step.status not in {'confirmation_required', 'confirmation_requested'}
        and set(effective_next_step.required_items) & set(applied_evaluation.requirements.satisfied)
    ):
        # Controlled fixtures propose their question against the pre-turn form.
        # Once this turn satisfies that request, project the current requirement
        # instead of retaining the answered field beside the fresh fallback text.
        effective_next_step = next_requirement_step(applied_evaluation.requirements)
    progress_state, progress_next_step = recompute_progress(
        updated_claim,
        applied_evaluation,
        open_handoffs=tuple([*open_handoffs, *([handoff] if handoff is not None else [])]),
        proposed_next_step=effective_next_step,
    )
    if (
        updated_claim.claim_state.workflow_state != progress_state
        or updated_claim.customer_next_step != progress_next_step
    ):
        updated_claim = updated_claim.model_copy(
            update={
                'claim_state': updated_claim.claim_state.model_copy(
                    update={'workflow_state': progress_state}
                ),
                'customer_next_step': progress_next_step,
            }
        )
    effective_next_step = progress_next_step
    confirmation_request = None
    if validated is not None and validated.action == 'summarize' and validated.summary_fields:
        # The model read these fields back in its own words. Runtime records
        # exactly which fields and values were shown so a later "yes" can be
        # bound to this summary and nothing else.
        shown_codes = [
            code
            for code in validated.summary_fields
            if code in updated_claim.form
            or (code == 'contents.items' and updated_claim.contents_items)
        ]
        if shown_codes:
            confirmation_request = ConfirmationRequestRecord(
                confirmation_id=new_id('cnf'),
                claim_id=claim.claim_id,
                claim_revision=updated_claim.revision,
                field_codes=shown_codes,
                shown_values_fingerprint=shown_values_fingerprint(
                    updated_claim.form, shown_codes, updated_claim.contents_items
                ),
                created_at=timestamp,
            )
    if (
        proposal.proposal_source is not AgentProposalSource.CONTROLLED_AGENT
        or safety_interrupt is not None
    ):
        effective_customer_response = compose_reply(
            safety_interrupt,
            tuple([*open_handoffs, *([handoff] if handoff is not None else [])]),
            effective_customer_response,
            question,
            model_authored=validated is not None,
        )
    session_after_questions, accounted_next_step, effective_customer_response = (
        _apply_question_accounting(
            session_after_questions,
            proposal,
            effective_next_step,
            effective_customer_response,
            claimant_message.message_id,
            timestamp,
            during_handoff=bool(open_handoffs or handoff),
            requirements_ready=applied_evaluation.requirements.ready,
        )
    )
    if accounted_next_step != effective_next_step:
        updated_claim = apply_progress(
            updated_claim,
            applied_evaluation,
            open_handoffs=tuple([*open_handoffs, *([handoff] if handoff else [])]),
            proposed_next_step=accounted_next_step,
        )
    live_mutation_command = _live_mutation_command(
        claim=claim,
        claimant_message=claimant_message,
        idempotency_key=key,
        form_changes=form_changes,
        contents_item_changes=contents_item_changes,
        handoff=handoff,
        pending_evidence=pending_evidence,
        runtime_policy=runtime_policy,
    )
    effective_next_step = updated_claim.customer_next_step
    judgment_signals: list[ReviewSignalRecord] = []
    judgment_rejections: list[dict[str, str]] = []
    if validated is not None and validated.policy_judgment_proposals:
        if authority.outcome is not AuthorityOutcome.AUTHORISED:
            judgment_rejections = [
                {'kind': item.kind, 'reason': 'turn_not_authorized'}
                for item in validated.policy_judgment_proposals
            ]
        else:
            judgment_signals, judgment_rejections = policy_judgment_signals(
                updated_claim,
                validated.policy_judgment_proposals,
                authorized_knowledge=validated.policy_judgment_sources,
                trigger_message_id=claimant_message.message_id,
                created_at=timestamp,
                handoff_active=bool(open_handoffs or handoff or safety_interrupt),
            )
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
        runtime_trace_id=runtime_trace.trace_id if runtime_trace is not None else None,
        message_turn_kind='legacy_agent',
        message_turn_revision=resulting_revision,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        action_registry_version=(
            live_mutation_command.contract_version if live_mutation_command is not None else None
        ),
        action_code=(
            live_mutation_command.action_code
            if live_mutation_command is not None
            else prepared_action_code
        ),
        target_ref=(
            claim_id
            if live_mutation_command is not None or prepared_action_code is not None
            else None
        ),
        revision_before_message=confirmation_revision_before_message,
        confirmation_checkpoint=checkpoint_idempotency.confirmation_checkpoint,
        inbound_checkpoint=checkpoint_idempotency.inbound_checkpoint,
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
    runtime_turn_id = new_id('turn')
    external_service_intents = (
        proposal.external_service_intents
        if proposal.validated_turn is not None
        else selected_external_service_intents
        if proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY
        else detected_service_intents(
            message_text,
            proposal.external_service_intents,
            product_family=turn_family_resolution.product_family,
        )
    )
    if handoff is not None or agent_context.open_handoffs:
        external_service_intents = []
    runtime_directive = (
        runtime_trace.runtime_action_code if runtime_trace is not None else 'runtime.continue'
    )
    runtime_proposal = AgentProposalRecord(
        proposal_id=new_id('apr'),
        turn_id=runtime_turn_id,
        claim_id=claim_id,
        session_id=session_id,
        action_code=runtime_trace.action_code
        if runtime_trace is not None
        else 'conversation.answer',
        runtime_directive=runtime_directive,
        reason_codes=list(proposal.reason_codes),
        customer_reason=effective_customer_reason,
        customer_response=effective_customer_response,
        customer_next_step=effective_next_step,
        evidence_id=proposal.evidence_id,
        source_claim_id=proposal.source_claim_id,
        removal_scope=proposal.removal_scope,
        form_changes=list(proposal.form_changes),
        contents_item_changes=list(proposal.contents_item_changes),
        source_refs=sorted(_tool_source_refs(proposal.tool_results)),
        external_service_intents=external_service_intents,
        policy_judgment_proposals=list(validated.policy_judgment_proposals) if validated else [],
        policy_judgment_rejections=judgment_rejections,
        policy_judgment_signal_refs=[item.signal_id for item in judgment_signals],
        proposal_source=proposal.proposal_source,
        model_profile_id=session.model_profile_id,
        runtime_configuration=(runtime_policy.provenance() if runtime_policy else None),
        created_at=timestamp,
    )
    runtime_turn_plan = TurnPlanRecord(
        turn_id=runtime_turn_id,
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id=claimant_message.message_id,
        model_profile_id=session.model_profile_id,
        intents=sorted(turn_route.intents),
        conversation_moves=['acknowledge', 'collect_or_confirm_facts'],
        candidate_fields=sorted({change.field_code for change in proposal.form_changes}),
        tool_requests=list(proposal.required_tools),
        registry_versions=(
            {'external_service_lifecycle': agent_context.external_services[0].registry_version}
            if agent_context.external_services
            else {}
        ),
        external_lifecycle_context=[
            ExternalLifecycleContextCoordinate(
                registry_version=item.registry_version,
                service_identity=item.service_identity,
                operation_status=item.operation_status,
                result_status=item.result_status,
                result_verification=item.result_verification,
            )
            for item in agent_context.external_services
            if item.operation_status is not ExternalLifecycleStatus.CONSENT_REQUIRED
        ],
        runtime_directive=runtime_directive,
        limitations=list(
            dict.fromkeys(
                [
                    *(['model_runtime_trace_only'] if runtime_trace is not None else []),
                    *(['professional_review_required'] if professional_review else []),
                ]
            )
        ),
        created_at=timestamp,
    )
    primary_action_code = (
        runtime_trace.action_code
        if runtime_trace is not None
        else (
            'human.create_handoff'
            if proposal.action in {AgentAction.HANDOFF, AgentAction.URGENT_HANDOFF}
            else 'conversation.answer'
        )
    )
    primary_namespace = primary_action_code.split('.', 1)[0]
    envelope_records = [
        ActionEnvelopeRecord(
            envelope_id=new_id('env'),
            turn_id=runtime_turn_id,
            claim_id=claim_id,
            namespace=primary_namespace,
            action_code=primary_action_code,
            target_ref=agent_message.message_id,
            expected_revision=expected_revision,
            source_refs=[claimant_message.message_id],
            authority=authority,
            status='executed' if authority.outcome is AuthorityOutcome.AUTHORISED else 'rejected',
            idempotency_key=key,
            created_at=timestamp,
        )
    ]
    executed_action_code = (
        live_mutation_command.action_code
        if live_mutation_command is not None
        else prepared_action_code
    )
    if executed_action_code is not None and executed_action_code != primary_action_code:
        envelope_records.append(
            ActionEnvelopeRecord(
                envelope_id=new_id('env'),
                turn_id=runtime_turn_id,
                claim_id=claim_id,
                namespace=executed_action_code.split('.', 1)[0],
                action_code=executed_action_code,
                target_ref=claim_id,
                expected_revision=expected_revision,
                source_refs=[claimant_message.message_id],
                authority=authority,
                status='executed',
                idempotency_key=key,
                created_at=timestamp,
            )
        )
    tool_records: list[ToolResultRecord] = []
    recovery_work_items: list[RuntimeWorkItemRecord] = []
    if (
        runtime_trace is not None
        and runtime_trace.tool_call_id is not None
        and runtime_trace.tool_name is not None
        and runtime_trace.tool_result_status is not None
    ):
        tool_source_refs = [f'claim:{claim_id}:revision:{expected_revision}']
        if runtime_trace.tool_result_status == 'unavailable':
            tool_policy_ref = _recovery_policy_ref(
                RecoveryTrigger(
                    source='tool',
                    outcome_code='unavailable',
                    blocking=runtime_trace.runtime_action_code == 'runtime.fail_safe',
                )
            )
            tool_source_refs.append(tool_policy_ref)
            if runtime_trace.runtime_action_code == 'runtime.fail_safe':
                recovery_work_items.append(
                    RuntimeWorkItemRecord(
                        work_item_id=new_id('wki'),
                        claim_id=claim_id,
                        turn_id=runtime_turn_id,
                        kind='system',
                        subject_ref=runtime_trace.tool_name,
                        owner='system',
                        status='open',
                        blocks_action=runtime_trace.action_code,
                        source_refs=[claimant_message.message_id, tool_policy_ref],
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
        tool_records.append(
            ToolResultRecord(
                result_id=new_id('toolres'),
                turn_id=runtime_turn_id,
                claim_id=claim_id,
                tool_call_id=runtime_trace.tool_call_id,
                tool_name=runtime_trace.tool_name,
                status=runtime_trace.tool_result_status,
                output=dict(runtime_trace.tool_output),
                source_refs=tool_source_refs,
                limitations=[],
                created_at=timestamp,
            )
        )
    for index, context_result in enumerate(
        result for result in proposal.tool_results if result.get('tool') == 'evidence.history'
    ):
        raw_status = context_result.get('status')
        status = (
            raw_status
            if raw_status in {'succeeded', 'unavailable', 'failed', 'unknown'}
            else 'failed'
        )
        raw_refs = context_result.get('source_refs', [])
        source_refs = [str(ref) for ref in raw_refs] if isinstance(raw_refs, list) else []
        if status == 'unavailable':
            source_refs.append(
                _recovery_policy_ref(
                    RecoveryTrigger(source='retrieval', outcome_code='unavailable', blocking=False)
                )
            )
        raw_limitations = context_result.get('limitations', [])
        limitations = (
            [str(item) for item in raw_limitations]
            if isinstance(raw_limitations, list)
            else ['The Evidence history result did not contain valid limitations.']
        )
        tool_records.append(
            ToolResultRecord(
                result_id=new_id('toolres'),
                turn_id=runtime_turn_id,
                claim_id=claim_id,
                tool_call_id=f'context:{claimant_message.message_id}:evidence_history:{index}',
                tool_name='evidence.history',
                status=status,
                output=dict(context_result),
                source_refs=source_refs,
                limitations=limitations,
                created_at=timestamp,
            )
        )
    work_items = [
        RuntimeWorkItemRecord(
            work_item_id=new_id('wki'),
            claim_id=claim_id,
            turn_id=runtime_turn_id,
            kind='question' if item in effective_next_step.required_items else 'system',
            subject_ref=item,
            owner=(
                'claimant'
                if effective_next_step.responsible_party is ResponsibleParty.CLAIMANT
                else 'staff'
            ),
            status='open',
            blocks_action=effective_next_step.status,
            source_refs=[claimant_message.message_id],
            created_at=timestamp,
            updated_at=timestamp,
        )
        for item in effective_next_step.required_items
    ]
    work_items.extend(recovery_work_items)
    if professional_review and handoff is not None:
        review_policy_ref = _recovery_policy_ref(
            RecoveryTrigger(source='human', outcome_code='high_impact_review_required')
        )
        work_items.append(
            RuntimeWorkItemRecord(
                work_item_id=new_id('wki'),
                claim_id=claim_id,
                turn_id=runtime_turn_id,
                kind='professional_review',
                subject_ref=handoff.handoff_id,
                owner='staff',
                status='open',
                blocks_action='high_impact.execute',
                source_refs=[claimant_message.message_id, review_policy_ref],
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    if confirmation_request is not None:
        # Bind the confirmation to the exact values shown by this turn.  The
        # evaluation is calculated from ``updated_claim``; using the pre-turn
        # Claim here produced a fingerprint that could never match the next
        # message after the proposal had been applied.
        work_items.append(
            RuntimeWorkItemRecord(
                work_item_id=new_id('wki'),
                claim_id=claim_id,
                turn_id=runtime_turn_id,
                kind='confirmation',
                subject_ref=confirmation_request.confirmation_id,
                confirmation_request=confirmation_request,
                owner='claimant',
                status='open',
                blocks_action='confirmation_requested',
                source_refs=[claimant_message.message_id],
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    for intent in external_service_intents:
        offer = build_offer_metadata(
            claim=updated_claim,
            agent_message_id=agent_message.message_id,
            trigger_message_id=claimant_message.message_id,
            intent=intent,
            dispatcher=external_capability_dispatcher,
        )
        work_items.append(
            offer_work_item(
                claim=updated_claim,
                turn_id=runtime_turn_id,
                offer=offer,
                timestamp=timestamp,
            )
        )
    execution_plan = ExecutionPlanRecord(
        execution_plan_id=new_id('xpl'),
        turn_id=runtime_turn_id,
        claim_id=claim_id,
        expected_revision=expected_revision,
        envelope_ids=[item.envelope_id for item in envelope_records],
        approved_envelope_ids=[
            item.envelope_id for item in envelope_records if item.status in {'approved', 'executed'}
        ],
        rejected_envelope_ids=[
            item.envelope_id for item in envelope_records if item.status == 'rejected'
        ],
        status=('executed' if authority.outcome is AuthorityOutcome.AUTHORISED else 'rejected'),
        created_at=timestamp,
        finished_at=timestamp,
    )
    turn_result = TurnResultRecord(
        result_id=new_id('res'),
        turn_id=runtime_turn_id,
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        execution_plan_id=execution_plan.execution_plan_id,
        status=('succeeded' if authority.outcome is AuthorityOutcome.AUTHORISED else 'blocked'),
        resulting_claim_revision=resulting_revision,
        customer_response=effective_customer_response,
        state_change_refs=[f'claim:{claim_id}:revision:{resulting_revision}'],
        tool_result_refs=[item.result_id for item in tool_records],
        work_item_refs=[item.work_item_id for item in work_items],
        limitations=[],
        created_at=timestamp,
    )
    runtime_records = RuntimeTurnRecords(
        turn_plan=runtime_turn_plan,
        proposal=runtime_proposal,
        execution_plan=execution_plan,
        action_envelopes=envelope_records,
        tool_results=tool_records,
        result=turn_result,
        work_items=work_items,
    )
    return TurnOutcome(
        claim=updated_claim,
        agent_message_text=effective_customer_response,
        handoff=handoff,
        confirmation_request=confirmation_request,
        branch_evaluation=applied_evaluation,
        records=TurnRecords(
            customer_reason=effective_customer_reason,
            form_changes=form_changes,
            contents_item_changes=contents_item_changes,
            discrepancy_candidates=discrepancy_candidates,
            pending_evidence=pending_evidence,
            professional_review=professional_review,
            agent_message=agent_message,
            decision=decision,
            idempotency=idempotency,
            evaluation_record=evaluation_record,
            runtime_records=runtime_records,
            live_mutation_command=live_mutation_command,
            review_signals=judgment_signals,
        ),
        session=updated_session,
        offers=[item for item in work_items if item.kind == 'external'],
        rejected_parts=[*(validated.rejected if validated else []), *judgment_rejections],
    )
