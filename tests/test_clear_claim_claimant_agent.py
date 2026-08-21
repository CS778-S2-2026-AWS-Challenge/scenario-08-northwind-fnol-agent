import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding='utf-8')))


def _facts_by_code(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        item['field_code']: {
            'value': item['field']['value'],
            'status': item['field']['status'],
            'source': item['field']['source'],
        }
        for item in items
    }


def _run_clear_claim_journey(
    client: TestClient,
    auth_headers: dict[str, str],
    journey: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'{run_id}-create'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = created.json()
    claim_id = working['claim']['claim_id']
    session_id = working['session']['session_id']

    described = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{run_id}-describe',
            'If-Match': str(working['claim']['revision']),
        },
        json={
            'client_message_id': f'{run_id}-describe',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert described.status_code == 200
    described_body = described.json()
    expected_describe = next(
        state for state in journey['baseline_states'] if state['name'] == 'describe'
    )
    assert described_body['decision']['action'] == expected_describe['action']
    assert (
        described_body['decision']['customer_next_step']['status']
        == (expected_describe['next_step']['status'])
    )
    assert described_body['agent_message']['actor'] == 'agent'
    agent_text = described_body['agent_message']['content']['text'].lower()
    assert 'structured' in agent_text
    assert not any(
        forbidden in agent_text
        for forbidden in ('internal signal', 'source_refs', 'provider metadata', 'authority')
    )
    assert _facts_by_code(described_body['form_changes']) == {
        fact['field_code']: {
            'value': fact['value'],
            'status': fact['status'],
            'source': fact['source'],
        }
        for fact in expected_describe['facts']
    }

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{run_id}-confirm',
            'If-Match': str(described_body['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    expected_confirm = next(
        state for state in journey['baseline_states'] if state['name'] == 'confirm'
    )
    assert confirmed_body['customer_next_step']['status'] == expected_confirm['next_step']['status']
    assert {
        code: {
            'value': field['value'],
            'status': field['status'],
            'source': field['source'],
        }
        for code, field in confirmed_body['confirmed_fields'].items()
    } == {
        fact['field_code']: {
            'value': fact['value'],
            'status': fact['status'],
            'source': fact['source'],
        }
        for fact in expected_confirm['facts']
    }

    correction = journey['correction_branch']
    corrected = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed_body['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': correction['input'],
                    'correction_reason': correction['correction_reason'],
                }
            ]
        },
    )
    assert corrected.status_code == 200
    corrected_body = corrected.json()
    expected_correct = correction['state']
    assert corrected_body['customer_next_step']['status'] == expected_correct['next_step']['status']
    assert corrected_body['updated_fields']['incident.description']['source'] == 'claimant'
    assert corrected_body['updated_fields']['incident.description']['status'] == 'confirmed'

    current = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert current.status_code == 200
    current_body = current.json()
    current_facts = {
        code: {
            'value': field['value'],
            'status': field['status'],
            'source': field['source'],
        }
        for code, field in current_body['form'].items()
    }
    assert current_facts == {
        fact['field_code']: {
            'value': fact['value'],
            'status': fact['status'],
            'source': fact['source'],
        }
        for fact in expected_correct['facts']
    }
    assert current_body['form']['incident.location']['source'] == 'inference'
    assert current_body['form']['loss.description']['source'] == 'inference'
    assert current_body['form']['incident.location']['source_refs']
    assert current_body['form']['loss.description']['source_refs']

    created_external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{run_id}-proceed',
            'If-Match': str(corrected_body['revision']),
        },
    )
    assert created_external.status_code == 201
    creation_body = created_external.json()
    assert creation_body['decision']['action'] == 'CREATE_CLAIM'
    assert creation_body['external_claim']['creation_status'] == journey['expected_creation_status']
    assert creation_body['external_claim']['route'] == journey['expected_route']
    assert creation_body['external_claim']['source'] == journey['expected_source']
    assert creation_body['customer_next_step']['status'] == 'claim_created'

    return {
        'decision_actions': [
            described_body['decision']['action'],
            creation_body['decision']['action'],
        ],
        'next_steps': [
            described_body['decision']['customer_next_step']['status'],
            confirmed_body['customer_next_step']['status'],
            corrected_body['customer_next_step']['status'],
            creation_body['customer_next_step']['status'],
        ],
        'form': current_facts,
        'external_claim': {
            key: creation_body['external_claim'][key]
            for key in ('creation_status', 'route', 'source', 'next_step')
        },
    }


def test_at01_claimant_agent_path_is_repeatable_and_claimant_safe(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()

    first = _run_clear_claim_journey(client, auth_headers, journey, 'at01-journey-one')
    second = _run_clear_claim_journey(client, auth_headers, journey, 'at01-journey-two')

    assert first == second
