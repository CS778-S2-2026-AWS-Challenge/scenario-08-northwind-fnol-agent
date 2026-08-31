import pytest

from backend.domain.agent_actions import AGENT_ACTION_DEFINITIONS, action_definition
from backend.domain.models import (
    AgentAction,
    AuthorityOutcome,
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    StateChange,
    WorkingClaim,
)
from backend.services.agent import (
    AgentProposal,
    AgentTurnContext,
    InvariantGuardedAgent,
    authorised_state_changes,
    validate_proposal,
)


def make_claim() -> WorkingClaim:
    from datetime import UTC, datetime

    timestamp = datetime.now(UTC)
    return WorkingClaim(
        claim_id='clm_agent',
        customer_id='cus_agent',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_action_registry_defines_every_action_and_separates_tools_from_semantics() -> None:
    assert set(AGENT_ACTION_DEFINITIONS) == set(AgentAction)
    for action in AgentAction:
        definition = action_definition(action)
        assert definition.action is action
        assert definition.purpose
        assert definition.preconditions
        assert definition.allowed_state_paths == ('claim_state.next_action',)
        assert definition.tool_policy
        assert definition.response_requirement
        assert definition.prohibited_outcomes

    assert action_definition(AgentAction.ASK).authority is AuthorityOutcome.AUTHORISED
    assert action_definition(AgentAction.CREATE_CLAIM).authority is AuthorityOutcome.REVIEW_REQUIRED


def proposal(action: AgentAction, state_change: StateChange) -> AgentProposal:
    claim = make_claim()
    return AgentProposal(
        action=action,
        reason_codes=['NEXT_ACTION_READY'],
        customer_reason='A controlled test proposal.',
        customer_response='A controlled claimant response.',
        customer_next_step=claim.customer_next_step,
        form_changes=[],
        state_changes=[state_change],
        proposed_signals=[],
        required_tools=[],
        next_action_requirements=[],
    )


@pytest.mark.parametrize(
    'action',
    [
        AgentAction.PROCEED,
        AgentAction.HANDOFF,
        AgentAction.URGENT_HANDOFF,
        AgentAction.CREATE_CLAIM,
    ],
)
def test_high_impact_agent_actions_require_review_and_do_not_execute(
    action: AgentAction,
) -> None:
    candidate = proposal(action, StateChange(path='claim_state.next_action', to=action.value))

    authority = validate_proposal(candidate)

    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(candidate, authority) == []


def test_validator_blocks_unsupported_or_inconsistent_state_changes() -> None:
    unsupported = proposal(
        AgentAction.UPDATE,
        StateChange(path='claim_state.coverage', to='clear'),
    )
    inconsistent = proposal(
        AgentAction.UPDATE,
        StateChange(path='claim_state.next_action', to='CREATE_CLAIM'),
    )

    assert validate_proposal(unsupported).outcome is AuthorityOutcome.BLOCKED
    assert validate_proposal(inconsistent).outcome is AuthorityOutcome.BLOCKED


def test_validator_blocks_an_unknown_next_action_value() -> None:
    candidate = proposal(
        AgentAction.UPDATE,
        StateChange(path='claim_state.next_action', to='INVENTED_ACTION'),
    )

    assert validate_proposal(candidate).outcome is AuthorityOutcome.BLOCKED


def test_handoff_reason_code_alone_cannot_bypass_high_impact_review() -> None:
    candidate = proposal(
        AgentAction.HANDOFF,
        StateChange(path='claim_state.next_action', to='HANDOFF'),
    )
    candidate.reason_codes[:] = ['HUMAN_SUPPORT_REQUESTED']

    assert validate_proposal(candidate).outcome is AuthorityOutcome.REVIEW_REQUIRED


def test_invariant_guard_short_circuits_and_otherwise_delegates() -> None:
    class RecordingAgent:
        call_count = 0

        def propose_turn(self, _context: AgentTurnContext) -> AgentProposal:
            self.call_count += 1
            return proposal(
                AgentAction.UPDATE,
                StateChange(path='claim_state.next_action', to='UPDATE'),
            )

    provider = RecordingAgent()
    guarded = InvariantGuardedAgent(provider)
    claim = make_claim()

    interrupt = guarded.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses_agent',
            trigger_message_id='msg_interrupt',
            message_text='I need a human.',
            evidence_refs=[],
        )
    )
    delegated = guarded.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses_agent',
            trigger_message_id='msg_delegated',
            message_text='A support person emailed me yesterday.',
            evidence_refs=[],
        )
    )

    assert interrupt.action is AgentAction.HANDOFF
    assert interrupt.controlled_rule_authorised is True
    assert delegated.action is AgentAction.UPDATE
    assert provider.call_count == 1
