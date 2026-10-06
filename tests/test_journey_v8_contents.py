"""Contents fixture journey shares the v8 orchestration and confirmation boundary."""

import json
from collections.abc import Callable
from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from tests.journey_v8_support import CLAIMANT, Journey, V8JourneyProvider, envelope, fact


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    return V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact(
                        'incident.description',
                        'A laptop was stolen from the house.',
                        'My laptop was stolen',
                    ),
                    fact('incident.type', 'theft', 'stolen'),
                    fact(
                        'incident.occurred_at', '2026-09-20T15:00:00+12:00', 'yesterday afternoon'
                    ),
                    fact('incident.location', 'Wellington', 'Wellington'),
                    fact('loss.description', 'One stolen laptop'),
                    fact('incident.injury_or_danger', False, 'No one was hurt'),
                ],
                question='contents.items',
            ),
            envelope(
                fields=[
                    fact('theft.entry_context', 'forced_entry', 'back window was forced open'),
                    fact(
                        'incident.discovered_at',
                        '2026-09-21T08:00:00+12:00',
                        'found out at 8am today',
                    ),
                ],
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
                        'reported_text': 'one Laptop computer that I own',
                    }
                ],
                reply=(
                    'Here is what I will pass to the claims team: your Example Laptop 13, '
                    'worth about NZD 1000, was stolen from your Wellington house yesterday '
                    'afternoon; the back window was forced and you found out at 8am today; '
                    'nobody was hurt. Shall I send it?'
                ),
                summary_fields=CONTENTS_SUMMARY_FIELDS,
            ),
            envelope(confirms=True, reply='Sent. You can add the receipt whenever you have it.'),
        ]
    )


CONTENTS_SUMMARY_FIELDS = [
    'incident.description',
    'incident.occurred_at',
    'incident.location',
    'incident.injury_or_danger',
    'loss.description',
    'theft.entry_context',
    'incident.discovered_at',
    'contents.items',
]


def test_contents_item_and_theft_branch_complete_with_same_message_runtime(
    client: TestClient,
    repository: FixtureRepository,
    app: FastAPI,
    record_property: Callable[[str, object], None],
) -> None:
    journey = Journey(client, 'contents', 'v8-contents')
    first = journey.send(
        'My laptop was stolen from my house in Wellington yesterday afternoon. No one was hurt.'
    )
    assert first['dynamic_form']['selected_family'] == 'contents'
    second = journey.send(
        'The back window was forced open; I found out at 8am today. '
        'It was one Laptop computer that I own, an Example Laptop 13, worth NZD 1000.'
    )
    assert journey.view()['contents_items'][0]['description'] == 'Laptop computer'
    assert second['dynamic_form']['requirements']['ready'] is True
    assert 'Please confirm these details' not in second['agent_message']['content']['text']
    final = journey.send('Yes all correct.')
    assert final['dynamic_form']['requirements']['ready'] is True
    assert journey.view()['contents_items'][0]['status'] == 'confirmed'
    content = b'synthetic laptop receipt'
    upload = client.post(
        f'/api/v1/claims/{journey.claim_id}/evidence/uploads',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'v8-contents-upload',
            'If-Match': str(journey.revision),
        },
        json={
            'kind': 'other_document',
            'original_filename': 'receipt.pdf',
            'media_type': 'application/pdf',
            'size_bytes': len(content),
        },
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()['evidence_id']
    app.state.evidence_storage.put_upload(
        claim_id=journey.claim_id, evidence_id=evidence_id, content=content
    )
    completed = client.post(
        f'/api/v1/claims/{journey.claim_id}/evidence/{evidence_id}/complete',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'v8-contents-upload-complete',
            'If-Match': str(upload.json()['revision']),
        },
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    assert completed.status_code == 202, completed.text
    item_id = journey.view()['contents_items'][0]['item_id']
    route = f'/api/v1/claims/{journey.claim_id}/contents-items/{item_id}/evidence-associations'
    associated = client.post(
        route,
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'v8-contents-associate',
            'If-Match': str(completed.json()['revision']),
        },
        json={'evidence_id': evidence_id, 'purpose': 'proof_of_purchase'},
    )
    assert associated.status_code == 201, associated.text
    journey.revision = associated.json()['revision']
    assert client.get(route, headers=CLAIMANT).json()['items'][0]['evidence_id'] == evidence_id
    journey.create()
    record_property('planned_input_budget', json.dumps(journey.budget_measurements(repository)))
    assert len(journey.turns) <= 9
    session = repository.get_session(journey.claim_id, journey.session_id, 'cus_8f41a2c90d7e463b')
    assert session is not None
    assert session.repeated_question_count == 0
