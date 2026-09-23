"""Independent end-to-end regressions for claimant fact semantic authority."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.models import FormStatus
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import submit_message


def _new_claim(client: TestClient, key: str) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body['claim']['claim_id'], body['session']['session_id'], body['claim']['revision']


def test_temporal_non_answer_is_recorded_as_unavailable_not_as_a_confirmed_time(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = InvariantGuardedAgent(
        V8JourneyProvider(
            [
                envelope(
                    fields=[
                        fact(
                            'incident.occurred_at',
                            'I do not know when',
                            'I do not know when',
                        )
                    ]
                )
            ]
        )
    )
    claim_id, session_id, revision = _new_claim(client, 'semantic-temporal')
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='semantic-temporal-turn',
        text='I do not know when.',
    )
    assert response.status_code == 200, response.text
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    # "I do not know when" is not a time. It is the claimant telling us they
    # cannot supply one yet: recorded as unavailable, never as a confirmed
    # value, and it does not satisfy the occurred-at requirement.
    field = claim.form['incident.occurred_at']
    assert field.value is None
    assert field.status is FormStatus.UNAVAILABLE
    assert field.assertions[-1].reported_text == 'I do not know when'
    requirements = response.json()['dynamic_form']['requirements']
    assert 'incident.occurred_at' not in requirements['satisfied']
    assert 'incident.occurred_at' in requirements['by_state']['unavailable']
    assert response.json()['agent_message'] is not None


def test_family_mismatched_field_is_not_confirmed_through_full_turn(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = InvariantGuardedAgent(
        V8JourneyProvider(
            [
                envelope(
                    fields=[
                        fact('claim.product_family', 'motor', 'My car was rear-ended'),
                        fact('property.address', '1 Queen Street', '1 Queen Street'),
                        fact('vehicle.damage_description', 'Dented bumper', 'car was rear-ended'),
                    ]
                )
            ]
        )
    )
    claim_id, session_id, revision = _new_claim(client, 'semantic-family')
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='semantic-family-turn',
        text='My car was rear-ended at 1 Queen Street.',
    )
    assert response.status_code == 200, response.text
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.incident_type == 'motor'
    assert claim.form['vehicle.damage_description'].status is FormStatus.CONFIRMED
    assert 'property.address' not in claim.form
    requirements = response.json()['dynamic_form']['requirements']
    assert 'property.address' not in requirements['satisfied']
    assert 'property.address' not in requirements['recorded']
