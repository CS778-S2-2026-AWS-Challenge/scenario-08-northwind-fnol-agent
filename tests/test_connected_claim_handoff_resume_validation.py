from fastapi.testclient import TestClient

from backend.domain.models import HandoffStatus
from backend.repositories.fixture import FixtureRepository


def test_claimant_handoff_staff_reply_and_continuation_share_one_authoritative_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'd4-267-connected-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    session_id = created.json()['session']['session_id']
    assert created.json()['claim']['revision'] == 1

    claimant_turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'd4-267-initial-message',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'd4-267-initial-message',
            'content': {
                'type': 'text',
                'text': 'My parked car was hit from behind on Queen Street. Nobody was injured.',
            },
            'evidence_refs': [],
        },
    )
    assert claimant_turn.status_code == 200
    assert claimant_turn.json()['claim_revision'] == 2

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'd4-267-support',
            'If-Match': '2',
        },
        json={
            'reason': 'I want a person to help me continue.',
            'support_need': 'human_requested',
        },
    )
    assert support.status_code == 201
    assert support.json()['revision'] == 3
    handoff_id = support.json()['handoff']['handoff_id']

    queue = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    assert queue.status_code == 200
    queue_item = next(item for item in queue.json()['items'] if item['claim_id'] == claim_id)
    assert queue_item['claim_id'] == claim_id

    staff_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert staff_detail.status_code == 200
    assert staff_detail.json()['claim_id'] == claim_id
    assert staff_detail.json()['active_session_id'] == session_id
    assert staff_detail.json()['revision'] == 3
    assert staff_detail.json()['handoffs'][0]['handoff_id'] == handoff_id

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'd4-267-accept',
            'If-Match': '3',
        },
        json={},
    )
    assert accepted.status_code == 200
    assert accepted.json()['revision'] == 4
    assert accepted.json()['handoff']['status'] == 'accepted'
    assert accepted.json()['handoff']['assigned_to'] == 'stf_demo'

    staff_reply = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'd4-267-staff-reply',
            'If-Match': '4',
        },
        json={
            'content': {
                'type': 'text',
                'text': 'I have your saved report and can continue from the details already provided.',
            }
        },
    )
    assert staff_reply.status_code == 200
    assert staff_reply.json()['claim_revision'] == 5

    claimant_history = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages?limit=100',
        headers=auth_headers,
    )
    assert claimant_history.status_code == 200
    visible_messages = claimant_history.json()['items']
    staff_message = next(
        item for item in visible_messages if item['message_id'] == staff_reply.json()['message']['message_id']
    )
    assert staff_message['claim_id'] == claim_id
    assert staff_message['session_id'] == session_id
    assert staff_message['actor'] == 'staff'

    continuation = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'd4-267-continuation',
            'If-Match': '5',
        },
        json={
            'client_message_id': 'd4-267-continuation',
            'content': {
                'type': 'text',
                'text': 'Thanks. I can add the remaining details here.',
            },
            'evidence_refs': [],
        },
    )
    assert continuation.status_code == 200
    assert continuation.json()['claim_revision'] == 6
    assert continuation.json()['decision'] is None
    assert continuation.json()['agent_message'] is None

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_handoff is not None
    assert repository.claim_count == 1
    assert stored_claim.claim_id == claim_id
    assert stored_claim.active_session_id == session_id
    assert stored_claim.revision == 6
    assert stored_handoff.status is HandoffStatus.IN_PROGRESS
    assert stored_handoff.assigned_to == 'stf_demo'

    stored_messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert all(message.claim_id == claim_id for message in stored_messages)
    assert all(message.session_id == session_id for message in stored_messages)
    assert any(message.actor == 'staff' for message in stored_messages)
    assert any(message.message_id == 'd4-267-continuation' for message in stored_messages)

    final_staff_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert final_staff_detail.status_code == 200
    assert final_staff_detail.json()['claim_id'] == claim_id
    assert final_staff_detail.json()['revision'] == stored_claim.revision
    assert final_staff_detail.json()['active_session_id'] == session_id
