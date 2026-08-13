import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository

JOURNEY_PATH = Path(__file__).parents[1] / 'journeys' / 'PRES-01-rear-end-handoff.json'


def _journey() -> dict[str, Any]:
    loaded: object = json.loads(JOURNEY_PATH.read_text(encoding='utf-8'))
    assert isinstance(loaded, dict)
    return loaded


def _message(
    client: TestClient,
    claim_id: str,
    session_id: str,
    revision: int,
    text: str,
    turn_number: int,
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': f'pres-turn-{turn_number}',
            'If-Match': str(revision),
        },
        json={
            'client_message_id': f'pres-message-{turn_number}',
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )
    assert response.status_code == 200, response.text
    payload: object = response.json()
    assert isinstance(payload, dict)
    return payload


def test_primary_rear_end_journey_preserves_context_through_handoff(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    journey = _journey()
    claimant = {'Authorization': 'Bearer synthetic-claimant'}
    created_response = client.post(
        '/api/v1/claims',
        headers={**claimant, 'Idempotency-Key': 'pres-claim'},
        json={
            'channel': 'web_agent',
            'locale': journey['claim']['locale'],
            'incident_type': journey['claim']['incident_type'],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    first_spec = journey['turns'][0]
    first = _message(
        client,
        claim_id,
        session_id,
        created['claim']['revision'],
        first_spec['input'],
        1,
    )
    assert first['decision']['action'] == first_spec['expected_action']
    assert {item['field_code'] for item in first['form_changes']} == set(
        first_spec['expected_form_fields']
    )
    assert first['decision']['customer_next_step']['status'] == first_spec['next_step_status']
    assert (
        first['agent_message']['content']['text']
        != first['decision']['customer_next_step']['summary']
    )
    assert all(
        fragment in first['agent_message']['content']['text'].lower()
        for fragment in first_spec['response_contains']
    )

    confirm_spec = journey['turns'][1]
    confirmation_response = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **claimant,
            'Idempotency-Key': 'pres-confirm',
            'If-Match': str(first['claim_revision']),
        },
        json={'field_codes': first_spec['expected_form_fields']},
    )
    assert confirmation_response.status_code == 200, confirmation_response.text
    confirmation = confirmation_response.json()
    assert confirmation['customer_next_step']['status'] == confirm_spec['expected_next_step_status']

    evidence_spec = journey['turns'][2]
    evidence_turn = _message(
        client,
        claim_id,
        session_id,
        confirmation['revision'],
        evidence_spec['input'],
        2,
    )
    assert evidence_turn['decision']['action'] == evidence_spec['expected_action']
    assert (
        evidence_turn['decision']['customer_next_step']['status']
        == evidence_spec['next_step_status']
    )
    assert all(
        fragment in evidence_turn['agent_message']['content']['text'].lower()
        for fragment in evidence_spec['response_contains']
    )
    evidence_response = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=claimant)
    assert evidence_response.status_code == 200
    evidence = evidence_response.json()['items']
    assert len(evidence) == 1
    assert evidence[0]['status'] == evidence_spec['expected_evidence_status']
    assert evidence[0]['kind'] == 'police_report'

    handoff_spec = journey['turns'][3]
    handoff_turn = _message(
        client,
        claim_id,
        session_id,
        evidence_turn['claim_revision'],
        handoff_spec['input'],
        3,
    )
    assert handoff_turn['decision']['action'] == handoff_spec['expected_action']
    assert (
        handoff_turn['decision']['customer_next_step']['status'] == handoff_spec['next_step_status']
    )
    assert all(
        fragment in handoff_turn['agent_message']['content']['text'].lower()
        for fragment in handoff_spec['response_contains']
    )

    detail_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail['claim_id'] == claim_id
    assert len(detail['messages']) == 6
    assert len(detail['handoffs']) == 1
    handoff = detail['handoffs'][0]
    expected_handoff = journey['expected_handoff']
    assert handoff['priority'] == expected_handoff['priority']
    assert handoff['support_need'] == expected_handoff['support_need']
    assert expected_handoff['requested_action_contains'] in handoff['requested_action']
    assert evidence[0]['evidence_id'] in handoff['packet']['pending_items']
    assert (
        len(handoff['packet']['prior_customer_updates'])
        >= expected_handoff['minimum_prior_customer_updates']
    )
    assert handoff['packet']['incident_summary'] == first_spec['input']

    accepted_response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff["handoff_id"]}/accept',
        headers={
            'Authorization': 'Bearer synthetic-staff',
            'Idempotency-Key': 'pres-accept-handoff',
            'If-Match': str(detail['revision']),
        },
        json={},
    )
    assert accepted_response.status_code == 200, accepted_response.text
    accepted = accepted_response.json()
    assert accepted['handoff']['status'] == 'accepted'
    assert accepted['handoff']['assigned_to'] == 'stf_demo'

    claimant_accepted = client.get(f'/api/v1/claims/{claim_id}', headers=claimant).json()
    assert claimant_accepted['handoff']['status'] == 'accepted'
    assert 'assigned_to' not in claimant_accepted['handoff']

    support_message = _message(
        client,
        claim_id,
        session_id,
        accepted['revision'],
        'Can I still send more details while I wait?',
        4,
    )
    assert support_message['agent_message'] is None
    assert support_message['decision'] is None
    support_retry = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **claimant,
            'Idempotency-Key': 'pres-turn-4',
            'If-Match': str(accepted['revision']),
        },
        json={
            'client_message_id': 'pres-message-4',
            'content': {'type': 'text', 'text': 'Can I still send more details while I wait?'},
            'evidence_refs': [],
        },
    )
    assert support_retry.status_code == 200
    assert support_retry.json() == support_message

    staff_message_response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            'Authorization': 'Bearer synthetic-staff',
            'Idempotency-Key': 'pres-staff-message',
            'If-Match': str(support_message['claim_revision']),
        },
        json={'content': {'type': 'text', 'text': 'Yes. Your additional details are saved here.'}},
    )
    assert staff_message_response.status_code == 200, staff_message_response.text
    staff_message = staff_message_response.json()
    assert staff_message['message']['actor'] == 'staff'
    staff_retry = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            'Authorization': 'Bearer synthetic-staff',
            'Idempotency-Key': 'pres-staff-message',
            'If-Match': str(support_message['claim_revision']),
        },
        json={'content': {'type': 'text', 'text': 'Yes. Your additional details are saved here.'}},
    )
    assert staff_retry.status_code == 200
    assert staff_retry.json() == staff_message

    conversation = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages', headers=claimant
    ).json()['items']
    assert any(
        item['content'].get('text') == 'Yes. Your additional details are saved here.'
        for item in conversation
    )

    latest_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-staff'},
    ).json()
    assert latest_detail['handoffs'][0]['status'] == 'in_progress'
    assert latest_detail['customer_next_step']['status'] == 'human_support_in_progress'
    claimant_request_index = next(
        index
        for index, item in enumerate(latest_detail['messages'])
        if item['content'].get('text') == handoff_spec['input']
    )
    handoff_reply_index = next(
        index
        for index, item in enumerate(latest_detail['messages'])
        if item['actor'] == 'agent'
        and item.get('in_reply_to')
        == latest_detail['messages'][claimant_request_index]['message_id']
    )
    assert claimant_request_index < handoff_reply_index

    resolved_response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff["handoff_id"]}/resolve',
        headers={
            'Authorization': 'Bearer synthetic-staff',
            'Idempotency-Key': 'pres-resolve-handoff',
            'If-Match': str(staff_message['claim_revision']),
        },
        json={
            'result': {
                'outcome': 'support_contact_started',
                'summary': 'A staff member reviewed the saved context and accepted the report.',
                'reason_codes': ['HANDOFF_ACCEPTED'],
                'source_refs': [handoff['handoff_id']],
            },
            'state_changes': [],
            'customer_update': {
                'summary': (
                    'A Northwind staff member has reviewed your report and will contact you.'
                ),
                'responsible_party': 'northwind',
                'related_refs': [handoff['handoff_id']],
            },
        },
    )
    assert resolved_response.status_code == 200, resolved_response.text
    resolved = resolved_response.json()
    assert resolved['handoff']['status'] == 'resolved'
    assert resolved['staff_action']['status'] == 'completed'
    assert resolved['customer_update']['summary'].startswith('A Northwind staff member')

    claimant_view_response = client.get(f'/api/v1/claims/{claim_id}', headers=claimant)
    assert claimant_view_response.status_code == 200
    claimant_view = claimant_view_response.json()
    assert claimant_view['customer_next_step']['status'] == 'staff_update'
    assert claimant_view['customer_next_step']['summary'] == resolved['customer_update']['summary']

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.claim_state.evidence.value == 'pending_generation'
    assert stored.claim_state.customer_support.value == 'human_requested'
    assert stored.form['authorities.police_report_reference'].status.value == 'pending_generation'
