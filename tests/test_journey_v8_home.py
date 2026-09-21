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
                ]
            ),
            envelope(confirms=True),
        ]
    )


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
    assert third['dynamic_form']['requirements']['ready_pending_confirmation'] is True
    confirmed = journey.send('Yes all correct.')
    assert confirmed['dynamic_form']['requirements']['ready'] is True
    journey.create()
    record_property('planned_input_budget', json.dumps(journey.budget_measurements(repository)))
    assert len(journey.turns) <= 8
    session = repository.get_session(journey.claim_id, journey.session_id, 'cus_demo')
    assert session is not None
    assert session.repeated_question_count == 0
