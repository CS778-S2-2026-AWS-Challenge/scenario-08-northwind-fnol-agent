import re
from dataclasses import dataclass
from typing import Protocol

from backend.domain.intake import (
    infer_controlled_incident_type,
    next_controlled_intake_field,
    next_controlled_intake_step,
)
from backend.domain.models import (
    AgentAction,
    AgentAuthority,
    AgentProposalSource,
    AuthorityOutcome,
    CustomerNextStep,
    FormSource,
    FormStatus,
    ModelDecisionProvenance,
    NeededFor,
    ProposedFormChange,
    ResponsibleParty,
    StateChange,
    WorkingClaim,
)

HIGH_IMPACT_ACTIONS = frozenset(
    {
        AgentAction.PROCEED,
        AgentAction.HANDOFF,
        AgentAction.URGENT_HANDOFF,
        AgentAction.CREATE_CLAIM,
    }
)
CONTROLLED_HANDOFF_REASONS = frozenset({'EXPLICIT_SAFETY_SIGNAL', 'HUMAN_SUPPORT_REQUESTED'})
SUPPORTED_AGENT_STATE_PATHS = frozenset({'claim_state.next_action'})

PERSON_SUBJECT = (
    r'(?:i|we|he|she|they|someone|somebody|'
    r'(?:a|the|my|our)?\s*(?:passenger|driver|person|pedestrian|cyclist|child|adult))'
)
INJURY_PATTERNS = (
    re.compile(
        rf'\b{PERSON_SUBJECT}\s+'
        r'(?:am|are|is|was|were|got|has\s+been|have\s+been)\s+'
        r'(?:(?:seriously|badly)\s+)?(?:injured|hurt|bleeding|trapped|unconscious)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\b{PERSON_SUBJECT}\s+(?:has|have|suffered)\s+'
        r'(?:(?:a|an)\s+)?(?:(?:serious|minor)\s+)?injur(?:y|ies)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\bthere\s+(?:is|are|was|were)\s+'
        r'(?:(?:a|an)\s+)?(?:injured|hurt|bleeding|trapped|unconscious)\s+'
        r'(?:person|people|passenger|driver|pedestrian|cyclist|child|adult)\b',
        re.IGNORECASE,
    ),
)
DANGER_PATTERNS = (
    re.compile(r'\b(?:still|continuing|immediate)\s+(?:danger|dangerous|unsafe)\b', re.IGNORECASE),
    re.compile(r'\b(?:fire|smoke)\s+(?:is\s+)?(?:spreading|continuing|active)\b', re.IGNORECASE),
)
INJURY_NEGATION_PATTERNS = (
    re.compile(
        r'\b(?:no\s+one|nobody|none)\s+'
        r'(?:(?:is|are|was|were|got|has\s+been|have\s+been)\s+)?'
        r'(?:(?:seriously|badly)\s+)?(?:injured|hurt|bleeding|trapped|unconscious)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\b{PERSON_SUBJECT}\s+'
        r'(?:am|are|is|was|were|has\s+been|have\s+been)\s+not\s+'
        r'(?:(?:seriously|badly)\s+)?(?:injured|hurt|bleeding|trapped|unconscious)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\bthere\s+(?:is|are|was|were)\s+no\s+'
        r'(?:injured|hurt|bleeding|trapped|unconscious)\s+'
        r'(?:person|people|passenger|driver|pedestrian|cyclist|child|adult)\b',
        re.IGNORECASE,
    ),
)
DANGER_NEGATION_PATTERNS = (
    re.compile(
        r'\b(?:there\s+(?:is|are|was|were)\s+)?no\s+'
        r'(?:(?:still|continuing|immediate|ongoing)\s+)?(?:danger|dangerous|unsafe)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:is|are|was|were)\s+not\s+'
        r'(?:(?:still|currently)\s+)?(?:in\s+)?(?:danger|dangerous|unsafe)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\bno\s+longer\s+(?:in\s+)?(?:danger|dangerous|unsafe)\b',
        re.IGNORECASE,
    ),
)
HUMAN_REQUEST_PATTERNS = (
    re.compile(
        r'\b(?:speak|talk)\s+(?:to|with)\s+(?:a\s+)?(?:person|human|representative)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:want|need|request)\s+(?:a\s+)?(?:person|human|representative)\b', re.IGNORECASE
    ),
    re.compile(r'\bhuman\s+(?:help|support)\b', re.IGNORECASE),
)
PENDING_POLICE_REPORT_PATTERNS = (
    re.compile(
        r'\bpolice\b[^.!?]{0,100}\b(?:report|reference)\b[^.!?]{0,100}'
        r'\b(?:later|next\s+week|pending|not\s+(?:ready|available|issued|generated)|'
        r'has\s+not\s+been\s+(?:issued|generated)|hasn\x27t\s+been\s+(?:issued|generated))\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:later|next\s+week|pending|not\s+(?:ready|available|issued|generated)|'
        r'has\s+not\s+been\s+(?:issued|generated)|hasn\x27t\s+been\s+(?:issued|generated))\b'
        r'[^.!?]{0,100}\bpolice\b[^.!?]{0,60}\b(?:report|reference)\b',
        re.IGNORECASE,
    ),
)
REAR_END_COLLISION_PATTERNS = (
    re.compile(
        r'\b(?:hit|struck)\b[^.!?]*\b(?:back|rear)\b[^.!?]*\b(?:car|vehicle|bumper)\b',
        re.IGNORECASE,
    ),
    re.compile(r'\brear[- ]?ended\b', re.IGNORECASE),
)
SAFETY_CLEAR_PATTERNS = (
    re.compile(r'\b(?:scene|area|road)\s+(?:is|was)\s+safe\b', re.IGNORECASE),
    re.compile(
        r'\b(?:car|cars|vehicle|vehicles|we|i)\s+(?:is|are|was|were|have\s+been|has\s+been)?\s*'
        r'(?:moved|parked|pulled)\s+(?:off|out\s+of|away\s+from)\s+(?:the\s+)?(?:road|traffic)\b',
        re.IGNORECASE,
    ),
)
LOCATION_PATTERN = re.compile(
    r'\b(?:at|on|in)\s+([A-Z][A-Za-z0-9 -]+?)(?=[,.]|\s+(?:when|while|and)\b|$)'
)
LOSS_PATTERN = re.compile(
    r'([^.!?]*(?:damag(?:e|ed)|scratch(?:ed)?|dent(?:ed)?|broken|lost)[^.!?]*)',
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AgentTurnContext:
    claim: WorkingClaim
    session_id: str
    trigger_message_id: str
    message_text: str | None
    evidence_refs: list[str]
    professional_review_required: bool = False


@dataclass(frozen=True, slots=True)
class AgentProposal:
    action: AgentAction
    reason_codes: list[str]
    customer_reason: str
    customer_response: str
    customer_next_step: CustomerNextStep
    form_changes: list[ProposedFormChange]
    state_changes: list[StateChange]
    proposed_signals: list[dict[str, object]]
    required_tools: list[dict[str, object]]
    next_action_requirements: list[str]
    handoff_priority: str | None = None
    controlled_rule_authorised: bool = False
    proposal_source: AgentProposalSource = AgentProposalSource.CONTROLLED_AGENT
    model_provenance: ModelDecisionProvenance | None = None


def _contains_unnegated_signal(
    message_text: str,
    signal_patterns: tuple[re.Pattern[str], ...],
    negation_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    remaining_text = message_text
    for pattern in negation_patterns:
        remaining_text = pattern.sub('', remaining_text)
    return any(pattern.search(remaining_text) for pattern in signal_patterns)


def _initial_form_changes(message_text: str, incident_type: str | None) -> list[ProposedFormChange]:
    changes = [
        ProposedFormChange(
            field_code='incident.description',
            value=message_text,
            source=FormSource.CLAIMANT,
            status=FormStatus.PROPOSED,
            needed_for=NeededFor.CURRENT_ACTION,
            confidence=1.0,
        )
    ]
    inferred_incident_type = (
        infer_controlled_incident_type(message_text) if incident_type is None else None
    )
    if inferred_incident_type is not None:
        changes.append(
            ProposedFormChange(
                field_code='incident.type',
                value=inferred_incident_type,
                source=FormSource.INFERENCE,
                status=FormStatus.PROPOSED,
                needed_for=NeededFor.CURRENT_ACTION,
                confidence=0.95,
            )
        )
    location = LOCATION_PATTERN.search(message_text)
    if location is not None:
        changes.append(
            ProposedFormChange(
                field_code='incident.location',
                value=location.group(1).strip(),
                source=FormSource.INFERENCE,
                status=FormStatus.PROPOSED,
                needed_for=NeededFor.CURRENT_ACTION,
                confidence=0.85,
            )
        )
    loss = LOSS_PATTERN.search(message_text)
    if loss is not None:
        changes.append(
            ProposedFormChange(
                field_code='loss.description',
                value=loss.group(1).strip(),
                source=FormSource.INFERENCE,
                status=FormStatus.PROPOSED,
                needed_for=NeededFor.CURRENT_ACTION,
                confidence=0.85,
            )
        )
    return changes


def _is_guided_rear_end_claim(claim: WorkingClaim, message_text: str) -> bool:
    description = claim.form.get('incident.description')
    candidate = str(description.value) if description is not None else message_text
    inferred_type = claim.form.get('incident.type')
    if description is None:
        is_motor = (
            claim.incident_type is None and infer_controlled_incident_type(candidate) == 'motor'
        )
    else:
        is_motor = (
            inferred_type is not None
            and inferred_type.value == 'motor'
            and inferred_type.source is FormSource.INFERENCE
        )
    return is_motor and any(pattern.search(candidate) for pattern in REAR_END_COLLISION_PATTERNS)


def _guided_initial_form_changes(message_text: str) -> list[ProposedFormChange]:
    changes = _initial_form_changes(message_text, None)
    return [
        change.model_copy(update={'status': FormStatus.CONFIRMED})
        if change.field_code == 'incident.description'
        else change
        for change in changes
    ]


def _safety_is_explicitly_clear(message_text: str) -> bool:
    injury_clear = any(pattern.search(message_text) for pattern in INJURY_NEGATION_PATTERNS)
    danger_clear = any(pattern.search(message_text) for pattern in DANGER_NEGATION_PATTERNS)
    scene_clear = any(pattern.search(message_text) for pattern in SAFETY_CLEAR_PATTERNS)
    return injury_clear and (danger_clear or scene_clear)


def _guided_proposal(context: AgentTurnContext, message_text: str) -> AgentProposal | None:
    claim = context.claim
    if not _is_guided_rear_end_claim(claim, message_text):
        return None

    if 'incident.description' not in claim.form:
        changes = _guided_initial_form_changes(message_text)
        return AgentProposal(
            action=AgentAction.ASK,
            reason_codes=['SAFETY_STATUS_REQUIRED'],
            customer_reason='Your immediate safety needs to be clear before the report continues.',
            customer_response=(
                'I can help you report this. First, is anyone injured, in immediate danger, '
                'or blocking traffic?'
            ),
            customer_next_step=CustomerNextStep(
                status='provide_safety_status',
                summary='Tell us whether anyone is injured or still in danger.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=['incident.injury_or_danger'],
            ),
            form_changes=changes,
            state_changes=[StateChange(path='claim_state.next_action', to='ASK')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['provide:incident.injury_or_danger'],
        )

    if 'incident.injury_or_danger' not in claim.form:
        if not _safety_is_explicitly_clear(message_text):
            return AgentProposal(
                action=AgentAction.CLARIFY,
                reason_codes=['SAFETY_STATUS_UNCLEAR'],
                customer_reason='The current safety situation is not clear yet.',
                customer_response=(
                    'Before we continue, please tell me whether anyone is injured, whether there '
                    'is any immediate danger, and whether the vehicles are out of traffic.'
                ),
                customer_next_step=CustomerNextStep(
                    status='clarify_safety_status',
                    summary='Clarify whether anyone is injured or still in danger.',
                    responsible_party=ResponsibleParty.CLAIMANT,
                    required_items=['incident.injury_or_danger'],
                ),
                form_changes=[],
                state_changes=[StateChange(path='claim_state.next_action', to='CLARIFY')],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=['clarify:incident.injury_or_danger'],
            )
        return AgentProposal(
            action=AgentAction.ASK,
            reason_codes=['SAFETY_STATUS_RECORDED'],
            customer_reason='No injury or immediate danger was reported.',
            customer_response='Thanks. About when did this happen? An approximate time is fine.',
            customer_next_step=CustomerNextStep(
                status='provide_incident_time',
                summary='Tell us approximately when the incident happened.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=['incident.occurred_at'],
            ),
            form_changes=[
                ProposedFormChange(
                    field_code='incident.injury_or_danger',
                    value=False,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.CONFIRMED,
                    needed_for=NeededFor.CURRENT_ACTION,
                    confidence=1.0,
                )
            ],
            state_changes=[StateChange(path='claim_state.next_action', to='ASK')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['provide:incident.occurred_at'],
        )

    if 'incident.occurred_at' not in claim.form:
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['POLICY_WORDING_REVIEW_NEEDED'],
            customer_reason=(
                'One point in the applicable collision wording needs a specialist check.'
            ),
            customer_response=(
                'Thanks. I have saved those details and will check the policy linked to your '
                'report. Is a police report or reference available now, or is it still pending?'
            ),
            customer_next_step=CustomerNextStep(
                status='provide_police_report_status',
                summary='Tell us whether the police report or reference is available yet.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=['authorities.police_report_reference'],
            ),
            form_changes=[
                ProposedFormChange(
                    field_code='incident.occurred_at',
                    value=message_text,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.CONFIRMED,
                    needed_for=NeededFor.CURRENT_ACTION,
                    confidence=1.0,
                )
            ],
            state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
            proposed_signals=[],
            required_tools=[
                {
                    'tool': 'policy_history',
                    'operation': 'search_policy',
                    'policy_reference': 'synthetic-policy-ambiguous',
                    'question': (
                        'Can this rear-end collision report proceed under the applicable '
                        'collision-damage wording?'
                    ),
                }
            ],
            next_action_requirements=['provide:authorities.police_report_reference'],
        )
    return AgentProposal(
        action=AgentAction.UPDATE,
        reason_codes=['ADDITIONAL_CONTEXT_RECORDED'],
        customer_reason='Your additional information remains part of the same report.',
        customer_response=(
            'I have added that information to the same report. The policy review can continue, '
            'and you do not need to start again.'
        ),
        customer_next_step=claim.customer_next_step,
        form_changes=[],
        state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
        proposed_signals=[],
        required_tools=[],
        next_action_requirements=[],
    )


def _confirmation_response(changes: list[ProposedFormChange]) -> str:
    labels = {
        'incident.description': 'what happened',
        'incident.type': 'the incident type',
        'incident.location': 'where it happened',
        'loss.description': 'what was damaged or lost',
    }
    understood = ', '.join(labels[change.field_code] for change in changes)
    return (
        f'I have structured {understood} from your description. '
        'Please check the highlighted facts and correct anything that is not right.'
    )


class AgentTurnProvider(Protocol):
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        raise NotImplementedError


def deterministic_interrupt_proposal(context: AgentTurnContext) -> AgentProposal | None:
    message_text = context.message_text or ''
    active_handoff = context.claim.claim_state.next_action in {
        AgentAction.HANDOFF,
        AgentAction.URGENT_HANDOFF,
    }
    injury_signal = _contains_unnegated_signal(
        message_text, INJURY_PATTERNS, INJURY_NEGATION_PATTERNS
    )
    danger_signal = _contains_unnegated_signal(
        message_text, DANGER_PATTERNS, DANGER_NEGATION_PATTERNS
    )
    if injury_signal or danger_signal:
        return AgentProposal(
            action=AgentAction.URGENT_HANDOFF,
            reason_codes=['EXPLICIT_SAFETY_SIGNAL'],
            customer_reason='You described an injury or continuing danger.',
            customer_response=(
                'Your safety comes first. Move to a safer place if you can do so safely, '
                'and contact local emergency services yourself if immediate help is needed. '
                'I have kept the details you provided and requested urgent Northwind support.'
            ),
            customer_next_step=CustomerNextStep(
                status='urgent_support_queued',
                summary=(
                    'Move to a safer place if you can do so safely. Contact local emergency '
                    'services yourself if immediate help is needed. Northwind urgent support '
                    'has been requested with the details already provided.'
                ),
                responsible_party=ResponsibleParty.NORTHWIND,
            ),
            form_changes=[],
            state_changes=[StateChange(path='claim_state.next_action', to='URGENT_HANDOFF')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            handoff_priority='urgent',
            controlled_rule_authorised=True,
        )
    if not active_handoff and any(
        pattern.search(message_text) for pattern in HUMAN_REQUEST_PATTERNS
    ):
        return AgentProposal(
            action=AgentAction.HANDOFF,
            reason_codes=['HUMAN_SUPPORT_REQUESTED'],
            customer_reason='You asked to continue with a person.',
            customer_response=(
                'I will transfer this report to a Northwind staff member. The facts, evidence '
                'status, and messages already recorded will go with it, so you should not need '
                'to start again.'
            ),
            customer_next_step=CustomerNextStep(
                status='human_support_queued',
                summary=(
                    'A Northwind support request has been queued with the details already '
                    'provided. You do not need to restart your report.'
                ),
                responsible_party=ResponsibleParty.NORTHWIND,
            ),
            form_changes=[],
            state_changes=[StateChange(path='claim_state.next_action', to='HANDOFF')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            handoff_priority='standard',
            controlled_rule_authorised=True,
        )
    if any(pattern.search(message_text) for pattern in PENDING_POLICE_REPORT_PATTERNS):
        if context.professional_review_required and not active_handoff:
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['EVIDENCE_PENDING_GENERATION', 'PROFESSIONAL_REVIEW_REQUIRED'],
                customer_reason=(
                    'The police report is not available yet, but it is not needed for the current '
                    'policy review.'
                ),
                customer_response=(
                    'That is okay. I have recorded that the police report is expected later and '
                    'sent the relevant facts and policy wording to a claims specialist. They can '
                    'review it now, and you can add the report when it becomes available.'
                ),
                customer_next_step=CustomerNextStep(
                    status='professional_review_queued',
                    summary=(
                        'A claims specialist is checking one policy point. Add the police report '
                        'when it becomes available.'
                    ),
                    responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
                ),
                form_changes=[],
                state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
                proposed_signals=[],
                required_tools=[
                    {
                        'tool': 'evidence_registry',
                        'operation': 'record_pending_generation',
                        'kind': 'police_report',
                    },
                    {
                        'tool': 'professional_review',
                        'operation': 'create_policy_review',
                    },
                ],
                next_action_requirements=[],
                controlled_rule_authorised=True,
            )
        pending_field = context.claim.form.get('authorities.police_report_reference')
        already_pending = (
            pending_field is not None and pending_field.status is FormStatus.PENDING_GENERATION
        )
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['EVIDENCE_PENDING_GENERATION'],
            customer_reason='The police report has not been issued and is needed only later.',
            customer_response=(
                'That is okay. I have recorded that the police report is expected later. '
                'It will not block the parts of your report that can safely continue now.'
            ),
            customer_next_step=context.claim.customer_next_step,
            form_changes=[],
            state_changes=[],
            proposed_signals=[],
            required_tools=(
                []
                if already_pending
                else [
                    {
                        'tool': 'evidence_registry',
                        'operation': 'record_pending_generation',
                        'kind': 'police_report',
                    }
                ]
            ),
            next_action_requirements=[],
            controlled_rule_authorised=True,
        )
    if active_handoff:
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['HANDOFF_ALREADY_QUEUED'],
            customer_reason='Your additional information has been kept with the report.',
            customer_response=(
                'I have added that information to the report already waiting for Northwind support.'
            ),
            customer_next_step=context.claim.customer_next_step,
            form_changes=[],
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
        )
    return None


class InvariantGuardedAgent:
    """Applies server-owned turn interrupts before the configured provider."""

    def __init__(self, provider: AgentTurnProvider) -> None:
        self._provider = provider

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        interrupt = deterministic_interrupt_proposal(context)
        return interrupt if interrupt is not None else self._provider.propose_turn(context)


class ControlledAgent:
    """Deterministic prototype provider that can be replaced by a model adapter."""

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        message_text = context.message_text or ''
        interrupt = deterministic_interrupt_proposal(context)
        if interrupt is not None:
            return interrupt
        if context.message_text is not None:
            guided = _guided_proposal(context, message_text)
            if guided is not None:
                return guided
        intake_field = next_controlled_intake_field(context.claim)
        if context.message_text is not None and intake_field is not None:
            changes = (
                _initial_form_changes(message_text, context.claim.incident_type)
                if not context.claim.form and intake_field.field_code == 'incident.description'
                else [
                    ProposedFormChange(
                        field_code=intake_field.field_code,
                        value=context.message_text,
                        source=FormSource.CLAIMANT,
                        status=FormStatus.PROPOSED,
                        needed_for=NeededFor.CURRENT_ACTION,
                        confidence=1.0,
                    )
                ]
            )
            return AgentProposal(
                action=AgentAction.CONFIRM,
                reason_codes=['MATERIAL_FACTS_PROPOSED'],
                customer_reason=intake_field.confirmation_prompt,
                customer_response=_confirmation_response(changes),
                customer_next_step=CustomerNextStep(
                    status='confirmation_required',
                    summary=intake_field.confirmation_prompt,
                    responsible_party=ResponsibleParty.CLAIMANT,
                    required_items=[change.field_code for change in changes],
                ),
                form_changes=changes,
                state_changes=[StateChange(path='claim_state.next_action', to='CONFIRM')],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[f'confirm:{change.field_code}' for change in changes],
            )

        if context.message_text is not None and any(
            pattern.search(message_text) for pattern in PENDING_POLICE_REPORT_PATTERNS
        ):
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['EVIDENCE_PENDING_GENERATION'],
                customer_reason='The police report does not exist yet and is needed only later.',
                customer_response=(
                    'That is okay. I have recorded that the police report is expected later. '
                    'It will not block the parts of your report that can safely continue now.'
                ),
                customer_next_step=CustomerNextStep(
                    status='continue_current_report',
                    summary='Continue now; add the police report when it becomes available.',
                    responsible_party=ResponsibleParty.CLAIMANT,
                ),
                form_changes=[],
                state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
                proposed_signals=[],
                required_tools=[
                    {
                        'tool': 'evidence_registry',
                        'operation': 'record_pending_generation',
                        'kind': 'police_report',
                    }
                ],
                next_action_requirements=[],
            )

        if context.message_text is not None:
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['CLAIMANT_CONFIRMED'],
                customer_reason='I have kept that information with your report.',
                customer_response=(
                    'I have added that information to your report. You can continue with any '
                    'available evidence or request human support.'
                ),
                customer_next_step=next_controlled_intake_step(context.claim),
                form_changes=[],
                state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[],
            )

        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['EVIDENCE_INCOMPLETE'],
            customer_reason='The evidence reference was recorded for later processing.',
            customer_response=(
                'I have linked that evidence to your report and kept its current status.'
            ),
            customer_next_step=context.claim.customer_next_step,
            form_changes=[],
            state_changes=[StateChange(path='claim_state.next_action', to='UPDATE')],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
        )


