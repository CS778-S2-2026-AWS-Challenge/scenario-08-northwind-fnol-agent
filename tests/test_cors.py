from fastapi.testclient import TestClient


def test_development_cors_allows_any_origin(client: TestClient) -> None:
    response = client.options(
        '/api/claims/message',
        headers={
            'Origin': 'http://developer-host.example',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type,x-request-id',
        },
    )

    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == '*'
    assert 'access-control-allow-credentials' not in response.headers


def test_cors_exposes_request_id(client: TestClient) -> None:
    response = client.get(
        '/health/live',
        headers={'Origin': 'http://developer-host.example'},
    )

    assert response.headers['access-control-allow-origin'] == '*'
    assert response.headers['access-control-expose-headers'] == 'X-Request-ID'
