import json
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / 'fixtures' / 'connectivity-message.json'


def test_temporary_message_endpoint_accepts_fixture(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    request_body = json.loads(FIXTURE.read_text(encoding='utf-8'))

    response = client.post('/api/claims/message', headers=auth_headers, json=request_body)

    assert response.status_code == 200
    assert response.json() == {
        'reply': 'I received your claim.',
        'received_message': request_body['message'],
    }


def test_temporary_message_endpoint_rejects_empty_content(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        '/api/claims/message',
        headers=auth_headers,
        json={'message': '   '},
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
