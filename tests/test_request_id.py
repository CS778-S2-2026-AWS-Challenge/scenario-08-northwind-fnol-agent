import re

from fastapi.testclient import TestClient


def test_valid_client_request_id_is_preserved(client: TestClient) -> None:
    response = client.get('/health/live', headers={'X-Request-ID': 'client-request_123'})

    assert response.headers['X-Request-ID'] == 'client-request_123'


def test_missing_request_id_is_generated(client: TestClient) -> None:
    response = client.get('/health/live')

    assert re.fullmatch(r'req_[0-9a-f]{32}', response.headers['X-Request-ID'])


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    response = client.get('/health/live', headers={'X-Request-ID': 'invalid request id'})

    assert response.headers['X-Request-ID'] != 'invalid request id'
    assert response.headers['X-Request-ID'].startswith('req_')
