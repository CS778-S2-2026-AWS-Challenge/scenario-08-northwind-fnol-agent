"""Issue #148, the `bdfa123` third: ambiguity, conflict, and visibility fixtures.

@Ysoseri1224 checks the Agent authority boundary and @LLL263 checks staff review
actions and results. This runs the four professional-review fixtures and checks
what they demonstrate about authority and about the claimant/staff split.

The Agent's authority boundary is visible in what these scenarios *do not*
contain: no coverage decision, no fraud conclusion, and no claim creation, in
exactly the situations where a system that overstepped would produce one.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.domain.models import AgentAction, Coverage, FraudSignal, WorkflowState
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import ScenarioFixture, load_scenarios, seed_scenario

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
REVIEW_DIRECTORY = Path(__file__).resolve().parents[2] / 'fixtures' / 'professional_review'


def review_scenarios() -> list[ScenarioFixture]:
    return load_scenarios(REVIEW_DIRECTORY)


@pytest.fixture(params=[scenario.scenario_id for scenario in review_scenarios()])
def scenario(request: pytest.FixtureRequest) -> ScenarioFixture:
    return next(item for item in review_scenarios() if item.scenario_id == request.param)


def seeded(scenario: ScenarioFixture) -> tuple[FixtureRepository, TestClient]:
    repository = FixtureRepository()
    seed_scenario(repository, scenario)
    return repository, TestClient(create_app(Settings(), repository))


def test_the_agent_escalates_instead_of_deciding(scenario: ScenarioFixture) -> None:
    """Issue #148: no high-impact decision outside the Agent's authority.

    Every one of these scenarios is a situation a person must resolve. The
    Agent's next action is to transfer, and the high-impact dimensions stay
    unresolved rather than being filled in.
    """
    claim_state = scenario.claim.claim_state

    assert claim_state.next_action is AgentAction.HANDOFF
    assert claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW

    # A fraud conclusion is never reached automatically, in any scenario.
    assert claim_state.fraud_signal is FraudSignal.NONE

    # Coverage is either untouched or explicitly marked as needing a person.
    assert claim_state.coverage in {
        Coverage.NOT_ASSESSED,
        Coverage.AMBIGUOUS,
        Coverage.REVIEW_REQUIRED,
    }
    assert claim_state.coverage is not Coverage.CLEAR


def test_internal_review_signals_never_reach_the_claimant(scenario: ScenarioFixture) -> None:
    """Issue #148: claimants cannot see internal signals."""
    repository, client = seeded(scenario)
    claim_id = scenario.claim.claim_id
    session_id = scenario.claim.active_session_id
    assert session_id is not None

    with client as active:
        messages = active.get(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers=CLAIMANT_AUTH,
        )
        claim = active.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)

    assert messages.status_code == 200
    assert claim.status_code == 200
    claimant_text = messages.text + claim.text

    review_reason = str(scenario.expected['review_reason'])
    assert review_reason not in claimant_text

    signals = repository.list_review_signals(claim_id, scenario.claim.customer_id)
    for signal in signals:
        assert signal.signal_id not in claimant_text
        assert signal.summary not in claimant_text
        for code in signal.reason_codes:
            assert code not in claimant_text

    for retrieval in scenario.retrievals:
        assert retrieval.retrieval_id not in claimant_text
        assert retrieval.source.reference not in claimant_text

    for handoff in repository.list_handoffs(claim_id, scenario.claim.customer_id):
        for code in handoff.reason_codes:
            assert code not in claimant_text
        assert handoff.reason not in claimant_text
        assert handoff.requested_action not in claimant_text


# Which part of the Workbench projection carries the review reason. Named per
# scenario so a reason that stops being exposed fails here instead of being
# found somewhere incidental in the response body.
REASON_CHANNEL = {
    'AT-13-coverage-ambiguity': 'signals',
    'AT-14-history-signal': 'signals',
    'AT-15-conflicting-evidence': 'internal_message',
    'AT-16-retrieval-unavailable': 'handoffs',
}


