from collections.abc import Callable

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.auth import (
    require_claimant,
    require_claimant_session,
    require_integration_service,
    require_staff,
)
from backend.core.config import Settings


def _bearer(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def _assert_error(response_status: int, response_body: dict[str, object], code: str) -> None:
    assert response_status == (403 if code == 'ACCESS_DENIED' else 401)
    error = response_body['error']
    assert isinstance(error, dict)
    assert error['code'] == code


def test_non_health_routes_declare_the_expected_authentication_boundary(app: FastAPI) -> None:
    expected_dependencies: dict[str, Callable[..., object]] = {
        '/api/claims/message': require_claimant,
    }
    health_paths = {'/health', '/health/live', '/health/ready'}
    public_paths = {'/api/v1/auth/sessions'}

    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in health_paths:
            continue

        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        if route.path in public_paths:
            assert not dependency_calls, f'Public route {route.path} unexpectedly requires auth.'
            continue

        expected: Callable[..., object] | None
        if route.path.startswith('/api/v1/workbench/'):
            expected = require_staff
        elif route.path.startswith(('/api/v1/auth/', '/api/v1/account')):
            expected = require_claimant_session
        elif route.path.startswith('/api/v1/claims'):
            expected = require_claimant
        elif route.path.startswith('/internal/v1/'):
            expected = require_integration_service
        else:
            expected = expected_dependencies.get(route.path)

        assert expected is not None, f'Route {route.path} has no classified permission boundary.'
        assert expected in dependency_calls, f'Route {route.path} is missing {expected.__name__}.'


def test_claimant_routes_reject_other_registered_actor_credentials(client: TestClient) -> None:
    allowed = client.get('/api/v1/claims/clm_missing', headers=_bearer('synthetic-claimant'))
    staff = client.get('/api/v1/claims/clm_missing', headers=_bearer('synthetic-staff'))
    administrator = client.get('/api/v1/claims/clm_missing', headers=_bearer('synthetic-admin'))
    integration = client.get(
        '/api/v1/claims/clm_missing',
        headers=_bearer('synthetic-integration'),
    )
    unknown = client.get('/api/v1/claims/clm_missing', headers=_bearer('unknown'))

    assert allowed.status_code == 404
    for response in (staff, administrator, integration):
        _assert_error(response.status_code, response.json(), 'ACCESS_DENIED')
    _assert_error(unknown.status_code, unknown.json(), 'AUTHENTICATION_REQUIRED')


def test_staff_routes_reject_other_registered_actor_credentials(client: TestClient) -> None:
    allowed = client.get('/api/v1/workbench/claims/clm_missing', headers=_bearer('synthetic-staff'))
    claimant = client.get(
        '/api/v1/workbench/claims/clm_missing',
        headers=_bearer('synthetic-claimant'),
    )
    administrator = client.get(
        '/api/v1/workbench/claims/clm_missing',
        headers=_bearer('synthetic-admin'),
    )
    integration = client.get(
        '/api/v1/workbench/claims/clm_missing',
        headers=_bearer('synthetic-integration'),
    )
    unknown = client.get('/api/v1/workbench/claims/clm_missing', headers=_bearer('unknown'))

    assert allowed.status_code == 404
    for response in (claimant, administrator, integration):
        _assert_error(response.status_code, response.json(), 'ACCESS_DENIED')
    _assert_error(unknown.status_code, unknown.json(), 'AUTHENTICATION_REQUIRED')


def test_integration_routes_reject_other_registered_actor_credentials(client: TestClient) -> None:
    payload = {
        'working_claim_id': 'clm_missing',
        'claim_revision': 1,
        'authorised_decision_id': 'dec_missing',
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': 'standard_motor_intake',
    }
    allowed = client.post(
        '/internal/v1/claims/create',
        headers=_bearer('synthetic-integration'),
        json=payload,
    )
    claimant = client.post(
        '/internal/v1/claims/create',
        headers=_bearer('synthetic-claimant'),
        json=payload,
    )
    staff = client.post(
        '/internal/v1/claims/create',
        headers=_bearer('synthetic-staff'),
        json=payload,
    )
    administrator = client.post(
        '/internal/v1/claims/create',
        headers=_bearer('synthetic-admin'),
        json=payload,
    )
    unknown = client.post(
        '/internal/v1/claims/create',
        headers=_bearer('unknown'),
        json=payload,
    )

    assert allowed.status_code == 404
    for response in (claimant, staff, administrator):
        _assert_error(response.status_code, response.json(), 'ACCESS_DENIED')
    _assert_error(unknown.status_code, unknown.json(), 'AUTHENTICATION_REQUIRED')


def test_deprecated_claimant_route_is_not_an_authentication_bypass(client: TestClient) -> None:
    payload = {'message': 'A synthetic connectivity check.'}
    allowed = client.post(
        '/api/claims/message',
        headers=_bearer('synthetic-claimant'),
        json=payload,
    )
    missing = client.post('/api/claims/message', json=payload)
    staff = client.post(
        '/api/claims/message',
        headers=_bearer('synthetic-staff'),
        json=payload,
    )
    administrator = client.post(
        '/api/claims/message',
        headers=_bearer('synthetic-admin'),
        json=payload,
    )
    integration = client.post(
        '/api/claims/message',
        headers=_bearer('synthetic-integration'),
        json=payload,
    )

    assert allowed.status_code == 200
    _assert_error(missing.status_code, missing.json(), 'AUTHENTICATION_REQUIRED')
    for response in (staff, administrator, integration):
        _assert_error(response.status_code, response.json(), 'ACCESS_DENIED')


def test_normal_mode_rejects_synthetic_credentials_even_in_development() -> None:
    app = create_app(Settings(environment='development'))
    integration_payload = {
        'working_claim_id': 'clm_missing',
        'claim_revision': 1,
        'authorised_decision_id': 'dec_missing',
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': 'standard_motor_intake',
    }

    with TestClient(app) as client:
        claimant = client.get(
            '/api/v1/claims/clm_missing',
            headers=_bearer('synthetic-claimant'),
        )
        staff = client.get(
            '/api/v1/workbench/claims/clm_missing',
            headers=_bearer('synthetic-staff'),
        )
        integration = client.post(
            '/internal/v1/claims/create',
            headers=_bearer('synthetic-integration'),
            json=integration_payload,
        )

    for response in (claimant, staff, integration):
        _assert_error(response.status_code, response.json(), 'AUTHENTICATION_REQUIRED')


def test_synthetic_credentials_are_disabled_in_production_normal_mode() -> None:
    app = create_app(Settings(environment='production'))
    integration_payload = {
        'working_claim_id': 'clm_missing',
        'claim_revision': 1,
        'authorised_decision_id': 'dec_missing',
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': 'standard_motor_intake',
    }

    with TestClient(app) as client:
        claimant = client.get(
            '/api/v1/claims/clm_missing',
            headers=_bearer('synthetic-claimant'),
        )
        staff = client.get(
            '/api/v1/workbench/claims/clm_missing',
            headers=_bearer('synthetic-staff'),
        )
        integration = client.post(
            '/internal/v1/claims/create',
            headers=_bearer('synthetic-integration'),
            json=integration_payload,
        )

    for response in (claimant, staff, integration):
        _assert_error(response.status_code, response.json(), 'AUTHENTICATION_REQUIRED')


def test_claimant_validation_rejects_internal_and_storage_fields_without_echoing_values(
    client: TestClient,
) -> None:
    response = client.post(
        '/api/v1/claims',
        headers={
            **_bearer('synthetic-claimant'),
            'Idempotency-Key': 'boundary-validation',
        },
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'dynamodb_table_name': 'private-claims-table',
            'internal_signal': 'history_review_required',
        },
    )

    assert response.status_code == 422
    error = response.json()['error']
    assert error['code'] == 'VALIDATION_ERROR'
    assert {detail['field'] for detail in error['details']} == {
        'body.dynamodb_table_name',
        'body.internal_signal',
    }
    assert 'private-claims-table' not in response.text
    assert 'history_review_required' not in response.text
