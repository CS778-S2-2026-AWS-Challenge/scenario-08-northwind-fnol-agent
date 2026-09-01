from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings


def _client() -> TestClient:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    return TestClient(create_app(settings))


def _headers(token: str = 'synthetic-admin') -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def test_admin_configuration_lifecycle_and_audit() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={
                'domain': 'agent_rule',
                'impact': 'high',
                'values': {'rule_id': 'motor-intake'},
                'secret_references': {'model_api_key': 'secret://demo/model'},
                'reason': 'Initial controlled rule.',
            },
        )
        assert created.status_code == 201
        record = created.json()
        assert record['state'] == 'draft'
        assert 'secret://demo/model' in record['secret_references'].values()
        configuration_id = record['configuration_id']

        validation = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers={**_headers(), 'If-Match': '"1"'},
            json={'scenarios': ['motor-handoff']},
        )
        assert validation.status_code == 200
        assert validation.json()['state'] == 'awaiting_approval'

        published = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            headers={**_headers(), 'If-Match': '"2"'},
            json={'reason': 'Approved after scenario validation.'},
        )
        assert published.status_code == 200
        assert published.json()['state'] == 'published'

        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit',
            headers=_headers(),
        )
        assert audits.status_code == 200
        assert [item['action'] for item in audits.json()['items']] == [
            'create_draft',
            'validate',
            'publish',
        ]


def test_admin_boundary_and_revision_errors() -> None:
    with _client() as client:
        denied = client.get(
            '/internal/v1/admin/configurations',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        assert denied.status_code == 403

        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={'domain': 'feature', 'values': {'enabled': True}, 'reason': 'Demo flag.'},
        )
        configuration_id = created.json()['configuration_id']
        stale = client.patch(
            f'/internal/v1/admin/configurations/{configuration_id}',
            headers={**_headers(), 'If-Match': '"99"'},
            json={'values': {'enabled': False}, 'reason': 'Stale update.'},
        )
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'REVISION_CONFLICT'


def test_plaintext_secret_is_rejected() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={
                'domain': 'model',
                'values': {'api_key': 'do-not-store'},
                'reason': 'Invalid secret attempt.',
            },
        )
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'SECRET_VALUE_FORBIDDEN'


def test_publish_supersedes_previous_and_rollback_keeps_history() -> None:
    with _client() as client:
        first = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={
                'domain': 'agent_rule',
                'impact': 'high',
                'values': {'version': 1},
                'reason': 'First rule.',
            },
        ).json()
        first_id = first['configuration_id']
        client.post(
            f'/internal/v1/admin/configurations/{first_id}/validate',
            headers={**_headers(), 'If-Match': '"1"'},
            json={'scenarios': ['motor-intake']},
        )
        client.post(
            f'/internal/v1/admin/configurations/{first_id}/publish',
            headers={**_headers(), 'If-Match': '"2"'},
            json={'reason': 'Publish first rule.'},
        )
        second = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={
                'domain': 'agent_rule',
                'impact': 'high',
                'values': {'version': 2},
                'reason': 'Second rule.',
            },
        ).json()
        second_id = second['configuration_id']
        client.post(
            f'/internal/v1/admin/configurations/{second_id}/validate',
            headers={**_headers(), 'If-Match': '"1"'},
            json={'scenarios': ['motor-intake']},
        )
        published = client.post(
            f'/internal/v1/admin/configurations/{second_id}/publish',
            headers={**_headers(), 'If-Match': '"2"'},
            json={'reason': 'Publish second rule.'},
        ).json()
        assert published['previous_version'] == first_id
        rolled_back = client.post(
            f'/internal/v1/admin/configurations/{second_id}/rollback',
            headers={**_headers(), 'If-Match': '"3"'},
            json={'reason': 'Restore first rule.', 'rollback_target': first_id},
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()['rollback_target'] == first_id