def reason_in_projection(body: dict[str, Any], reason: str) -> set[str]:
    """Every channel of the Workbench projection that carries the reason.

    Reads the response only. An earlier version fell back to
    `repository.list_review_signals()`, which meant the assertion could pass
    while the projection exposed nothing — a false positive for the very claim
    the test makes.
    """
    found: set[str] = set()
    if any(reason in signal.get('reason_codes', []) for signal in body.get('signals', [])):
        found.add('signals')
    if any(reason in handoff.get('reason_codes', []) for handoff in body.get('handoffs', [])):
        found.add('handoffs')
    # The internal review-signal message carries a structured `reason`, not
    # prose, so this reads that field rather than searching message text.
    if any(
        message.get('visibility') == 'internal_only'
        and message.get('content', {}).get('type') == 'review_signal'
        and message.get('content', {}).get('reason') == reason
        for message in body.get('messages', [])
    ):
        found.add('internal_message')
    return found


def test_staff_can_see_the_review_reason_and_act(scenario: ScenarioFixture) -> None:
    """Issue #148: staff can act on what the claimant cannot see.

    The reason must be present in a named part of the projection, not merely
    somewhere in the response body.
    """
    _, client = seeded(scenario)
    claim_id = scenario.claim.claim_id

    with client as active:
        detail = active.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)

    assert detail.status_code == 200
    body: dict[str, Any] = detail.json()
    review_reason = str(scenario.expected['review_reason'])

    channels = reason_in_projection(body, review_reason)
    expected_channel = REASON_CHANNEL[scenario.scenario_id]
    assert expected_channel in channels, (
        f'{scenario.scenario_id}: staff cannot see why review is required. '
        f'Expected it in {expected_channel}; the projection carries it in '
        f'{sorted(channels) or "nothing"}.'
    )

    # Staff hold the shared claim state, not a separate board record: the
    # detail returns the same Claim State dimensions the Agent reads.
    assert body['claim_id'] == claim_id
    assert body['revision'] == scenario.claim.revision
    assert body['claim_state']['workflow_state'] == WorkflowState.PROFESSIONAL_REVIEW.value
    assert body['claim_state']['next_action'] == AgentAction.HANDOFF.value
    assert body['claim_state']['fraud_signal'] == FraudSignal.NONE.value


def test_the_review_reason_travels_three_named_routes() -> None:
    """Each condition reaches staff by a route the projection actually exposes.

    Recorded as a set so a scenario cannot quietly stop exposing its reason and
    still pass because the string appears somewhere else in the response.
    """
    assert set(REASON_CHANNEL) == {scenario.scenario_id for scenario in review_scenarios()}
    assert set(REASON_CHANNEL.values()) == {'signals', 'handoffs', 'internal_message'}

    for scenario in review_scenarios():
        _, client = seeded(scenario)
        with client as active:
            body = active.get(
                f'/api/v1/workbench/claims/{scenario.claim.claim_id}', headers=STAFF_AUTH
            ).json()
        channels = reason_in_projection(body, str(scenario.expected['review_reason']))
        assert channels == {REASON_CHANNEL[scenario.scenario_id]}, (
            f'{scenario.scenario_id} carries its reason in {sorted(channels)}, '
            f'not only {REASON_CHANNEL[scenario.scenario_id]}'
        )


def test_no_review_condition_advances_the_claim_on_its_own() -> None:
    """The four conditions Issue #130 built, checked as a set.

    Asserted across the set rather than per scenario: after narrowing a single
    scenario to `HANDOFF`, a further check that it is not `CREATE_CLAIM` can
    never fail and proves nothing. Over the whole catalogue it does.
    """
    scenarios = review_scenarios()

    assert {scenario.expected['review_reason'] for scenario in scenarios} == {
        'COVERAGE_AMBIGUOUS',
        'RELEVANT_HISTORY_REVIEW',
        'EVIDENCE_CONFLICT',
        'RETRIEVAL_UNAVAILABLE',
    }

    actions = {scenario.claim.claim_state.next_action for scenario in scenarios}
    workflows = {scenario.claim.claim_state.workflow_state for scenario in scenarios}
    coverages = {scenario.claim.claim_state.coverage for scenario in scenarios}

    # Not one of the four creates a claim or resolves coverage on its own.
    assert actions == {AgentAction.HANDOFF}
    assert workflows == {WorkflowState.PROFESSIONAL_REVIEW}
    assert AgentAction.CREATE_CLAIM not in actions
    assert WorkflowState.CREATED not in workflows
    assert Coverage.CLEAR not in coverages
