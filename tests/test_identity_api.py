from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi.testclient import TestClient

from backend.adapters.identity import FixtureIdentityRepository
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.domain.identity import ClaimantAuthSessionRecord


def login(client: TestClient, email: str, password: str) -> dict[str, object]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_login_account_update_and_logout_are_server_authenticated(client: TestClient) -> None:
    session = login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    headers = {'Authorization': f'Bearer {session["access_token"]}'}

    current = client.get('/api/v1/auth/session', headers=headers)
    account = client.get('/api/v1/account', headers=headers)
    profile = client.patch(
        '/api/v1/account/profile',
        headers=headers,
        json={'display_name': 'Updated Demo Claimant', 'phone': '020 000 0000'},
    )
    preferences = client.patch(
        '/api/v1/account/preferences',
        headers=headers,
        json={'email': False, 'sms': True},
    )
    logout = client.delete('/api/v1/auth/session', headers=headers)
    after_logout = client.get('/api/v1/account', headers=headers)

    assert current.status_code == 200
    assert current.json()['customer_id'] == 'cus_demo'
    assert account.json()['development_identity'] is True
    assert account.json()['profile']['email'].endswith('.invalid')
    assert profile.json()['profile']['display_name'] == 'Updated Demo Claimant'
    assert preferences.json()['preferences'] == {'email': False, 'sms': True}
    assert logout.status_code == 204
    assert after_logout.status_code == 401


def test_login_rejects_invalid_credentials_without_revealing_account(client: TestClient) -> None:
    response = client.post(
        '/api/v1/auth/sessions',
        json={'email': 'claimant.one@example.invalid', 'password': 'wrong-password'},
    )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
    assert 'email or password' in response.json()['error']['message']


def test_registration_creates_authenticated_account_and_rejects_duplicate_email(
    client: TestClient,
) -> None:
    payload = {
        'email': 'new.claimant@example.invalid',
        'password': 'a-strong-test-password',
        'display_name': 'New Claimant',
    }
    created = client.post('/api/v1/auth/accounts', json=payload)
    duplicate = client.post('/api/v1/auth/accounts', json=payload)

    assert created.status_code == 201
    assert created.json()['customer_id'].startswith('cus_')
    assert created.json()['development_identity'] is True
    assert duplicate.status_code == 409
    assert duplicate.json()['error']['code'] == 'RESOURCE_CONFLICT'


def test_claim_capabilities_are_available_to_authenticated_claimants(client: TestClient) -> None:
    session = login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    response = client.get(
        '/api/v1/claims/capabilities',
        headers={'Authorization': f'Bearer {session["access_token"]}'},
    )

    assert response.status_code == 200
    assert response.json()['claim_types'] == ['motor', 'home', 'contents']
    assert response.json()['models'] == []


def test_claim_capabilities_exposes_configured_model_profile() -> None:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_identifier='gpt54-mini',
        model_protocol_adapter='openai_compatible',
        model_base_url='https://model.example.invalid',
        model_supports_structured_output=True,
        model_supports_tools=True,
    )
    with TestClient(create_app(settings)) as client:
        session = login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        response = client.get(
            '/api/v1/claims/capabilities',
            headers={'Authorization': f'Bearer {session["access_token"]}'},
        )

    assert response.json()['models'][0]['id'] == 'qwen-local'
    assert response.json()['models'][0]['label'] == 'gpt54-mini'
    assert response.json()['default_model_profile_id'] == 'qwen-local'


def test_fixed_compatibility_token_cannot_bypass_account_session_lifecycle(
    client: TestClient,
) -> None:
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    responses = (
        client.get('/api/v1/auth/session', headers=headers),
        client.delete('/api/v1/auth/session', headers=headers),
        client.get('/api/v1/account', headers=headers),
        client.patch(
            '/api/v1/account/profile',
            headers=headers,
            json={'display_name': 'Bypass attempt', 'phone': ''},
        ),
        client.patch(
            '/api/v1/account/preferences',
            headers=headers,
            json={'email': False, 'sms': True},
        ),
    )

    assert all(response.status_code == 401 for response in responses)
    assert all(
        response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED' for response in responses
    )


def test_authenticated_claimant_cannot_select_another_customer_identity(client: TestClient) -> None:
    first = login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    second = login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    first_headers = {
        'Authorization': f'Bearer {first["access_token"]}',
        'Idempotency-Key': 'first-claimant-claim',
    }
    second_headers = {'Authorization': f'Bearer {second["access_token"]}'}

    created = client.post(
        '/api/v1/claims',
        headers=first_headers,
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'customer_id': 'cus_other',
        },
    )
    assert created.status_code == 422
    # Create a valid claim and prove the second authenticated claimant sees a concealed 404.
    created = client.post(
        '/api/v1/claims',
        headers={**first_headers, 'Idempotency-Key': 'first-valid-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    claim_id = created.json()['claim']['claim_id']
    denied = client.get(f'/api/v1/claims/{claim_id}', headers=second_headers)
    assert denied.status_code == 404
    assert denied.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_expired_session_is_not_authenticated() -> None:
    identities = FixtureIdentityRepository()
    identities.save_session(
        ClaimantAuthSessionRecord(
            token_hash='expired-token-hash',
            customer_id='cus_demo',
            created_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )

    assert identities.get_session('expired-token-hash') is None


def test_synthetic_login_fails_closed_outside_development_and_test() -> None:
    with TestClient(create_app(Settings(environment='production'))) as production_client:
        response = production_client.post(
            '/api/v1/auth/sessions',
            json={'email': 'claimant.one@example.invalid', 'password': 'northwind-demo-one'},
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_synthetic_login_requires_explicit_developer_identity_mode() -> None:
    with TestClient(create_app(Settings(environment='development'))) as normal_mode_client:
        response = normal_mode_client.post(
            '/api/v1/auth/sessions',
            json={'email': 'claimant.one@example.invalid', 'password': 'northwind-demo-one'},
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
