"""What each run can say about the metrics `sprint/sprint4.md` section 2 requires.

The record keeps the requirement and the runtime apart. Three of the five metrics judge a
model's behaviour: whether the journey finished without follow-up, whether a severity
classification survives blind rating, and whether fraud flags are precise. On this runtime the
Agent is the rule-driven `ControlledAgent`, so a rate measured here would describe the rules
rather than the Agent, and no severity or fraud judgement is produced to rate at all. Claimant
effort is measured in part: the run counts what the claimant did, while the elapsed minutes and
the question total have no served source.

Each shortfall names the document that establishes it, so the record states a boundary rather
than an opinion, and the suite fails if the quoted passage leaves that document.

The claim result is measured as what the run recorded of the claim number, expected timeline,
final state, and evidence chain. Where a journey ends before claim creation, that is the
recorded result rather than a missing measurement; the result class says how far it reached.
"""

from collections.abc import Sequence

from .record import (
    AgentTurn,
    ClaimantEffort,
    FinalState,
    MetricCoverage,
    MetricState,
    SprintMetric,
)

CONTROLLED_AGENT_AUTHORITY = (
    'docs/model-gateway.md: "The default `controlled` profile continues to use '
    '`ControlledAgent`." A rule-driven Agent produces no judgement of its own to rate, so a '
    'rate measured on this runtime would describe the rules.'
)
MODEL_PROFILE_AUTHORITY = (
    'docs/model-gateway.md: "profile is enabled only through explicit startup configuration". '
    'This runtime has no configured model transport, so no model-produced severity or fraud '
    'signal exists to rate.'
)
CLAIMANT_TIME_AUTHORITY = (
    'docs/api.md documents "median_time_to_next_action_seconds" and claimant question totals '
    'on an aggregate metrics endpoint the application does not serve, so elapsed claimant time '
    'and the question total have no source here; the counts below are what the run observed.'
)


def metric_coverage(
    *,
    turns: Sequence[AgentTurn],
    effort: ClaimantEffort,
    state: FinalState,
) -> list[MetricCoverage]:
    """State every required metric for one run, measured or not.

    Args:
        turns: Agent turns the run recorded, used to count questions put to the claimant.
        effort: Counts of what the claimant did during the run.
        state: Final Claim state, including the claim number and expected timeline.

    Returns:
        One coverage entry per metric in `SprintMetric`.
    """

    questions = sum('?' in (turn.agent_reply or '') for turn in turns)
    return [
        MetricCoverage(
            metric=SprintMetric.NO_FOLLOW_UP,
            state=MetricState.NOT_MEASURED,
            limitation=CONTROLLED_AGENT_AUTHORITY,
        ),
        MetricCoverage(
            metric=SprintMetric.SEVERITY_BLIND_RATING,
            state=MetricState.NOT_MEASURED,
            limitation=MODEL_PROFILE_AUTHORITY,
        ),
        MetricCoverage(
            metric=SprintMetric.FRAUD_PRECISION,
            state=MetricState.NOT_MEASURED,
            limitation=MODEL_PROFILE_AUTHORITY,
        ),
        MetricCoverage(
            metric=SprintMetric.CLAIMANT_EFFORT,
            state=MetricState.PARTLY_MEASURED,
            observed=(
                f'{effort.messages} claimant messages, {questions} of which the Agent answered '
                f'with a question; {effort.confirmations} confirmations, {effort.uploads} '
                f'uploads, {effort.consents} consents'
            ),
            limitation=CLAIMANT_TIME_AUTHORITY,
        ),
        MetricCoverage(
            metric=SprintMetric.CLAIM_RESULT,
            state=MetricState.MEASURED,
            observed=_claim_result(state),
        ),
    ]


def _claim_result(state: FinalState) -> str:
    """Say what the run recorded of the claim number, timeline, state, and evidence chain."""

    if state.claim_number is None:
        created = 'no claim number: this journey ends before claim creation'
    else:
        expected = state.expected_by.isoformat() if state.expected_by is not None else 'none'
        created = f'claim {state.claim_number}, expected by {expected}'
    return (
        f'{created}; final state {state.workflow_state or "unrecorded"} with next step '
        f'{state.customer_next_step or "none"} owned by '
        f'{state.next_step_responsible_party or "nobody"}; '
        f'{len(state.evidence_ids)} evidence records'
    )
