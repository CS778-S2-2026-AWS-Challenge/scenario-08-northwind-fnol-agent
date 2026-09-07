from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.runtime_configuration import RuntimeConfigurationResolutionError


def test_legacy_and_versioned_liveness_routes(client: TestClient) -> None:
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/health/live').json() == {'status': 'ok'}


def test_readiness_reports_every_dependency_honestly(client: TestClient) -> None:
    response = client.get('/health/ready')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'degraded'

    # Each adapter reports what is actually wired. A fixture running under the
    # production contract says so; it never claims to be the real provider.
    assert payload['checks']['claims_service'] == 'using_fixture'
    assert payload['checks']['policy'] == 'using_fixture'
    assert payload['checks']['claim_history'] == 'using_fixture'
    assert payload['checks']['handoff_dispatch'] == 'using_fixture'
    assert payload['checks']['evidence_storage'] == 'using_fixture'
    assert payload['checks']['knowledge_documents'] == 'using_fixture'
    assert payload['checks']['knowledge_retrieval'] == 'using_fixture'

    # Every unconfirmed AWS capability stays visible as its own check, so a
    # working fixture can never be mistaken for confirmed AWS access.
    assert payload['checks']['aws_claims_service'] == 'pending_confirmation'
    assert payload['checks']['aws_policy_history'] == 'pending_confirmation'
    assert payload['checks']['aws_evidence_storage'] == 'pending_confirmation'

    # Readiness identifies the adapter class without exposing deployment configuration.
    assert payload['checks']['persistence'] == 'using_fixture'
    assert payload['checks']['data_runtime_profile'] == 'fixture'
    assert payload['checks']['object_storage_adapter'] == 'fixture'
    assert payload['checks']['agent'] == 'not_configured'
    assert payload['checks']['control_plane_release_set'] == 'none'
    assert payload['checks']['control_plane_domains'] == 'none'

    assert datetime.fromisoformat(payload['checked_at'])


def test_readiness_reports_unavailable_when_active_release_cannot_be_resolved(
    client: TestClient,
    app: FastAPI,
) -> None:
    class FailingResolver:
        def snapshot(self) -> None:
            raise RuntimeConfigurationResolutionError('Synthetic release resolution failure.')

    app.state.runtime_configuration_resolver = FailingResolver()

    response = client.get('/health/ready')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'unavailable'
    assert payload['checks']['control_plane_release_set'] == 'unavailable'
    assert payload['checks']['control_plane_domains'] == 'unavailable'


def test_readiness_reports_unconfigured_release_resolver(
    client: TestClient,
    app: FastAPI,
) -> None:
    app.state.runtime_configuration_resolver = None

    response = client.get('/health/ready')

    assert response.status_code == 200
    payload = response.json()
    assert payload['checks']['control_plane_release_set'] == 'not_configured'
    assert payload['checks']['control_plane_domains'] == 'not_configured'