def validate_proposal(proposal: AgentProposal) -> AgentAuthority:
    if (
        proposal.action in {AgentAction.HANDOFF, AgentAction.URGENT_HANDOFF}
        and proposal.controlled_rule_authorised
        and set(proposal.reason_codes).issubset(CONTROLLED_HANDOFF_REASONS)
        and proposal.reason_codes
    ):
        return AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        )
    if proposal.action in HIGH_IMPACT_ACTIONS:
        return AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.REVIEW_REQUIRED,
        )
    for state_change in proposal.state_changes:
        if state_change.path not in SUPPORTED_AGENT_STATE_PATHS:
            return AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.BLOCKED,
            )
        raw_action = (
            state_change.to.value if isinstance(state_change.to, AgentAction) else state_change.to
        )
        try:
            proposed_action = AgentAction(str(raw_action))
        except ValueError:
            return AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.BLOCKED,
            )
        if proposed_action is not proposal.action:
            return AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.BLOCKED,
            )
    return AgentAuthority(
        proposed_by='agent',
        validated_by='deterministic_rule_engine',
        outcome=AuthorityOutcome.AUTHORISED,
    )


def authorised_state_changes(
    proposal: AgentProposal,
    authority: AgentAuthority,
) -> list[StateChange]:
    if authority.outcome is not AuthorityOutcome.AUTHORISED:
        return []
    return proposal.state_changes
