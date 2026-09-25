"""Runtime derives loss.description from an already-confirmed first contents item.

loss.description restates the same loss the first confirmed contents item
already records more specifically. Making it unconditionally required
deadlocked the claimant into repeating a fact they had already given (PR
#1043's Bug2 fix). Runtime now derives it once that item is confirmed, as an
inference pending the claimant's own confirmation -- it never fabricates a
fact the claimant never gave.
"""

import pytest
from fastapi.testclient import TestClient

from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            envelope(
                fields=[fact('incident.type', 'theft', 'stolen')],
                items=[
                    {
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
                ],
                question='incident.location',
            ),
        ]
    )


def test_contents_derives_loss_description_from_confirmed_first_item(client: TestClient) -> None:
    journey = Journey(client, 'contents', 'v8-loss-desc-contents')
    journey.send('My laptop was stolen from the house.')
    form = journey.view()['form']
    derived = form['loss.description']
    assert derived['value'] == 'Laptop computer'
    assert derived['source'] == 'inference'
    assert derived['status'] == 'proposed'
