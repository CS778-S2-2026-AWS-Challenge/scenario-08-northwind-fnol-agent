from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository


def test_cross_claim_staff_reply_rejection_is_atomic(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    primary = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'cross-claim-primary'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert primary.status_code == 201
    claim_id = primary.json()['claim']['claim_id']
    session_id = primary.json()['session']['session_id']

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'cross-claim-support',
            'If-Match': '1',
        },
        json={
            'reason': 'I want a person to help me continue.',
            'support_need': 'human_requested',
        },
    )
    assert support.status_code == 201
    handoff_id = support.json()['handoff']['handoff_id']

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'cross-claim-accept',
            'If-Match': '2',
        },
        json={},
    )
    assert accepted.status_code == 200
    assert accepted.json()['revision'] == 3

    other_claim = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'cross-claim-other'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert other_claim.status_code == 201
    other_claim_id = other_claim.json()['claim']['claim_id']
    other_session_id = other_claim.json()['session']['session_id']

    other_turn = client.post(
        f'/api/v1/claims/{other_claim_id}/sessions/{other_session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'cross-claim-other-message',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'cross-claim-other-message',
            'content': {'type': 'text', 'text': 'This message belongs to another claim.'},
            'evidence_refs': [],
        },
    )
    assert other_turn.status_code == 200
    other_message_id = other_turn.json()['claimant_message']['message_id']

    claim_before = repository.get_claim_internal(claim_id)
    assert claim_before is not None
    messages_before = repository.list_messages(claim_id, session_id, claim_before.customer_id)
    handoffs_before = repository.list_handoffs(claim_id, claim_before.customer_id)
    route = f'/api/v1/workbench/claims/{claim_id}/messages'
    key = 'cross-claim-rejected-staff-message'

    rejected = client.post(
        route,
        headers={
            **staff_auth_headers,
            'Idempotency-Key': key,
            'If-Match': '3',
        },
        json={
            'content': {'type': 'text', 'text': 'This reply must be rejected.'},
            'in_reply_to': other_message_id,
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()['error']['code'] == 'VALIDATION_ERROR'
    claim_after = repository.get_claim_internal(claim_id)
    messages_after = repository.list_messages(claim_id, session_id, claim_before.customer_id)
    handoffs_after = repository.list_handoffs(claim_id, claim_before.customer_id)
    idempotency_after = repository.find_idempotency('stf_demo', route, key)
    assert claim_after == claim_before
    assert messages_after == messages_before
    assert handoffs_after == handoffs_before
    assert idempotency_after is None
