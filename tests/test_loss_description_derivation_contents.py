"""Runtime derives loss.description from an already-confirmed contents item.

loss.description restates the same loss a confirmed contents item already
records more specifically. Making it unconditionally required deadlocked the
claimant into repeating a fact they had already given (PR #1043's Bug2 fix).
Runtime now derives it once an item is confirmed, as an inference pending the
claimant's own confirmation -- it never fabricates a fact the claimant never
gave, and the derived fact keeps the originating item's own source refs and
the claimant's own words rather than the message of whatever turn happened
to trigger the derivation.
"""

import pytest
from fastapi.testclient import TestClient

from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact

LAPTOP = {
    'item_id': None,
    'description': 'Laptop computer',
    'category': 'electronics',
    'quantity': 1,
    'brand': 'Example',
    'model': 'Laptop 13',
    'loss_type': 'stolen',
    'ownership': 'owned',
    'estimated_value': {'amount': 1000, 'currency': 'NZD'},
    'reported_text': 'my laptop was stolen',
}

# reported_text absent from the claimant's message, so Runtime records the item
# as a model inference (PROPOSED), not a claimant-confirmed fact.
GUESSED_CAMERA = {**LAPTOP, 'description': 'Camera', 'reported_text': 'a camera too'}


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            # Turn 1: only a proposed (inferred) item -- nothing confirmed yet.
            envelope(
                fields=[fact('incident.type', 'theft', 'stolen')],
                items=[GUESSED_CAMERA],
                question='incident.location',
            ),
            # Turn 2: a second, confirmed item stated in the claimant's own words.
            envelope(
                fields=[fact('incident.location', 'Wellington', 'Wellington')],
                items=[LAPTOP],
                question='incident.occurred_at',
            ),
        ]
    )


def test_contents_derives_from_the_first_confirmed_item_across_turns_with_its_own_provenance(
    client: TestClient,
) -> None:
    journey = Journey(client, 'contents', 'v8-loss-desc-contents')

    first = journey.send('Something was stolen from the house.')
    # A proposed item alone neither satisfies nor derives the requirement.
    assert 'loss.description' in first['dynamic_form']['requirements']['missing_required_now']
    assert 'loss.description' not in journey.view()['form']
    first_message_id = first['claimant_message']['message_id']

    second = journey.send('It was in Wellington, my laptop was stolen')
    view = journey.view()
    items = {item['description']: item for item in view['contents_items']}
    assert items['Camera']['status'] == 'proposed'
    assert items['Laptop computer']['status'] == 'confirmed'

    derived = view['form']['loss.description']
    assert derived['value'] == 'Laptop computer'
    assert derived['source'] == 'inference'
    assert derived['status'] == 'proposed'
    # Provenance follows the confirmed item, not the position-zero proposed one
    # and not a synthetic "Derived from" string.
    assert derived['source_refs'] == items['Laptop computer']['source_refs']
    assert derived['source_refs'] == [second['claimant_message']['message_id']]
    assert first_message_id not in derived['source_refs']
    assert derived['assertions'][-1]['reported_text'] == 'my laptop was stolen'
    assert 'loss.description' not in second['dynamic_form']['requirements']['missing_required_now']
