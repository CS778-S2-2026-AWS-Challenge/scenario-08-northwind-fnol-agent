import re
from dataclasses import dataclass
from typing import Protocol

from backend.domain.intake import next_controlled_intake_field
from backend.domain.models import (
    AgentAction,
    AgentAuthority,
    AuthorityOutcome,
    CustomerNextStep,
    FormSource,
    FormStatus,
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


@dataclass(frozen=True, slots=True)
class AgentTurnContext:
    claim: WorkingClaim
    session_id: str
    trigger_message_id: str
    message_text: str | None
    evidence_refs: list[str]


@dataclass(frozen=True, slots=True)
class AgentProposal:
    action: AgentAction
    reason_codes: list[str]
    customer_reason: str
    customer_next_step: CustomerNextStep
    form_changes: list[ProposedFormChange]
    state_changes: list[StateChange]
    proposed_signals: list[dict[str, object]]
    required_tools: list[dict[str, object]]
    next_action_requirements: list[str]
    handoff_priority: str | None = None
    controlled_rule_authorised: bool = False


class AgentTurnProvider(Protocol):
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        raise NotImplementedError


class ControlledAgent:
    """Deterministic prototype provider that can be replaced by a model adapter."""

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        message_text = context.message_text or ''
        injury_signal = any(pattern.search(message_text) for pattern in INJURY_PATTERNS)
        danger_signal = any(pattern.search(message_text) for pattern in DANGER_PATTERNS)
        if injury_signal or danger_signal:
            return AgentProposal(
                action=AgentAction.URGENT_HANDOFF,
                reason_codes=['EXPLICIT_SAFETY_SIGNAL'],
                customer_reason='You described an injury or continuing danger.',
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
        if context.claim.claim_state.next_action not in {
            AgentAction.HANDOFF,
            AgentAction.URGENT_HANDOFF,
        } and any(pattern.search(message_text) for pattern in HUMAN_REQUEST_PATTERNS):
            return AgentProposal(
                action=AgentAction.HANDOFF,
                reason_codes=['HUMAN_SUPPORT_REQUESTED'],
                customer_reason='You asked to continue with a person.',
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
        if context.claim.claim_state.next_action in {
            AgentAction.HANDOFF,
            AgentAction.URGENT_HANDOFF,
        }:
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['HANDOFF_ALREADY_QUEUED'],
                customer_reason='Your additional information has been kept with the report.',
                customer_next_step=context.claim.customer_next_step,
                form_changes=[],
                state_changes=[],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[],
            )
        intake_field = next_controlled_intake_field(context.claim)
        if context.message_text is not None and intake_field is not None:
            return AgentProposal(
                action=AgentAction.CONFIRM,
                reason_codes=['MATERIAL_FACTS_PROPOSED'],
                customer_reason=intake_field.confirmation_prompt,
                customer_next_step=CustomerNextStep(
                    status='confirmation_required',
                    summary=intake_field.confirmation_prompt,
                    responsible_party=ResponsibleParty.CLAIMANT,
                    required_items=[intake_field.field_code],
                ),
                form_changes=[
                    ProposedFormChange(
                        field_code=intake_field.field_code,
                        value=context.message_text,
                        source=FormSource.CLAIMANT,
                        status=FormStatus.PROPOSED,
                        needed_for=NeededFor.CURRENT_ACTION,
                        confidence=1.0,
                    )
                ],
                state_changes=[StateChange(path='claim_state.next_action', to='CONFIRM')],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[f'confirm:{intake_field.field_code}'],
            )

        if context.message_text is not None:
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['CLAIMANT_CONFIRMED'],
                customer_reason='I have kept that information with your report.',
                customer_next_step=CustomerNextStep(
                    status='core_details_confirmed',
                    summary=(
                        'Your core incident details are confirmed. Review them before continuing.'
                    ),
                    responsible_party=ResponsibleParty.CLAIMANT,
                ),
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
