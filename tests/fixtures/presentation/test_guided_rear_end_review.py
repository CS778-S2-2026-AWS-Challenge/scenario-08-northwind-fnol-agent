import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.domain.retrieval import PolicyRetrievalRecord
from backend.repositories.fixture import FixtureRepository

JOURNEY_PATH = Path(__file__).parents[1] / 'journeys' / 'PRES-02-guided-rear-end-review.json'


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
            'Idempotency-Key': f'pres02-turn-{turn_number}',
            'If-Match': str(revision),
        },
        json={
            'client_message_id': f'pres02-message-{turn_number}',
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )
    assert response.status_code == 200, response.text
    payload: object = response.json()
    assert isinstance(payload, dict)
    return payload


def _assert_customer_text_excludes_internal_terms(payload: dict[str, Any]) -> None:
    customer_text = json.dumps(
        {
            'message': payload['agent_message'],
            'decision': payload['decision'],
            'handoff': payload['handoff'],
        }
    ).lower()
    for internal_term in (
        'policy_retrieval_uncertainty',
        'collision_wording_requires_interpretation',
        'pres-02-policy-record-v1',
        'professional_review_required',
    ):
        assert internal_term not in customer_text


def test_guided_rear_end_report_reaches_sourced_staff_review_and_returns_to_customer(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    journey = _journey()
    claimant = {'Authorization': 'Bearer synthetic-claimant'}
    staff = {'Authorization': 'Bearer synthetic-staff'}
    created_response = client.post(
        '/api/v1/claims',
        headers={**claimant, 'Idempotency-Key': 'pres02-claim'},
        json={'channel': 'web_agent', 'locale': journey['claim']['locale']},
    )
    assert created_response.status_code == 201, created_response.text
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
    assert first['decision']['customer_next_step']['status'] == first_spec['next_step_status']
    assert first['decision']['customer_next_step']['required_items'] == [
        first_spec['required_item']
    ]
    assert first['decision']['action'] != 'CONFIRM'
    assert not any(
        item.startswith('confirm:')
        for item in first['decision'].get('next_action_requirements', [])
    )
    fields = {item['field_code']: item['field'] for item in first['form_changes']}
    assert fields['incident.description']['status'] == 'confirmed'
    assert fields['incident.description']['source'] == 'claimant'
    assert fields['claim.product_family']['value'] == 'motor'
    assert fields['claim.product_family']['source'] == 'inference'
    assert fields['claim.product_family']['status'] == 'proposed'
    assert fields['incident.type']['value'] == 'collision'
    assert fields['incident.type']['source'] == 'inference'
    assert fields['incident.type']['status'] == 'proposed'
    _assert_customer_text_excludes_internal_terms(first)

    safety_spec = journey['turns'][1]
    safety = _message(
        client,
        claim_id,
        session_id,
        first['claim_revision'],
        safety_spec['input'],
        2,
    )
    assert safety['decision']['action'] == safety_spec['expected_action']
    assert safety['decision']['customer_next_step']['status'] == safety_spec['next_step_status']
    assert safety['decision']['customer_next_step']['required_items'] == [
        safety_spec['required_item']
    ]
    safety_change = next(
        item for item in safety['form_changes'] if item['field_code'] == 'incident.injury_or_danger'
    )
    assert safety_change['field']['value'] is False
    assert safety_change['field']['status'] == 'confirmed'
    _assert_customer_text_excludes_internal_terms(safety)

    time_spec = journey['turns'][2]
    timed = _message(
        client,
        claim_id,
        session_id,
        safety['claim_revision'],
        time_spec['input'],
        3,
    )
    assert timed['decision']['action'] == time_spec['expected_action']
    assert timed['decision']['customer_next_step']['status'] == time_spec['next_step_status']
    assert timed['handoff'] is None
    time_change = next(
        item for item in timed['form_changes'] if item['field_code'] == 'incident.occurred_at'
    )
    assert time_change['field']['status'] == 'confirmed'
    assert time_change['field']['source'] == 'claimant'
    _assert_customer_text_excludes_internal_terms(timed)

    retrievals = repository.list_retrieval_records(claim_id, 'cus_demo')
    assert len(retrievals) == 1
    retrieval = retrievals[0]
    assert isinstance(retrieval, PolicyRetrievalRecord)
    assert retrieval.facts.policy_reference == journey['policy']['reference']
    assert retrieval.facts.status == 'active'
    assert retrieval.source.system == journey['policy']['source_system']
    assert retrieval.source.reference == journey['policy']['source_reference']
    assert [item.code for item in retrieval.uncertainty] == [journey['policy']['review_reason']]
    stored_after_lookup = repository.get_claim(claim_id, 'cus_demo')
    assert stored_after_lookup is not None
    assert stored_after_lookup.claim_state.coverage.value == 'review_required'
    assert repository.list_handoffs(claim_id, 'cus_demo') == []

    evidence_spec = journey['turns'][3]
    queued = _message(
        client,
        claim_id,
        session_id,
        timed['claim_revision'],
        evidence_spec['input'],
        4,
    )
    assert queued['decision']['action'] == evidence_spec['expected_action']
    assert queued['decision']['customer_next_step']['status'] == evidence_spec['next_step_status']
    assert queued['handoff'] is None
    _assert_customer_text_excludes_internal_terms(queued)

    evidence_response = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=claimant)
    assert evidence_response.status_code == 200
    evidence = evidence_response.json()['items']
    assert len(evidence) == 1
    assert evidence[0]['status'] == evidence_spec['expected_evidence_status']
    assert evidence[0]['kind'] == 'police_report'

    claimant_queued = client.get(f'/api/v1/claims/{claim_id}', headers=claimant).json()
    assert claimant_queued['handoff'] is None
    assert claimant_queued['workflow_state'] == 'professional_review'
    claimant_serialised = json.dumps(claimant_queued).lower()
    assert journey['policy']['source_reference'].lower() not in claimant_serialised
    assert journey['policy']['review_reason'].lower() not in claimant_serialised

    detail_response = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff)
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail['claim_id'] == claim_id
    assert detail['incident']['family'] is None
    staff_fields = {
        item['code']: item['field']
        for item in client.get(f'/api/v1/workbench/claims/{claim_id}/fields', headers=staff).json()[
            'items'
        ]
    }
    assert staff_fields['claim.product_family']['value'] == 'motor'
    assert staff_fields['claim.product_family']['status'] == 'proposed'
    assert staff_fields['incident.type']['value'] == 'collision'
    assert staff_fields['incident.type']['status'] == 'proposed'
    assert detail['claim_state']['coverage'] == 'review_required'
    assert detail['claim_state']['workflow_state'] == 'professional_review'
    handoffs = client.get(f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff).json()[
        'items'
    ]
    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff['type'] == 'professional_review'
    assert handoff['support_need'] is None
    assert handoff['trigger'] == 'professional_review_required'
    assert 'Determine whether' in handoff['requested_action']
    assert 'pending police report must not block' in handoff['requested_action']
    assert handoff['packet']['incident_summary'] == first_spec['input']
    assert handoff['packet']['form_snapshot']['incident.injury_or_danger']['value'] is False
    assert evidence[0]['evidence_id'] in handoff['packet']['pending_items']
    assert handoff['packet']['policy_citation_refs'] == [retrieval.retrieval_id]
    assert retrieval.retrieval_id in handoff['packet']['source_refs']
    review_signal = repository.list_review_signals(claim_id, 'cus_demo')[0]
    assert review_signal.signal_id in handoff['packet']['source_refs']
    assert any(
        item.startswith('tag_registry:northwind-fnol-staff-tags:')
        for item in handoff['packet']['source_refs']
    )
    assert any(
        item['evidence_id'] == evidence[0]['evidence_id'] and item['status'] == 'pending'
        for item in handoff['packet']['evidence']
    )
    assert any(
        signal['reason_codes'] == [journey['policy']['review_reason']]
        and signal['source_evidence'][0]['retrieval_id'] == retrieval.retrieval_id
        for signal in client.get(
            f'/api/v1/workbench/claims/{claim_id}/signals', headers=staff
        ).json()['items']
    )

    continued = _message(
        client,
        claim_id,
        session_id,
        detail['revision'],
        'The car is still drivable and parked safely.',
        5,
    )
    assert continued['agent_message'] is not None
    assert continued['decision']['action'] == 'UPDATE'
    assert continued['decision']['customer_next_step']['status'] == 'professional_review_queued'

    accepted_response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff["handoff_id"]}/accept',
        headers={
            **staff,
            'Idempotency-Key': 'pres02-accept',
            'If-Match': str(continued['claim_revision']),
        },
        json={},
    )
    assert accepted_response.status_code == 200, accepted_response.text
    accepted = accepted_response.json()
    assert accepted['handoff']['status'] == 'accepted'
    claimant_in_review = client.get(f'/api/v1/claims/{claim_id}', headers=claimant).json()
    assert claimant_in_review['customer_next_step']['status'] == 'professional_review_in_progress'
    assert claimant_in_review['handoff'] is None

    resolution = journey['staff_resolution']
    resolved_response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff["handoff_id"]}/resolve',
        headers={
            **staff,
            'Idempotency-Key': 'pres02-resolve',
            'If-Match': str(accepted['revision']),
        },
        json={
            'result': {
                'outcome': 'professional_review_completed',
                'summary': 'The cited collision wording permits the report to continue.',
                'reason_codes': ['POLICY_SECTION_CONFIRMED'],
                'source_refs': handoff['packet']['source_refs'],
            },
            'state_changes': [
                {'path': 'claim_state.coverage', 'to': resolution['coverage']},
                {'path': 'claim_state.workflow_state', 'to': resolution['workflow_state']},
            ],
            'customer_update': {
                'summary': resolution['customer_update'],
                'responsible_party': 'claims_professional',
                'related_refs': [handoff['handoff_id']],
            },
        },
    )
    assert resolved_response.status_code == 200, resolved_response.text
    resolved = resolved_response.json()
    assert resolved['handoff']['status'] == 'resolved'
    assert resolved['staff_action']['action_type'] == 'professional_review'
    assert resolved['staff_action']['status'] == 'completed'

    final_customer = client.get(f'/api/v1/claims/{claim_id}', headers=claimant).json()
    assert final_customer['claim_id'] == claim_id
    assert final_customer['customer_next_step']['summary'] == resolution['customer_update']
    assert final_customer['handoff'] is None
    final_internal = repository.get_claim(claim_id, 'cus_demo')
    assert final_internal is not None
    assert final_internal.claim_state.coverage.value == resolution['coverage']
    assert final_internal.claim_state.workflow_state.value == resolution['workflow_state']
    assert final_internal.claim_state.next_action.value == 'PROCEED'
    assert final_internal.form['authorities.police_report_reference'].status.value == (
        'pending_generation'
    )


def test_unrelated_claim_does_not_enter_the_rear_end_fixture_path(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': 'pres02-unrelated-claim',
        },
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()

    response = _message(
        client,
        created['claim']['claim_id'],
        created['session']['session_id'],
        created['claim']['revision'],
        'My car was stolen from outside my home.',
        99,
    )

    assert response['decision']['action'] == 'ASK'
    assert response['decision']['customer_next_step']['status'] == 'more_information_needed'
    assert repository.list_retrieval_records(created['claim']['claim_id'], 'cus_demo') == []
