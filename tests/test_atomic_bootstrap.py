from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository


def test_initial_bootstrap_persists_claim_and_turn_once(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    payload = {
        'incident_type': 'motor',
        'client_message_id': 'bootstrap-message-1',
        'content': {'type': 'text', 'text': 'A parked car was damaged overnight.'},
    }
    headers = {**auth_headers, 'Idempotency-Key': 'bootstrap-operation-1'}

    first = client.post('/api/v1/claims/bootstrap', headers=headers, json=payload)
    replay = client.post('/api/v1/claims/bootstrap', headers=headers, json=payload)

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    body = first.json()
    claim_id = body['claim_id']
    session_id = body['session_id']
    assert repository.get_claim(claim_id, 'cus_demo') is not None
    assert repository.get_session(claim_id, session_id, 'cus_demo') is not None
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert len(messages) == 2
    assert messages[0].client_message_id == 'bootstrap-message-1'
