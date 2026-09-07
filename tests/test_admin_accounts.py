from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _headers(key: str | None = None, revision: int | None = None) -> dict[str, str]:
    headers = {'Authorization': 'Bearer synthetic-admin'}
    if key is not None:
        headers['Idempotency-Key'] = key
    if revision is not None:
        headers['If-Match'] = f'"{revision}"'
    return headers


def test_admin_can_read_and_update_customer_account_through_identity_repository() -> None:
    with _client() as client:
        customers = client.get('/internal/v1/admin/accounts/customers', headers=_headers())
        assert customers.status_code == 200
        customer = next(
            item for item in customers.json()['items'] if item['customer_id'] == 'cus_demo'
        )
        assert customer['active'] is True
        assert customer['allowed_actions'] == [
            {
                'action_code': 'admin.customer_account.update',
                'availability': 'available',
                'expected_revision': 1,
                'reason': None,
            }
        ]

        updated = client.patch(
            '/internal/v1/admin/accounts/customers/cus_demo',
            headers=_headers('customer-update', 1),
            json={'display_name': 'Updated Demo', 'active': False},
        )
        assert updated.status_code == 200
        assert updated.json()['display_name'] == 'Updated Demo'
        assert updated.json()['active'] is False
        assert updated.json()['revision'] == 2

        audit = client.get(
            '/internal/v1/admin/accounts/customers/cus_demo/audit', headers=_headers()
        )
        assert audit.status_code == 200
        assert audit.json()['items'][-1]['subject']['subject_id'] == 'cus_demo'
        assert audit.json()['items'][-1]['outcome'] == 'succeeded'

        denied = client.post(
            '/api/v1/auth/sessions',
            json={'email': 'claimant.one@example.invalid', 'password': 'northwind-demo-one'},
        )
        assert denied.status_code == 401


def test_admin_account_lists_are_paginated_and_protected() -> None:
    with _client() as client:
        denied = client.get('/internal/v1/admin/accounts/staff')
        assert denied.status_code == 401

        first = client.get('/internal/v1/admin/accounts/customers?limit=1', headers=_headers())
        assert first.status_code == 200
        assert len(first.json()['items']) == 1
        assert first.json()['page']['next_cursor'] is not None

        second = client.get(
            '/internal/v1/admin/accounts/customers',
            headers=_headers(),
            params={'cursor': first.json()['page']['next_cursor']},
        )
        assert second.status_code == 200
        assert len(second.json()['items']) == 1


def test_admin_can_update_staff_roles_and_active_state() -> None:
    with _client() as client:
        updated = client.patch(
            '/internal/v1/admin/accounts/staff/stf_demo',
            headers=_headers('staff-update', 1),
            json={'roles': ['claims_professional', 'operations'], 'active': False},
        )
        assert updated.status_code == 200
        assert updated.json()['roles'] == ['claims_professional', 'operations']
        assert updated.json()['active'] is False
        assert updated.json()['allowed_actions'][0]['action_code'] == ('admin.staff_account.update')

        audit = client.get('/internal/v1/admin/accounts/staff/stf_demo/audit', headers=_headers())
        assert audit.status_code == 200
        assert audit.json()['items'][-1]['subject']['subject_id'] == 'staff:stf_demo'

        staff_login = client.post(
            '/api/v1/staff/auth/sessions',
            json={'email': 'staff.one@example.invalid', 'password': 'northwind-demo-staff'},
        )
        assert staff_login.status_code == 401


