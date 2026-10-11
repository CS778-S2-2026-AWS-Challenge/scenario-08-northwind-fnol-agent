"""Motor fixture acceptance: facts, safety, continued chat, support and creation."""

import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact(
                        'incident.description',
                        'Rear-end collision on Queen St.',
                        'My car was rear-ended',
                    ),
                    fact('incident.location', 'Queen St', 'Queen St'),
                    fact(
                        'incident.occurred_at', '2026-09-20T15:00:00+12:00', 'yesterday around 3pm'
                    ),
                    fact('vehicle.damage_description', 'Bumper damaged', 'bumper damaged'),
                    fact('claim.product_family', 'motor', 'My car'),
                    fact('incident.type', 'collision', 'rear-ended'),
                    fact('loss.description', 'Rear bumper damage'),
                ],
                question='incident.injury_or_danger',
                services=['vehicle_damage_assessment_routing'],
                requested={'vehicle_damage_assessment_routing': 'need an assessor'},
            ),
            envelope(
                fields=[fact('incident.injury_or_danger', False, 'No one was hurt')],
                question='vehicle.drivable',
            ),
            envelope(
                fields=[fact('incident.injury_or_danger', True, 'my passenger has a sore neck')]
            ),
            # The handoff opened by this turn silences the model entirely: the
            # two claimant messages sent while it is open are only recorded,
            # never reach the model. Once support resolves the handoff, the
            # next real model call sees both of those messages in its own
            # conversation history and catches up on every fact they carried
            # in this one turn.
            envelope(
                fields=[
                    fact('injury.persons_affected', ['passenger'], 'Just the passenger'),
                    fact('injury.severity_reported', 'minor', "she says it's minor"),
                    fact('injury.medical_attention', 'none', 'no ambulance'),
                    fact('vehicle.drivable', False, "Can't drive it"),
                ],
                services=['vehicle_recovery_request'],
            ),
            envelope(
                fields=[
                    fact('parties.other_parties', True, 'another vehicle'),
                    fact(
                        'incident.liability_position',
                        'other_party_accepts',
                        'the other driver admitted it was their fault',
                    ),
                ],
                reply=(
                    'Here is what I will pass to the claims team: rear-ended on Queen St '
                    'yesterday around 3pm, bumper damaged and the car cannot be driven, your '
                    'passenger has a sore neck (minor, no ambulance), another vehicle was '
                    'involved and its driver accepted fault. Anything to change before I send it?'
                ),
                summary_fields=MOTOR_SUMMARY_FIELDS,
            ),
            envelope(confirms=True, reply='Sent. The claims team will take it from here.'),
        ]
    )


MOTOR_SUMMARY_FIELDS = [
    'claim.product_family',
    'incident.description',
    'incident.location',
    'incident.occurred_at',
    'incident.injury_or_danger',
    'injury.persons_affected',
    'injury.severity_reported',
    'injury.medical_attention',
    'vehicle.damage_description',
    'vehicle.drivable',
    'parties.other_parties',
    'incident.liability_position',
    'loss.description',
]


def test_motor_injury_is_recorded_without_retroactive_safety_handoff(
    client: TestClient,
    repository: FixtureRepository,
    record_property: Callable[[str, object], None],
) -> None:
    journey = Journey(client, 'motor', 'v8-motor')
    first = journey.send(
        'My car was rear-ended on Queen St yesterday around 3pm, bumper damaged, need an assessor'
    )
    assert (
        first['agent_message']['message_actions'][0]['service_identity']
        == 'vehicle_damage_assessment_routing'
    )
    assert 'incident.injury_or_danger' in first['decision']['customer_next_step']['required_items']
    second = journey.send('No one was hurt')
    assert (
        'incident.injury_or_danger'
        not in second['dynamic_form']['requirements']['missing_required_now']
    )
    assert journey.view()['form']['incident.injury_or_danger']['value'] is False
    third = journey.send('Actually my passenger has a sore neck')
    assert third['handoff'] is None
    assert journey.view()['form']['incident.injury_or_danger']['value'] is True
    assert (
        'injury.persons_affected' in third['dynamic_form']['requirements']['missing_required_now']
    )
    fourth = journey.send("Just the passenger, she says it's minor, no ambulance")
    assert journey.view()['form']['vehicle.drivable']['value'] is False
    assert all(
        code not in fourth['dynamic_form']['requirements']['missing_required_now']
        for code in (
            'injury.persons_affected',
            'injury.severity_reported',
            'injury.medical_attention',
            'vehicle.drivable',
        )
    )
    assert any(
        action['service_identity'] == 'vehicle_recovery_request'
        for action in fourth['agent_message']['message_actions']
    )
    fifth = journey.send(
        'There was another vehicle involved and the other driver admitted it was their fault.'
    )
    assert fifth['dynamic_form']['requirements']['ready'] is True
    fifth_text = fifth['agent_message']['content']['text']
    assert fifth_text.startswith('Here is what I will pass to the claims team')
    assert 'Please confirm these details' not in fifth_text
    final = journey.send('Yes all correct')
    assert final['dynamic_form']['requirements']['ready'] is True
    assert final['agent_message']['content']['text'] == (
        'Sent. The claims team will take it from here.'
    )
    journey.create()
    record_property('planned_input_budget', json.dumps(journey.budget_measurements(repository)))
    assert len(journey.turns) <= 9
    session = repository.get_session(journey.claim_id, journey.session_id, 'cus_8f41a2c90d7e463b')
    assert session is not None
    # The injury is recorded in a normal model turn, so the required-item
    # counter may include the expected follow-up questions for its details.
    assert session.repeated_question_count <= 2, [
        (
            turn['decision']['customer_next_step']['required_items'],
            turn['agent_message']['content']['text'],
        )
        for turn in journey.turns
    ]
