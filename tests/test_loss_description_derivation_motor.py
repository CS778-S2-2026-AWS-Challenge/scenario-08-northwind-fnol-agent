"""Runtime derives loss.description from an already-confirmed vehicle.damage_description.

loss.description restates the same loss vehicle.damage_description already
records more specifically. Making it unconditionally required deadlocked the
claimant into repeating a fact they had already given (PR #1043's Bug2 fix).
Runtime now derives it once the vehicle damage is confirmed, as an inference
pending the claimant's own confirmation -- it never fabricates a fact the
claimant never gave, and the derived fact keeps the vehicle damage's own
source refs and the claimant's own words as its provenance.
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
            envelope(
                fields=[fact('incident.injury_or_danger', False, 'No one was hurt')],
                question='incident.location',
            ),
        ]
    )


def test_motor_derives_loss_description_with_the_vehicle_damage_provenance(
    client: TestClient,
) -> None:
    journey = Journey(client, 'motor', 'v8-loss-desc-motor')
    first = journey.send('My car was rear-ended, bumper damaged.')
    form = journey.view()['form']
    assert form['vehicle.damage_description']['status'] == 'confirmed'
    derived = form['loss.description']
    assert derived['value'] == 'Bumper damaged'
    assert derived['source'] == 'inference'
    assert derived['status'] == 'proposed'
    # The audit trail points at the message that stated the damage, quoting the
    # claimant's words, not a synthetic "Derived from" note.
    assert derived['source_refs'] == form['vehicle.damage_description']['source_refs']
    assert derived['source_refs'] == [first['claimant_message']['message_id']]
    assert derived['assertions'][-1]['reported_text'] == 'bumper damaged'
    assert 'loss.description' not in first['dynamic_form']['requirements']['missing_required_now']

    # A later turn that says nothing about damage does not re-derive or re-attribute it.
    second = journey.send('No one was hurt')
    later = journey.view()['form']['loss.description']
    assert later['source_refs'] == [first['claimant_message']['message_id']]
    assert second['claimant_message']['message_id'] not in later['source_refs']
