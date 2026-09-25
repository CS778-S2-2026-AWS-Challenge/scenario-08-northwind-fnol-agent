"""Runtime derives loss.description from an already-confirmed vehicle.damage_description.

loss.description restates the same loss vehicle.damage_description already
records more specifically. Making it unconditionally required deadlocked the
claimant into repeating a fact they had already given (PR #1043's Bug2 fix).
Runtime now derives it once the vehicle damage is confirmed, as an inference
pending the claimant's own confirmation -- it never fabricates a fact the
claimant never gave.
"""

import pytest
from fastapi.testclient import TestClient

from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact('claim.product_family', 'motor', 'My car'),
                    fact('vehicle.damage_description', 'Bumper damaged', 'bumper damaged'),
                ],
                question='incident.injury_or_danger',
            ),
        ]
    )


def test_motor_derives_loss_description_from_confirmed_vehicle_damage(client: TestClient) -> None:
    journey = Journey(client, 'motor', 'v8-loss-desc-motor')
    journey.send('My car was rear-ended, bumper damaged.')
    form = journey.view()['form']
    assert form['vehicle.damage_description']['value'] == 'Bumper damaged'
    assert form['vehicle.damage_description']['status'] == 'confirmed'
    derived = form['loss.description']
    assert derived['value'] == 'Bumper damaged'
    assert derived['source'] == 'inference'
    assert derived['status'] == 'proposed'
