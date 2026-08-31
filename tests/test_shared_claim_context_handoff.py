from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository


def test_evidence_handoff_and_next_action_share_one_claim_context(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'shared-context-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']

    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'shared-context-evidence',
            'If-Match': '1',
        },
        json={
            'kind': 'police_report',
            'status': 'pending_generation',
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
            'claimant_note': 'The synthetic police report is not available yet.',
        },
    )
    assert registered.status_code == 201
    evidence = registered.json()['evidence']
    evidence_id = evidence['evidence_id']
    evidence_revision = registered.json()['revision']

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'shared-context-support',
            'If-Match': str(evidence_revision),
        },
        json={
            'reason': 'I want a person to continue with this report.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        },
    )
    assert support.status_code == 201
    support_payload = support.json()

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert len(handoffs) == 1
    handoff = handoffs[0]

    assert stored_claim.revision == support_payload['revision']
    assert stored_claim.claim_state.next_action.value == 'HANDOFF'
    assert stored_claim.customer_next_step.model_dump(mode='json') == support_payload[
        'customer_next_step'
    ]
    assert handoff.handoff_id == support_payload['handoff']['handoff_id']
    assert handoff.packet.evidence_refs == [evidence_id]
    assert [item.evidence_id for item in handoff.packet.evidence] == [evidence_id]
    assert evidence_id in handoff.packet.pending_items
    assert handoff.packet.promised_next_step == support_payload['customer_next_step']['summary']

    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert workbench.status_code == 200
    detail = workbench.json()
    assert detail['claim_id'] == claim_id
    assert detail['revision'] == stored_claim.revision
    assert detail['claim_state']['next_action'] == 'HANDOFF'
    assert detail['customer_next_step'] == support_payload['customer_next_step']
    assert [item['evidence_id'] for item in detail['evidence']] == [evidence_id]
    assert [item['handoff_id'] for item in detail['handoffs']] == [handoff.handoff_id]
    packet = detail['handoffs'][0]['packet']
    assert packet['evidence_refs'] == [evidence_id]
    assert [item['evidence_id'] for item in packet['evidence']] == [evidence_id]
    assert evidence_id in packet['pending_items']

    claimant_evidence = client.get(
        f'/api/v1/claims/{claim_id}/evidence',
        headers=auth_headers,
    )
    assert claimant_evidence.status_code == 200
    assert claimant_evidence.json()['items'] == [evidence]
    assert 'provenance' not in claimant_evidence.json()['items'][0]
    assert 'packet' not in support_payload['handoff']
