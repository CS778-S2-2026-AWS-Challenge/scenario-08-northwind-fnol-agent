import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding='utf-8')))


def test_at01_natural_intake_confirms_then_creates_mock_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'at01-working-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = created.json()
    claim = working['claim']
    claim_id = claim['claim_id']
    session_id = working['session']['session_id']

    before_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-create-too-early',
            'If-Match': str(claim['revision']),
        },
    )
    assert before_confirmation.status_code == 409
    assert before_confirmation.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-description-turn',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'at01-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200
    turn_body = turn.json()
    proposed = {item['field_code'] for item in turn_body['form_changes']}
    assert proposed == set(journey['expected_proposed_fields'])
    assert turn_body['decision']['action'] == 'CONFIRM'

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-confirm-all',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body['customer_next_step']['status'] == 'ready_to_create'

    creation_headers = {
        **auth_headers,
        'Idempotency-Key': 'at01-controlled-creation',
        'If-Match': str(confirmed_body['revision']),
    }
    created_external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    assert created_external.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == created_external.json()

    repository._idempotency.pop(
        (
            'cus_demo',
            f'/api/v1/claims/{claim_id}/creation',
            'at01-controlled-creation',
        )
    )
    recovered = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    assert recovered.status_code == 201
    assert recovered.json() == created_external.json()

    conflicting_reuse = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-controlled-creation',
            'If-Match': str(confirmed_body['revision'] + 1),
        },
    )
    assert conflicting_reuse.status_code == 409
    assert conflicting_reuse.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    duplicate_operation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-create-again',
            'If-Match': str(created_external.json()['revision']),
        },
    )
    assert duplicate_operation.status_code == 409
    assert duplicate_operation.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    result = created_external.json()
    assert result['decision']['action'] == 'CREATE_CLAIM'
    assert result['decision']['reason_codes'] == ['CLAIM_CREATION_AUTHORISED']
    assert result['external_claim']['creation_status'] == journey['expected_creation_status']
    assert result['external_claim']['route'] == journey['expected_route']
    assert result['external_claim']['source'] == journey['expected_source']
    assert result['external_claim']['claim_number']
    assert result['external_claim']['next_step']
    assert result['external_claim']['expected_by']
    assert result['customer_next_step']['status'] == 'claim_created'

    claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_view.status_code == 200
    projection = claimant_view.json()
    assert projection['workflow_state'] == 'created'
    assert projection['external_claim'] == result['external_claim']


def test_clear_motor_intake_classifies_missing_incident_type_before_creation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'unclassified-working-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201
    working = created.json()
    claim = working['claim']

    turn = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions/{working["session"]["session_id"]}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-description-turn',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'unclassified-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200
    turn_body = turn.json()
    proposed = {item['field_code'] for item in turn_body['form_changes']}
    assert proposed == {*journey['expected_proposed_fields'], 'incident.type'}

    confirmed = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-confirm-all',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': sorted(proposed)},
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body['customer_next_step']['status'] == 'ready_to_create'

    claimant_view = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=auth_headers)
    assert claimant_view.status_code == 200
    assert claimant_view.json()['incident_type'] == 'motor'

    created_external = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-controlled-creation',
            'If-Match': str(confirmed_body['revision']),
        },
    )
    assert created_external.status_code == 201


def test_claim_creation_rejects_a_stale_working_claim_revision(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'stale-creation-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()

    response = client.post(
        f'/api/v1/claims/{created["claim"]["claim_id"]}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'stale-creation-attempt',
            'If-Match': '999',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert response.json()['error']['current_revision'] == 1


def test_pending_later_evidence_does_not_block_controlled_claim_creation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'pending-creation-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-description',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'pending-creation-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    ).json()
    confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-confirm',
            'If-Match': str(turn['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    ).json()
    evidence_turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-evidence',
            'If-Match': str(confirmation['revision']),
        },
        json={
            'client_message_id': 'pending-creation-evidence',
            'content': {
                'type': 'text',
                'text': 'Police said the police report will be ready next week.',
            },
            'evidence_refs': [],
        },
    ).json()

    response = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-controlled-creation',
            'If-Match': str(evidence_turn['claim_revision']),
        },
    )

    assert response.status_code == 201
    assert response.json()['external_claim']['creation_status'] == 'created'
    evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth_headers).json()[
        'items'
    ]
    assert evidence[0]['status'] == 'pending_generation'
