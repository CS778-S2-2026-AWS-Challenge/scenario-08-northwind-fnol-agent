from datetime import datetime

from fastapi.testclient import TestClient


def test_legacy_and_versioned_liveness_routes(client: TestClient) -> None:
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/health/live').json() == {'status': 'ok'}


def test_readiness_reports_unconfigured_dependencies_honestly(client: TestClient) -> None:
    response = client.get('/health/ready')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'degraded'
    assert payload['checks']['claims_service'] == 'using_fixture'
    assert payload['checks']['aws_claims_service'] == 'pending_confirmation'
    assert {
        value
        for name, value in payload['checks'].items()
        if name not in {'claims_service', 'aws_claims_service'}
    } == {'not_configured'}
    assert datetime.fromisoformat(payload['checked_at'])
