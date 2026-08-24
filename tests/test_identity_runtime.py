from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.auth import Principal, require_administrator, require_claimant
from backend.core.config import IdentityMode, Settings


def _bearer(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def _identity_app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get('/__identity_test/claimant')
    def claimant_identity(
        principal: Annotated[Principal, Depends(require_claimant)],
    ) -> dict[str, object]:
        return {
            'subject': principal.subject,
            'actor_type': principal.actor_type,
            'scopes': sorted(principal.scopes),
            'auth_source': principal.auth_source,
            'synthetic': principal.synthetic,
        }

    @app.get('/__identity_test/administrator')
    def administrator_identity(
        principal: Annotated[Principal, Depends(require_administrator)],
    ) -> dict[str, object]:
        return {
            'subject': principal.subject,
            'actor_type': principal.actor_type,
            'scopes': sorted(principal.scopes),
            'auth_source': principal.auth_source,
            'synthetic': principal.synthetic,
        }

    return app


def test_developer_profile_metadata_is_server_derived_and_audit_capable() -> None:
    app = _identity_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))

    with TestClient(app) as client:
        response = client.get(
            '/__identity_test/claimant?actor_type=administrator&scope=admin:write',
            headers={
                **_bearer('synthetic-claimant'),
                'X-Role': 'administrator',
                'X-User': 'adm_forged',
                'X-Scope': 'admin:write',
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        'subject': 'cus_demo',
        'actor_type': 'claimant',
        'scopes': ['claim:read:self', 'claim:write:self'],
        'auth_source': 'developer:synthetic_claimant',
        'synthetic': True,
    }


def test_administrator_profile_is_distinct_without_creating_an_admin_api() -> None:
    app = _identity_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))

    with TestClient(app) as client:
        administrator = client.get(
            '/__identity_test/administrator',
            headers=_bearer('synthetic-admin'),
        )
        claimant = client.get(
            '/__identity_test/administrator',
            headers=_bearer('synthetic-claimant'),
        )
        unknown = client.get(
            '/__identity_test/administrator',
            headers=_bearer('not-registered'),
        )

    assert administrator.status_code == 200
    assert administrator.json() == {
        'subject': 'adm_demo',
        'actor_type': 'administrator',
        'scopes': ['admin:read', 'admin:write'],
        'auth_source': 'developer:synthetic_admin',
        'synthetic': True,
    }
    assert claimant.status_code == 403
    assert claimant.json()['error']['code'] == 'ACCESS_DENIED'
    assert unknown.status_code == 401
    assert unknown.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
    assert 'not-registered' not in unknown.text


def test_normal_mode_does_not_accept_repository_synthetic_profiles() -> None:
    app = _identity_app(Settings(environment='development'))

    with TestClient(app) as client:
        claimant = client.get(
            '/__identity_test/claimant',
            headers=_bearer('synthetic-claimant'),
        )
        administrator = client.get(
            '/__identity_test/administrator',
            headers=_bearer('synthetic-admin'),
        )

    for response in (claimant, administrator):
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_no_synthetic_agent_service_profile_is_registered() -> None:
    app = _identity_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))

    with TestClient(app) as client:
        response = client.get(
            '/__identity_test/claimant',
            headers=_bearer('synthetic-agent'),
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
