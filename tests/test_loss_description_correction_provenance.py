"""A derived loss.description cites only the correction that states the current value.

Field-level source_refs accumulate across the assertion history, so after a
correction they still name the superseded message. Runtime's derivation must
take provenance from the origin's *current* assertion, otherwise the derived
fact would claim the pre-correction message supports the corrected value.
The family is left unresolved on the first turn so the derivation only runs
after the correction has already produced a two-message history.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import submit_message

LAPTOP: dict[str, Any] = {
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


def _new_claim(client: TestClient, key: str) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created['claim']['incident_type'] is None
    return (
        created['claim']['claim_id'],
        created['session']['session_id'],
        created['claim']['revision'],
    )


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            # Turn 1: damage stated, family still undetermined -- no derivation yet.
            envelope(
                fields=[fact('vehicle.damage_description', 'Bumper damaged', 'bumper damaged')],
                question='claim.product_family',
            ),
            # Turn 2: the claimant corrects the damage and the family settles as motor.
            envelope(
                fields=[
                    fact('claim.product_family', 'motor', 'my car'),
                    fact(
                        'vehicle.damage_description',
                        'Rear door crushed',
                        'the whole rear door is crushed',
                    ),
                ],
                question='incident.location',
            ),
        ]
    )


def test_motor_derivation_after_a_correction_cites_only_the_correcting_message(
    client: TestClient,
) -> None:
    claim_id, session_id, revision = _new_claim(client, 'loss-desc-correction')

    first = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='loss-desc-correction-1',
        client_message_id='loss-desc-correction-1',
        text='Something hit it, bumper damaged',
    )
    assert first.status_code == 200, first.text
    first_message_id = first.json()['claimant_message']['message_id']
    view = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
    assert 'loss.description' not in view['form']

    second = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=first.json()['claim_revision'],
        key='loss-desc-correction-2',
        client_message_id='loss-desc-correction-2',
        text='Actually it is my car and the whole rear door is crushed',
    )
    assert second.status_code == 200, second.text
    second_message_id = second.json()['claimant_message']['message_id']

    form = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()['form']
    damage = form['vehicle.damage_description']
    assert damage['value'] == 'Rear door crushed'
    # The corrected field keeps the superseded first statement in its history...
    superseded = [item for item in damage['assertions'] if item['status'] == 'superseded']
    assert [item['source_refs'] for item in superseded] == [[first_message_id]]

    derived = form['loss.description']
    assert derived['value'] == 'Rear door crushed'
    # ...but the derived fact cites only the correction that states the current value.
    assert derived['source_refs'] == [second_message_id]
    assert derived['assertions'][-1]['source_refs'] == [second_message_id]
    assert derived['assertions'][-1]['reported_text'] == 'the whole rear door is crushed'
    assert first_message_id not in derived['source_refs']


def test_contents_derivation_after_an_item_correction_cites_only_the_correcting_message(
    app: FastAPI,
) -> None:
    # The shared app fixture is built around the motor script above; swap in a contents
    # script here. The turn-2 proposal needs the item_id Runtime assigns on turn 1, so it
    # is appended once that id is known. Turn 1 confirms the item while the family is
    # still open (no derivation); turn 2 corrects it as the family settles as contents.
    provider = V8JourneyProvider(
        [envelope(fields=[fact('incident.type', 'theft', 'stolen')], items=[LAPTOP])]
    )
    app.state.agent_turn_provider = provider
    with TestClient(app) as client:
        claim_id, session_id, revision = _new_claim(client, 'loss-desc-item-correction')
        first = submit_message(
            client,
            CLAIMANT,
            claim_id,
            session_id,
            revision=revision,
            key='loss-desc-item-correction-1',
            client_message_id='loss-desc-item-correction-1',
            text='Something happened, my laptop was stolen',
        )
        assert first.status_code == 200, first.text
        first_message_id = first.json()['claimant_message']['message_id']
        view = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
        assert view['contents_items'][0]['status'] == 'confirmed'
        assert 'loss.description' not in view['form']
        item_id = view['contents_items'][0]['item_id']

        provider.gateway.responses.append(
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output=envelope(
                    fields=[fact('claim.product_family', 'contents', 'my belongings')],
                    items=[
                        {
                            **LAPTOP,
                            'item_id': item_id,
                            'description': 'Gaming laptop',
                            'reported_text': 'it was actually my gaming laptop',
                        }
                    ],
                    question='incident.location',
                ),
                provider_model='openai/gpt-4o-mini',
            )
        )
        second = submit_message(
            client,
            CLAIMANT,
            claim_id,
            session_id,
            revision=first.json()['claim_revision'],
            key='loss-desc-item-correction-2',
            client_message_id='loss-desc-item-correction-2',
            text='These are my belongings, it was actually my gaming laptop',
        )
        assert second.status_code == 200, second.text
        second_message_id = second.json()['claimant_message']['message_id']

        view = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
        assert [item['description'] for item in view['contents_items']] == ['Gaming laptop']
        derived = view['form']['loss.description']
        assert derived['value'] == 'Gaming laptop'
        assert derived['source_refs'] == [second_message_id]
        assert derived['assertions'][-1]['source_refs'] == [second_message_id]
        assert derived['assertions'][-1]['reported_text'] == 'it was actually my gaming laptop'
        assert first_message_id not in derived['source_refs']
