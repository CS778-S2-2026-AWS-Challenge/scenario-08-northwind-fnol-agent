"""Contents items proposed outside the contents branch never fail the claimant's turn."""

import pytest
from fastapi.testclient import TestClient

from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact

LAPTOP = {
    'item_id': None,
    'description': 'Laptop computer',
    'category': 'electronics',
    'quantity': 1,
    'brand': None,
    'model': None,
    'loss_type': 'stolen',
    'ownership': 'owned',
    'estimated_value': {'amount': 1800, 'currency': 'NZD'},
    'reported_text': 'my laptop, about $1800',
}


@pytest.fixture
def agent_turn_provider(request: pytest.FixtureRequest) -> V8JourneyProvider:
    if request.function.__name__.endswith('records_the_contents_family'):
        return V8JourneyProvider(
            [
                envelope(
                    fields=[fact('claim.product_family', 'contents', None)],
                    items=[LAPTOP],
                    reply='Thanks. When did you notice it was gone?',
                    question='incident.occurred_at',
                ),
            ]
        )
    return V8JourneyProvider(
        [
            envelope(
                items=[LAPTOP],
                reply='Thanks. Where were you parked when it was taken?',
                question='incident.location',
            ),
        ]
    )


def test_items_outside_the_contents_branch_are_left_out_and_the_turn_stands(
    client: TestClient,
) -> None:
    journey = Journey(client, 'motor', 'contents-outside-branch')

    turn = journey.send('Someone backed into my car in the car park.')

    assert turn['agent_message']['content']['text'].startswith('Thanks.')
    assert journey.view()['contents_items'] == []


def test_items_count_when_the_same_turn_records_the_contents_family(client: TestClient) -> None:
    journey = Journey(client, None, 'contents-same-turn-family')  # type: ignore[arg-type]

    journey.send('It happened at home this morning.')

    assert [item['description'] for item in journey.view()['contents_items']] == ['Laptop computer']
