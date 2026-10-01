"""INV-12 rejects fabricated free-text stand-ins without dropping valid facts."""

import logging
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


@pytest.mark.parametrize(
    ('code', 'value'),
    [
        ('property.address', '>UNKNOWN<'),
        ('loss.description', 'N/A'),
        ('property.affected_areas', ['kitchen', 'TBD']),
        ('property.address', '{not_provided}'),
        ('loss.description', 'xxx'),
        ('property.address', '/property.address/'),
        ('incident.location', '<incident.location>'),
        ('property.affected_areas', ['{property.affected_areas}']),
    ],
)
def test_placeholder_stays_missing_while_other_fact_is_saved(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
    code: str,
    value: Any,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.services.turn_proposal_validation')
    app.state.agent_turn_provider = InvariantGuardedAgent(
        V8JourneyProvider(
            [
                envelope(
                    fields=[
                        fact(code, value),
                        fact('incident.occurred_at', 'last night', 'last night'),
                    ]
                ),
            ]
        )
    )
    journey = Journey(client, 'home', f'placeholder-{code}')
    result = journey.send('It happened last night.')
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None
    assert code not in claim.form
    # The claimant's 'last night' is resolved to a New Zealand date (demo journey fixes).
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2} night', claim.form['incident.occurred_at'].value)
    assert claim.form['incident.occurred_at'].status.value == 'confirmed'
    requirements = result['dynamic_form']['requirements']
    assert code in requirements['missing_required_now']
    assert code not in requirements['recorded']
    assert requirements['ready_pending_confirmation'] is False
    assert requirements['ready'] is False
    assert any(getattr(record, 'rejection', {}).get('value') == code for record in caplog.records)
    assert not any(
        item.kind == 'confirmation'
        for item in repository.list_runtime_work_items(journey.claim_id, 'cus_demo')
    )


def test_placeholder_cannot_overwrite_a_previously_recorded_address(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = InvariantGuardedAgent(
        V8JourneyProvider(
            [
                envelope(
                    fields=[fact('property.address', '12 Example Street', '12 Example Street')]
                ),
                envelope(
                    fields=[
                        fact('property.address', '[NONE]'),
                        fact('incident.occurred_at', 'last night', 'last night'),
                    ]
                ),
            ]
        )
    )
    journey = Journey(client, 'home', 'placeholder-preserve')
    journey.send('The address is 12 Example Street.')
    before = repository.get_claim(journey.claim_id, 'cus_demo')
    assert before is not None
    journey.send('It happened last night.')
    after = repository.get_claim(journey.claim_id, 'cus_demo')
    assert after is not None
    assert after.form['property.address'] == before.form['property.address']
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2} night', after.form['incident.occurred_at'].value)


def test_registered_unknown_medical_attention_enum_is_not_a_placeholder(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    # The safety text-scan (which would open a handoff and silence the
    # second turn) checks for specific injury/danger phrasing, not just the
    # word "unsafe" alone -- so "unsafe" confirms incident.injury_or_danger
    # (via the weaker safety marker the claimant-quote check accepts) and
    # activates the injury.details branch that registers
    # injury.medical_attention, without tripping the stricter interrupt scan.
    app.state.agent_turn_provider = InvariantGuardedAgent(
        V8JourneyProvider(
            [
                envelope(
                    fields=[
                        fact('incident.location', 'Queen St', 'Queen St'),
                        fact('incident.injury_or_danger', True, 'unsafe'),
                    ]
                ),
                envelope(fields=[fact('injury.medical_attention', 'unknown', 'I do not know')]),
            ]
        )
    )
    journey = Journey(client, 'motor', 'placeholder-enum-control')
    journey.send('It happened on Queen St, and the road felt unsafe at the time.')
    journey.send('I do not know whether they have received medical attention.')
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None
    assert claim.form['injury.medical_attention'].value == 'unknown'
    assert claim.form['injury.medical_attention'].status.value == 'confirmed'
