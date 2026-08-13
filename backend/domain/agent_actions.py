from dataclasses import dataclass

from backend.domain.models import AgentAction, AuthorityOutcome


@dataclass(frozen=True, slots=True)
class AgentActionDefinition:
    """Stable product semantics shared by rule-based and model-backed agents."""

    action: AgentAction
    purpose: str
    preconditions: tuple[str, ...]
    allowed_state_paths: tuple[str, ...]
    tool_policy: str
    authority: AuthorityOutcome
    response_requirement: str
    prohibited_outcomes: tuple[str, ...]


AGENT_ACTION_DEFINITIONS = {
    AgentAction.ASK: AgentActionDefinition(
        action=AgentAction.ASK,
        purpose='Request information required for the next safe action.',
        preconditions=('A required fact or evidence state is unresolved.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Tools are optional and must not replace a claimant answer.',
        authority=AuthorityOutcome.AUTHORISED,
        response_requirement='Acknowledge known context and ask one focused question.',
        prohibited_outcomes=('Do not ask for an already confirmed fact.',),
    ),
    AgentAction.CLARIFY: AgentActionDefinition(
        action=AgentAction.CLARIFY,
        purpose='Resolve ambiguity, conflict, omission, or evidence quality.',
        preconditions=('A material ambiguity or conflict is recorded.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Retrieval may support the question but cannot settle a high-impact decision.',
        authority=AuthorityOutcome.AUTHORISED,
        response_requirement=(
            'Name the uncertainty in claimant-safe language and request correction.'
        ),
        prohibited_outcomes=('Do not turn uncertainty into a coverage or fraud conclusion.',),
    ),
    AgentAction.CONFIRM: AgentActionDefinition(
        action=AgentAction.CONFIRM,
        purpose='Ask the claimant to confirm or correct proposed material facts.',
        preconditions=('At least one material form field is proposed.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='No side effect may depend on an unconfirmed proposed fact.',
        authority=AuthorityOutcome.AUTHORISED,
        response_requirement='Summarise the proposed facts without changing their meaning.',
        prohibited_outcomes=('Do not silently promote a proposed fact to confirmed.',),
    ),
    AgentAction.PROCEED: AgentActionDefinition(
        action=AgentAction.PROCEED,
        purpose='Advance work whose current safety conditions are satisfied.',
        preconditions=('Current-action requirements are satisfied.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Only invoke tools declared by the validated decision.',
        authority=AuthorityOutcome.REVIEW_REQUIRED,
        response_requirement='Explain what can proceed and what remains pending.',
        prohibited_outcomes=('Do not block unrelated work on evidence needed only later.',),
    ),
    AgentAction.UPDATE: AgentActionDefinition(
        action=AgentAction.UPDATE,
        purpose='Record or explain state, responsibility, pending work, and timing.',
        preconditions=('A persisted state or responsibility can be reported safely.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Updates may record bounded evidence state without external side effects.',
        authority=AuthorityOutcome.AUTHORISED,
        response_requirement=(
            'Respond to the latest message and distinguish status from next action.'
        ),
        prohibited_outcomes=(
            'Do not repeat a generic status when a more useful action is available.',
        ),
    ),
    AgentAction.HANDOFF: AgentActionDefinition(
        action=AgentAction.HANDOFF,
        purpose='Transfer preserved context for support or professional judgement.',
        preconditions=('A controlled handoff reason and receiving action are present.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Persist the handoff packet before claiming that support is queued.',
        authority=AuthorityOutcome.REVIEW_REQUIRED,
        response_requirement='Confirm transfer, preserved context, responsibility, and next step.',
        prohibited_outcomes=('Do not require the claimant to restart or expose internal signals.',),
    ),
    AgentAction.URGENT_HANDOFF: AgentActionDefinition(
        action=AgentAction.URGENT_HANDOFF,
        purpose='Interrupt ordinary intake for an explicit safety signal.',
        preconditions=('A controlled injury or continuing-danger signal is explicit.',),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Persist urgent support; never claim emergency services were contacted.',
        authority=AuthorityOutcome.REVIEW_REQUIRED,
        response_requirement='Give bounded safety guidance and state who must act next.',
        prohibited_outcomes=('Do not continue ordinary intake before the safety response.',),
    ),
    AgentAction.CREATE_CLAIM: AgentActionDefinition(
        action=AgentAction.CREATE_CLAIM,
        purpose='Create and route a claim through the configured claims adapter.',
        preconditions=(
            'Required facts are confirmed and a deterministic rule authorises creation.',
        ),
        allowed_state_paths=('claim_state.next_action',),
        tool_policy='Invoke claim creation once with idempotency and persist the adapter result.',
        authority=AuthorityOutcome.REVIEW_REQUIRED,
        response_requirement='Return creation state, claim number, route, next step, and timing.',
        prohibited_outcomes=('Do not create from unconfirmed facts or imply claim approval.',),
    ),
}


def action_definition(action: AgentAction) -> AgentActionDefinition:
    return AGENT_ACTION_DEFINITIONS[action]
