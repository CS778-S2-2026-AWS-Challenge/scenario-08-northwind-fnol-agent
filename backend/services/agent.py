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
SUPPORTED_AGENT_STATE_PATHS = frozenset({'claim_state.next_action'})


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


class AgentTurnProvider(Protocol):
    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        raise NotImplementedError


class ControlledAgent:
    """Deterministic prototype provider that can be replaced by a model adapter."""

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
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
