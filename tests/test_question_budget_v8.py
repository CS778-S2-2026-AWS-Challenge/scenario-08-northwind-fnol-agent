"""#1074 on the model-gateway path: an exhausted budget cannot override a ready Claim."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact

STILL_HELPING = 'I still need help.'
FULL_ACCOUNT = (
    'Someone keyed my parked car on Queen St yesterday around 3pm and the door is scratched. '
    'No one was hurt and I can still drive it.'
)
FOLLOW_UP = 'Thanks, I have what I need. What is the registration number, if you have it?'


def _completing_turn() -> dict[str, Any]:
    return envelope(
        fields=[
            fact('claim.product_family', 'motor', 'my parked car'),
            fact('incident.description', 'Door keyed while parked.', 'Someone keyed my parked car'),
            fact('incident.location', 'Queen St', 'Queen St'),
            fact('incident.occurred_at', '2026-09-20T15:00:00+12:00', 'yesterday around 3pm'),
            fact('incident.injury_or_danger', False, 'No one was hurt'),
            fact('vehicle.damage_description', 'Door scratched', 'the door is scratched'),
            fact('vehicle.drivable', True, 'I can still drive it'),
            fact('loss.description', 'Scratched door'),
        ],
        question='vehicle.registration',
        reply=FOLLOW_UP,
    )


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    spent = [envelope(question='incident.location', reply='Where did this happen?')] * 9
    # First Claim: nine questions spend the budget, then the claimant answers everything.
    # Second Claim: the same completing turn with the budget untouched, as the baseline.
    return V8JourneyProvider([*spent, _completing_turn(), _completing_turn()])


def _outcome(journey: Journey, turn: dict[str, Any]) -> dict[str, Any]:
    action = journey.view()['primary_action']
    step = turn['decision']['customer_next_step']
    return {
        'next_step': (step['status'], step['required_items']),
        'primary_action': (action['action_code'], action['available']),
        'ready': turn['dynamic_form']['requirements']['ready'],
    }


def test_model_turn_after_the_budget_gets_the_same_next_step_as_with_budget_left(
    client: TestClient,
    repository: FixtureRepository,
    agent_turn_provider: V8JourneyProvider,
) -> None:
    spent = Journey(client, 'motor', 'budget-v8-spent')
    for _ in range(9):
        spent.send(STILL_HELPING)
    session = repository.get_session(spent.claim_id, spent.session_id, 'cus_8f41a2c90d7e463b')
    assert session is not None
    assert session.question_turn_count >= session.question_budget
    after_budget = spent.send(FULL_ACCOUNT)

    baseline = Journey(client, 'motor', 'budget-v8-baseline')
    with_budget_left = baseline.send(FULL_ACCOUNT)

    assert len(agent_turn_provider.gateway.requests) == 11
    assert after_budget['dynamic_form']['requirements']['ready'] is True
    assert after_budget['decision']['customer_next_step']['status'] != 'question_budget_reached'
    assert after_budget['agent_message']['content']['text'] == FOLLOW_UP
    assert _outcome(spent, after_budget) == _outcome(baseline, with_budget_left)
    stored = repository.get_session(spent.claim_id, spent.session_id, 'cus_8f41a2c90d7e463b')
    assert stored is not None
    assert stored.post_session_follow_up_required is False
