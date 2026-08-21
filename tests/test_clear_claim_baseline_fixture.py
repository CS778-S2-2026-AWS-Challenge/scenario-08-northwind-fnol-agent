import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'
EXPECTED_STATES = ('describe', 'confirm', 'proceed')
REQUIRED_FACT_KEYS = {'field_code', 'value', 'status', 'source'}
OBSERVABLE_FACT_KEYS = ('value', 'status', 'source')


def _fixture() -> dict[str, Any]:
    loaded: object = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _facts_by_code(facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {fact['field_code']: {key: fact[key] for key in OBSERVABLE_FACT_KEYS} for fact in facts}


def _api_facts_by_code(fields: Any) -> dict[str, dict[str, Any]]:
    if isinstance(fields, dict):
        items = ({'field_code': code, **field} for code, field in fields.items())
    else:
        items = fields
    projected = {}
    for item in items:
        field = item.get('field', item)
        projected[item['field_code']] = {key: field[key] for key in OBSERVABLE_FACT_KEYS}
    return projected


def _assert_next_step(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert {key: actual[key] for key in expected} == expected


def test_clear_claim_baseline_fixture_is_repeatable_without_backend() -> None:
    first = _fixture()
    second = _fixture()

    assert first == second
    states = first['baseline_states']
    assert [state['name'] for state in states] == list(EXPECTED_STATES)

    for state in states:
        assert state['action']
        assert state['next_step']['status']
        assert state['next_step']['responsible_party']
        assert state['facts']
        for fact in state['facts']:
            assert fact.keys() >= REQUIRED_FACT_KEYS
            assert fact['field_code']
            assert fact['value']
            assert fact['status'] in {'proposed', 'confirmed'}
            assert fact['source'] in {'claimant', 'inference', 'image', 'document'}

    expected_codes = set(first['expected_proposed_fields'])
    describe = _facts_by_code(states[0]['facts'])
    confirm = _facts_by_code(states[1]['facts'])
    proceed = _facts_by_code(states[2]['facts'])
    assert set(describe) == expected_codes
    assert all(fact['status'] == 'proposed' for fact in describe.values())
    assert all(fact['status'] == 'confirmed' for fact in confirm.values())
    assert {code: fact['source'] for code, fact in confirm.items()} == {
        code: fact['source'] for code, fact in describe.items()
    }
    assert proceed == confirm
    assert states[2]['next_step']['status'] == 'ready_to_create'

    branch = first['correction_branch']
    correction = branch['state']
    corrected_facts = _facts_by_code(correction['facts'])
    assert branch['from_state'] == 'confirm'
    assert correction['name'] == 'correct'
    assert correction['action'] == 'UPDATE'
    assert (
        corrected_facts['incident.description']['value'] != confirm['incident.description']['value']
    )
    assert corrected_facts['incident.description']['source'] == 'claimant'
    assert corrected_facts['incident.location'] == confirm['incident.location']
    assert corrected_facts['loss.description'] == confirm['loss.description']


def test_clear_claim_baseline_matches_api_and_preserves_sources_on_correction(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    states = {state['name']: state for state in journey['baseline_states']}
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'at01-baseline-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = created.json()
    claim = working['claim']
    claim_id = claim['claim_id']
    session_id = working['session']['session_id']

    described = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-baseline-description',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'at01-baseline-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert described.status_code == 200
    described_body = described.json()
    assert described_body['decision']['action'] == states['describe']['action']
    assert _api_facts_by_code(described_body['form_changes']) == _facts_by_code(
        states['describe']['facts']
    )
    _assert_next_step(
        described_body['decision']['customer_next_step'], states['describe']['next_step']
    )

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-baseline-confirmation',
            'If-Match': str(described_body['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert _api_facts_by_code(confirmed_body['confirmed_fields']) == _facts_by_code(
        states['confirm']['facts']
    )
    _assert_next_step(confirmed_body['customer_next_step'], states['confirm']['next_step'])

    current = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert current.status_code == 200
    current_body = current.json()
    assert _api_facts_by_code(current_body['form']) == _facts_by_code(states['proceed']['facts'])
    _assert_next_step(current_body['customer_next_step'], states['proceed']['next_step'])

    branch = journey['correction_branch']
    corrected = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(confirmed_body['revision'])},
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': branch['input'],
                    'correction_reason': branch['correction_reason'],
                }
            ]
        },
    )
    assert corrected.status_code == 200
    corrected_body = corrected.json()
    expected_correction = branch['state']
    _assert_next_step(corrected_body['customer_next_step'], expected_correction['next_step'])

    corrected_claim = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert corrected_claim.status_code == 200
    assert _api_facts_by_code(corrected_claim.json()['form']) == _facts_by_code(
        expected_correction['facts']
    )
