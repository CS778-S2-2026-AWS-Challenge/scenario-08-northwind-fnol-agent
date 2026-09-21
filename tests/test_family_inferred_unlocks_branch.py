"""INV-11: a proposed family permits collection without granting creation authority."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import submit_message


def test_inferred_home_reaches_batch_confirmation_without_family_deadlock(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.agent_turn_provider = V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact('claim.product_family', 'home'),
                    fact('incident.description', 'A bathroom pipe burst.'),
                    fact('incident.occurred_at', '2026-09-20T23:00:00+12:00'),
                    fact('incident.location', 'Wellington'),
                    fact('loss.description', 'Lounge ceiling water damage'),
                ]
            ),
            envelope(
                fields=[
                    fact('incident.injury_or_danger', False),
                    fact('property.address', '12 Example Street, Wellington'),
                    fact('property.affected_areas', ['lounge ceiling']),
                    fact('property.ongoing_risk', 'none'),
                    fact('property.habitable', True),
                ]
            ),
            envelope(confirms=True),
        ]
    )
    created = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': 'inferred-home'},
        json={},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    revision = created['claim']['revision']
    turns = []
    for index, text in enumerate(
        [
            'My bathroom pipe burst last night and flooded the lounge in Wellington.',
            'No one is hurt. The water is off. The address is 12 Example Street, Wellington. '
            'Only the lounge ceiling is affected and we can still live here.',
        ]
    ):
        response = submit_message(
            client,
            CLAIMANT,
            claim_id,
            session_id,
            revision=revision,
            key=f'inferred-home-{index}',
            client_message_id=f'inferred-home-{index}',
            text=text,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        revision = body['claim_revision']
        turns.append(body)
        requirements = body['dynamic_form']['requirements']
        satisfied = set(requirements['satisfied'])
        recorded = set(requirements['recorded'])
        missing = set(requirements['missing_required_now'])
        assert not (satisfied & recorded or satisfied & missing or recorded & missing)
        assert 'claim.product_family' in recorded
        if index == 0:
            assert (
                'claim.product_family'
                not in body['decision']['customer_next_step']['required_items']
            )

    assert turns[0]['dynamic_form']['selected_family'] == 'home'
    assert 'property.address' in turns[0]['dynamic_form']['requirements']['missing_required_now']
    assert turns[1]['dynamic_form']['requirements']['ready_pending_confirmation'] is True
    view = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
    assert view['form']['claim.product_family']['status'] == 'proposed'
    blocked = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={**CLAIMANT, 'Idempotency-Key': 'inferred-premature', 'If-Match': str(revision)},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert 'family must be confirmed' in blocked.json()['error']['message']
    confirmed = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='inferred-confirm',
        client_message_id='inferred-confirm',
        text='Yes, all correct.',
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['dynamic_form']['requirements']['ready'] is True
    view = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
    assert view['form']['claim.product_family']['status'] == 'confirmed'
    assert all(field['status'] == 'confirmed' for field in view['form'].values())