def test_admin_customer_creation_is_idempotent_and_session_revocation_is_safe() -> None:
    with _client() as client:
        payload = {
            'email': 'managed.claimant@example.invalid',
            'initial_password': 'managed-claimant-password',
            'display_name': 'Managed Claimant',
            'phone': '021 555 0199',
        }
        created = client.post(
            '/internal/v1/admin/accounts/customers',
            headers=_headers('create-managed-customer'),
            json=payload,
        )
        replay = client.post(
            '/internal/v1/admin/accounts/customers',
            headers=_headers('create-managed-customer'),
            json=payload,
        )
        conflict = client.post(
            '/internal/v1/admin/accounts/customers',
            headers=_headers('create-managed-customer'),
            json={**payload, 'display_name': 'Different request'},
        )
        assert created.status_code == 201, created.text
        assert replay.status_code == 201
        assert replay.json() == created.json()
        assert conflict.status_code == 409
        assert 'initial_password' not in created.json()

        login = client.post(
            '/api/v1/auth/sessions',
            json={'email': payload['email'], 'password': payload['initial_password']},
        )
        assert login.status_code == 201, login.text
        token = login.json()['access_token']
        customer_id = created.json()['customer_id']
        sessions = client.get(
            f'/internal/v1/admin/accounts/customers/{customer_id}/sessions',
            headers=_headers(),
        )
        assert sessions.status_code == 200
        session = sessions.json()['items'][0]
        assert session['state'] == 'active'
        assert 'token_hash' not in session
        assert session['allowed_actions'][0]['availability'] == 'confirmation_required'

        revoked = client.post(
            f'/internal/v1/admin/accounts/customers/{customer_id}/sessions/'
            f'{session["session_id"]}/revoke',
            headers=_headers('revoke-managed-customer-session', session['revision']),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()['state'] == 'revoked'
        assert revoked.json()['revision'] == session['revision'] + 1
        assert (
            client.get(
                '/api/v1/auth/session', headers={'Authorization': f'Bearer {token}'}
            ).status_code
            == 401
        )


def test_admin_staff_creation_update_and_session_revoke_use_revisions() -> None:
    with _client() as client:
        payload = {
            'email': 'managed.staff@example.invalid',
            'initial_password': 'managed-staff-password',
            'display_name': 'Managed Staff',
            'roles': ['claims_professional'],
        }
        created = client.post(
            '/internal/v1/admin/accounts/staff',
            headers=_headers('create-managed-staff'),
            json=payload,
        )
        assert created.status_code == 201, created.text
        staff_id = created.json()['staff_id']
        stale = client.patch(
            f'/internal/v1/admin/accounts/staff/{staff_id}',
            headers=_headers('stale-staff-update', 99),
            json={'display_name': 'Stale update'},
        )
        assert stale.status_code == 409
        assert stale.json()['error']['current_revision'] == created.json()['revision']

        login = client.post(
            '/api/v1/staff/auth/sessions',
            json={'email': payload['email'], 'password': payload['initial_password']},
        )
        assert login.status_code == 201
        sessions = client.get(
            f'/internal/v1/admin/accounts/staff/{staff_id}/sessions', headers=_headers()
        )
        session = sessions.json()['items'][0]
        revoked = client.post(
            f'/internal/v1/admin/accounts/staff/{staff_id}/sessions/{session["session_id"]}/revoke',
            headers=_headers('revoke-managed-staff-session', session['revision']),
        )
        assert revoked.status_code == 200
        assert revoked.json()['state'] == 'revoked'


def test_admin_account_boundaries_reject_missing_empty_and_stale_operations() -> None:
    with _client() as client:
        missing_customer = client.patch(
            '/internal/v1/admin/accounts/customers/cus_missing',
            headers=_headers('missing-customer-update', 1),
            json={'display_name': 'Nobody'},
        )
        assert missing_customer.status_code == 404
        assert missing_customer.json()['error']['code'] == 'ACCOUNT_NOT_FOUND'

        empty_customer = client.patch(
            '/internal/v1/admin/accounts/customers/cus_demo',
            headers=_headers('empty-customer-update', 1),
            json={},
        )
        assert empty_customer.status_code == 422
        assert empty_customer.json()['error']['code'] == 'VALIDATION_ERROR'

        empty_staff_roles = client.patch(
            '/internal/v1/admin/accounts/staff/stf_demo',
            headers=_headers('empty-staff-roles', 1),
            json={'roles': [' ', '']},
        )
        assert empty_staff_roles.status_code == 422
        assert empty_staff_roles.json()['error']['code'] == 'VALIDATION_ERROR'

        missing_sessions = client.get(
            '/internal/v1/admin/accounts/staff/stf_missing/sessions', headers=_headers()
        )
        assert missing_sessions.status_code == 404
        assert missing_sessions.json()['error']['code'] == 'ACCOUNT_NOT_FOUND'

        missing_audit = client.get(
            '/internal/v1/admin/accounts/customers/cus_missing/audit', headers=_headers()
        )
        assert missing_audit.status_code == 404


def test_admin_session_revoke_is_idempotent_and_rejects_second_revoke() -> None:
    with _client() as client:
        payload = {
            'email': 'session-boundary@example.invalid',
            'initial_password': 'session-boundary-password',
            'display_name': 'Session Boundary',
        }
        created = client.post(
            '/internal/v1/admin/accounts/customers',
            headers=_headers('session-boundary-create'),
            json=payload,
        )
        assert created.status_code == 201
        customer_id = created.json()['customer_id']
        login = client.post(
            '/api/v1/auth/sessions',
            json={'email': payload['email'], 'password': payload['initial_password']},
        )
        assert login.status_code == 201
        sessions = client.get(
            f'/internal/v1/admin/accounts/customers/{customer_id}/sessions', headers=_headers()
        )
        session = sessions.json()['items'][0]
        route = (
            f'/internal/v1/admin/accounts/customers/{customer_id}/sessions/'
            f'{session["session_id"]}/revoke'
        )
        revoked = client.post(
            route,
            headers=_headers('session-boundary-revoke', session['revision']),
        )
        assert revoked.status_code == 200
        second = client.post(
            route,
            headers=_headers('session-boundary-revoke-again', revoked.json()['revision']),
        )
        assert second.status_code == 409
        assert second.json()['error']['code'] == 'SESSION_NOT_ACTIVE'
