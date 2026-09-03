from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment='test',
                identity_mode=IdentityMode.NORMAL,
                identity_db_path=str(tmp_path / 'claimant.sqlite3'),
                staff_identity_db_path=str(tmp_path / 'staff.sqlite3'),
                staff_bootstrap_email='claims@example.test',
                staff_bootstrap_password='strong-staff-password',
                staff_bootstrap_display_name='Alex Claims',
            )
        )
    )


def test_staff_login_uses_an_independent_persistent_identity_boundary(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post(
            '/api/v1/staff/auth/sessions',
            json={'email': 'claims@example.test', 'password': 'strong-staff-password'},
        )

        assert login.status_code == 201
        payload = login.json()
        assert payload['staff_id'].startswith('stf_')
        assert payload['development_identity'] is False
        headers = {'Authorization': f'Bearer {payload["access_token"]}'}

        session = client.get('/api/v1/staff/auth/session', headers=headers)
        profile = client.get('/api/v1/staff/me', headers=headers)
        queue = client.get('/api/v1/workbench/claims', headers=headers)

        assert session.status_code == 200
        assert session.json()['staff_id'] == payload['staff_id']
        assert profile.status_code == 200
        assert profile.json() == {
            'staff_id': payload['staff_id'],
            'display_name': 'Alex Claims',
            'email': 'claims@example.test',
            'roles': ['claims_professional'],
            'development_identity': False,
        }
        assert queue.status_code == 200

        claimant_boundary = client.get('/api/v1/auth/session', headers=headers)
        assert claimant_boundary.status_code == 403

        logout = client.delete('/api/v1/staff/auth/session', headers=headers)
        assert logout.status_code == 204
        assert client.get('/api/v1/workbench/claims', headers=headers).status_code == 401


def test_staff_login_rejects_unknown_credentials(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            '/api/v1/staff/auth/sessions',
            json={'email': 'claims@example.test', 'password': 'incorrect-password'},
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
