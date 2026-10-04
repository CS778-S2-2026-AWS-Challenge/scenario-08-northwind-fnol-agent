from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.services.staff_seed import load_staff_seed


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment='test',
                identity_mode=IdentityMode.NORMAL,
                identity_db_path=str(tmp_path / 'claimant.sqlite3'),
                staff_identity_db_path=str(tmp_path / 'staff.sqlite3'),
                staff_seed_password='strong-staff-password',
            )
        )
    )


def test_staff_login_uses_an_independent_persistent_identity_boundary(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post(
            '/api/v1/staff/auth/sessions',
            json={'email': 'claims.one@northwind.test', 'password': 'strong-staff-password'},
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
            'display_name': 'Claims Professional One',
            'email': 'claims.one@northwind.test',
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
            json={'email': 'claims.one@northwind.test', 'password': 'incorrect-password'},
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_every_start_prints_each_seeded_account_with_its_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _client(tmp_path):
        pass

    banner = capsys.readouterr().out
    for account in load_staff_seed('config/staff-seed.json'):
        assert account.email in banner
    assert 'password: strong-staff-password' in banner


def test_normal_identity_refuses_to_start_without_the_seed_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
    monkeypatch.setenv('NORTHWIND_IDENTITY_MODE', 'normal')
    monkeypatch.setenv('DATA_RUNTIME_PROFILE', 'fixture')
    monkeypatch.delenv('NORTHWIND_STAFF_SEED_PASSWORD', raising=False)

    with pytest.raises(ValueError, match='NORTHWIND_STAFF_SEED_PASSWORD is required'):
        create_app()
