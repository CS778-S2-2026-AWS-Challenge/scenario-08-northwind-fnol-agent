from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    now_utc,
)
from backend.repositories.configuration import ConfigurationRepository


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _headers(key: str | None = None) -> dict[str, str]:
    result = {'Authorization': 'Bearer synthetic-admin'}
    if key is not None:
        result['Idempotency-Key'] = key
    return result


def test_access_policy_is_a_real_versioned_configuration() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/access/policies',
            headers=_headers('access-policy-1'),
            json={
                'domain': 'access',
                'impact': 'high',
                'values': {
                    'role': 'claims_reviewer',
                    'actor_type': 'staff',
                    'scopes': ['workbench:read'],
                    'visibility': ['claim_shared'],
                    'active': True,
                },
                'reason': 'Define the claims reviewer boundary.',
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()['values']['role'] == 'claims_reviewer'

        listed = client.get('/internal/v1/admin/access/policies', headers=_headers())
        assert listed.status_code == 200
        assert listed.json()['items'][0]['domain'] == 'access'

        replay = client.post(
            '/internal/v1/admin/access/policies',
            headers=_headers('access-policy-1'),
            json={
                'domain': 'access',
                'impact': 'high',
                'values': {
                    'role': 'claims_reviewer',
                    'actor_type': 'staff',
                    'scopes': ['workbench:read'],
                    'visibility': ['claim_shared'],
                    'active': True,
                },
                'reason': 'Define the claims reviewer boundary.',
            },
        )
        assert replay.status_code == 201
        assert replay.json() == created.json()


def test_access_policy_rejects_wrong_domain_and_idempotency_conflict() -> None:
    with _client() as client:
        wrong_domain = client.post(
            '/internal/v1/admin/access/policies',
            headers=_headers('wrong-domain'),
            json={
                'domain': 'model',
                'impact': 'high',
                'values': {},
                'reason': 'This must not be stored as an access policy.',
            },
        )
        assert wrong_domain.status_code == 422
        assert wrong_domain.json()['error']['code'] == 'ACCESS_POLICY_INVALID'

        payload = {
            'domain': 'access',
            'impact': 'high',
            'values': {
                'role': 'claims_reviewer',
                'actor_type': 'staff',
                'scopes': ['workbench:read'],
                'visibility': ['claim_shared'],
                'active': True,
            },
            'reason': 'Create the first version.',
        }
        created = client.post(
            '/internal/v1/admin/access/policies',
            headers=_headers('access-conflict'),
            json=payload,
        )
        conflict = client.post(
            '/internal/v1/admin/access/policies',
            headers=_headers('access-conflict'),
            json={**payload, 'reason': 'Attempt a conflicting reuse.'},
        )

        assert created.status_code == 201, created.text
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_admin_audit_search_is_filtered_and_protected() -> None:
    with _client() as client:
        denied = client.get('/internal/v1/admin/audit')
        assert denied.status_code == 401

        updated = client.patch(
            '/internal/v1/admin/accounts/customers/cus_demo',
            headers={
                **_headers('audit-customer-update'),
                'If-Match': '"1"',
            },
            json={'display_name': 'Audited Demo Customer'},
        )
        assert updated.status_code == 200, updated.text

        response = client.get(
            '/internal/v1/admin/audit',
            headers=_headers(),
            params={'subject_type': 'customer', 'limit': 10},
        )
        assert response.status_code == 200
        assert response.json()['items']
        assert all(
            item['subject']['subject_type'] == 'customer' for item in response.json()['items']
        )


def test_published_access_policy_can_only_restrict_existing_staff_scope() -> None:
    repository = ConfigurationRepository()
    repository.create(
        ConfigurationRecord(
            configuration_id='cfg_access_staff',
            domain='access',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            values={
                'role': 'claims_reviewer',
                'actor_type': 'staff',
                'scopes': ['workbench:read'],
                'visibility': ['claim_shared'],
                'active': True,
            },
            author='adm_demo',
            reason='Restrict the demo staff account to read-only workbench access.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )
    with TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            configuration_repository=repository,
        )
    ) as client:
        response = client.post(
            '/api/v1/workbench/claims/clm_missing/messages',
            headers={
                'Authorization': 'Bearer synthetic-staff',
                'Idempotency-Key': 'restricted-staff-message',
                'If-Match': '1',
            },
            json={
                'content': {
                    'type': 'text',
                    'text': 'A staff message should be blocked by the published policy.',
                }
            },
        )
        assert response.status_code == 403
