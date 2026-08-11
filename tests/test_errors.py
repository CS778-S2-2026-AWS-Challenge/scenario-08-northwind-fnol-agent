from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import ApiError, ErrorDetail


def test_unknown_route_uses_error_contract(client: TestClient) -> None:
    response = client.get('/missing-route', headers={'X-Request-ID': 'request-404'})

    assert response.status_code == 404
    assert response.headers['X-Request-ID'] == 'request-404'
    assert response.json() == {
        'error': {
            'code': 'RESOURCE_NOT_FOUND',
            'message': 'Not Found',
            'request_id': 'request-404',
            'retryable': False,
        }
    }


def test_api_error_preserves_documented_fields(app: FastAPI) -> None:
    @app.get('/test/conflict')
    def conflict() -> None:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            details=[ErrorDetail(field='If-Match', reason='Expected 1; current revision is 2.')],
            retryable=True,
            current_revision=2,
        )

    with TestClient(app) as client:
        response = client.get('/test/conflict')

    assert response.status_code == 409
    assert response.json()['error'] == {
        'code': 'REVISION_CONFLICT',
        'message': 'The claim changed after this page was loaded.',
        'request_id': response.headers['X-Request-ID'],
        'details': [
            {'field': 'If-Match', 'reason': 'Expected 1; current revision is 2.'},
        ],
        'retryable': True,
        'current_revision': 2,
    }


def test_unexpected_error_is_bounded(app: FastAPI) -> None:
    @app.get('/test/failure')
    def failure() -> None:
        raise RuntimeError('private infrastructure detail')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test/failure')

    payload = response.json()['error']
    assert response.status_code == 500
    assert payload['code'] == 'INTERNAL_ERROR'
    assert payload['retryable'] is True
    assert 'private infrastructure detail' not in response.text
