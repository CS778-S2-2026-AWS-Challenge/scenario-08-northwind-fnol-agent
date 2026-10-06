"""Home fixture journey through the real v8 claimant API and reducer."""

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
                        'Bathroom pipe burst and flooded the lounge.',
                        'pipe burst in my bathroom',
                    ),
                    fact('incident.type', 'water', 'pipe burst'),
                    fact('incident.occurred_at', '2026-09-20T23:00:00+12:00', 'last night'),
                    fact('incident.location', 'Wellington', 'Wellington'),
                    fact('loss.description', 'Lounge ceiling and wall water damage'),
                ],
                question='incident.injury_or_danger',
            ),
            envelope(
                fields=[
                    fact('incident.injury_or_danger', False, 'No one was hurt'),
                    fact('property.ongoing_risk', 'active_leak', 'water is still dripping'),
                ],
                question='property.address',
            ),
            # The model judges the report is complete enough and reads it back in
            # its own words; summary_fields declares what it read back.
            envelope(
                fields=[
                    fact(
                        'property.address',
                        '12 Example Street, Wellington',
                        '12 Example Street, Wellington',
                    ),
                    fact(
                        'property.affected_areas',
                        ['lounge ceiling', 'wall'],
                        'lounge ceiling and wall',
                    ),
                    fact('property.habitable', True, 'we can still live here'),
                ],
                reply=(
                    'Here is what I will pass to the claims team: a bathroom pipe burst last '
                    'night at 12 Example Street, Wellington, flooding the lounge; the ceiling '
                    'and wall are affected, water is still dripping, nobody was hurt and you '
                    'can still live there. Is that all correct?'
                ),
                summary_fields=HOME_SUMMARY_FIELDS,
            ),
            envelope(confirms=True, reply='Thank you, that is all confirmed.'),
        ]
    )


HOME_SUMMARY_FIELDS = [
    'incident.description',
    'incident.occurred_at',
    'incident.location',
    'loss.description',
    'property.address',
    'property.affected_areas',
    'property.ongoing_risk',
    'property.habitable',
]


def test_home_completes_by_conversation_without_form_confirmation(
    client: TestClient,
    repository: FixtureRepository,
    record_property: Callable[[str, object], None],
) -> None:
    journey = Journey(client, 'home', 'v8-home')
    first = journey.send(
        'A pipe burst in my bathroom last night in Wellington and flooded the lounge.'
    )
    assert first['dynamic_form']['selected_family'] == 'home'
    second = journey.send('No one was hurt but water is still dripping from the ceiling.')
    assert journey.view()['form']['property.ongoing_risk']['value'] == 'active_leak'
    assert (
        'property.ongoing_risk'
        not in second['dynamic_form']['requirements']['missing_required_now']
    )
    third = journey.send(
        '12 Example Street, Wellington. The lounge ceiling and wall are affected; '
        'we can still live here.'
    )
    # Every required fact now has a disposition, so the report is already
    # ready; the summary is the model's courtesy read-back, not a Runtime gate.
    assert third['dynamic_form']['requirements']['ready'] is True
    assert third['dynamic_form']['requirements']['unresolved'] == []
    third_text = third['agent_message']['content']['text']
    assert third_text.startswith('Here is what I will pass to the claims team')
    assert 'Please confirm these details' not in third_text
    assert 'property.' not in third_text and 'incident.' not in third_text
    confirmed = journey.send('Yes all correct.')
    assert confirmed['dynamic_form']['requirements']['ready'] is True
    assert confirmed['agent_message']['content']['text'] == 'Thank you, that is all confirmed.'
    form = journey.view()['form']
    assert all(form[code]['status'] == 'confirmed' for code in HOME_SUMMARY_FIELDS)
    journey.create()
    record_property('planned_input_budget', json.dumps(journey.budget_measurements(repository)))
    assert len(journey.turns) <= 8
    session = repository.get_session(journey.claim_id, journey.session_id, 'cus_8f41a2c90d7e463b')
    assert session is not None
    assert session.repeated_question_count == 0
