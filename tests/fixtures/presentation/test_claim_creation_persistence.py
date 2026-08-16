from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository


def test_claim_creation_retry_does_not_duplicate_or_roll_back_newer_state(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    create_headers = {**auth_headers, 'Idempotency-Key': 'day5-create-retry'}
    payload = {'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'}

    created = client.post('/api/v1/claims', headers=create_headers, json=payload)
    replay_before_change = client.post('/api/v1/claims', headers=create_headers, json=payload)

    assert created.status_code == 201
    assert replay_before_change.status_code == 201
    assert replay_before_change.json() == created.json()

    created_body = created.json()
    claim_id = created_body['claim']['claim_id']
    session_id = created_body['session']['session_id']
    assert isinstance(claim_id, str)
    assert isinstance(session_id, str)
    assert created_body['claim']['revision'] == 1
    assert repository.claim_count == 1
    assert len(repository.list_sessions_for_claim(claim_id, 'cus_demo')) == 1

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'day5-create-retry-turn',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'day5-create-retry-turn',
            'content': {
                'type': 'text',
                'text': 'My parked car was hit from behind this morning and nobody was injured.',
            },
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200
    assert turn.json()['claim_revision'] == 2

    stored_after_turn = repository.get_claim(claim_id, 'cus_demo')
    assert stored_after_turn is not None
    assert stored_after_turn.revision == 2
    assert stored_after_turn.active_session_id == session_id

    replay_after_change = client.post('/api/v1/claims', headers=create_headers, json=payload)
    assert replay_after_change.status_code == 201
    replay_body = replay_after_change.json()
    persisted_payload = stored_after_turn.model_dump(mode='json')
    assert replay_body['claim']['claim_id'] == claim_id
    assert replay_body['claim']['revision'] == 2
    assert replay_body['session']['session_id'] == session_id
    assert replay_body['claim']['form'] == persisted_payload['form']
    assert replay_body['claim']['customer_next_step'] == persisted_payload['customer_next_step']

    stored_after_replay = repository.get_claim(claim_id, 'cus_demo')
    assert stored_after_replay is not None
    assert stored_after_replay.revision == 2
    assert stored_after_replay.active_session_id == session_id
    assert repository.claim_count == 1
    sessions = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    assert len(sessions) == 1
    assert sessions[0].session_id == session_id

    conflicting_reuse = client.post(
        '/api/v1/claims',
        headers=create_headers,
        json={**payload, 'incident_type': 'property'},
    )
    assert conflicting_reuse.status_code == 409
    assert conflicting_reuse.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_claim.revision == 2
    assert repository.claim_count == 1
