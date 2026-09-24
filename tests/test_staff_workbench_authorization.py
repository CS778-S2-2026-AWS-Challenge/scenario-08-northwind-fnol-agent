import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import CreateStaffMessageRequest
from backend.repositories.fixture import FixtureRepository
from backend.services.staff_actions import send_staff_message
from backend.services.workbench import get_workbench_claim_detail


def _login_operations_staff(app: FastAPI, client: TestClient) -> dict[str, str]:
    password = 'operations-test-password'
    app.state.staff_identity_repository.provision_account(
        'operations@example.invalid',
        password,
        'Operations Staff',
        ('operations',),
    )
    response = client.post(
        '/api/v1/staff/auth/sessions',
        json={'email': 'operations@example.invalid', 'password': password},
    )
    assert response.status_code == 201
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def _create_claim(client: TestClient, auth_headers: dict[str, str], suffix: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'least-privilege-{suffix}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    claim_id = response.json()['claim']['claim_id']
    assert isinstance(claim_id, str)
    return claim_id


def _claim_with_support_request(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> str:
    claim_id = _create_claim(client, auth_headers, 'read-only-actions')
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    response = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'least-privilege-support',
            'If-Match': str(claim.revision),
        },
        json={
            'reason': 'I need a claims professional to help me continue.',
            'support_need': 'human_requested',
            'preferred_channel': 'in_app',
        },
    )
    assert response.status_code == 201
    return claim_id


def test_operations_staff_can_manage_only_their_own_identity_session(
    app: FastAPI,
    client: TestClient,
    staff_auth_headers: dict[str, str],
) -> None:
    headers = _login_operations_staff(app, client)

    session = client.get('/api/v1/staff/auth/session', headers=headers)
    profile = client.get('/api/v1/staff/me', headers=headers)
    queue = client.get('/api/v1/workbench/claims', headers=headers)
    online_staff = client.get('/api/v1/workbench/staff/online', headers=staff_auth_headers)
    logout = client.delete('/api/v1/staff/auth/session', headers=headers)

    assert session.status_code == 200
    assert profile.status_code == 200
    assert profile.json()['roles'] == ['operations']
    assert queue.status_code == 403
    assert queue.json()['error']['code'] == 'ACCESS_DENIED'
    assert online_staff.status_code == 200
    assert all(
        item['staff_id'] != session.json()['staff_id'] for item in online_staff.json()['items']
    )
    assert logout.status_code == 204


@pytest.mark.parametrize(
    ('method', 'path_template', 'payload'),
    (
        ('GET', '/api/v1/workbench/claims', None),
        ('GET', '/api/v1/workbench/claims/{claim_id}', None),
        ('GET', '/api/v1/workbench/claims/clm_not_present', None),
        (
            'POST',
            '/api/v1/workbench/claims/{claim_id}/messages',
            {'content': {'type': 'text', 'text': 'This must not be persisted.'}},
        ),
        (
            'POST',
            '/api/v1/workbench/claims/{claim_id}/handoffs/hnd_not_present/accept',
            {},
        ),
        (
            'POST',
            '/api/v1/workbench/claims/{claim_id}/external-tasks/ext_not_present/accept-review',
            {},
        ),
        (
            'POST',
            '/api/v1/workbench/claims/{claim_id}/external-tasks/ext_not_present/reconcile',
            None,
        ),
    ),
)
def test_operations_staff_is_denied_before_workbench_resource_existence(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    method: str,
    path_template: str,
    payload: dict[str, object] | None,
) -> None:
    claim_id = _create_claim(client, auth_headers, method.casefold() + path_template[-8:])
    headers = {
        **_login_operations_staff(app, client),
        'Idempotency-Key': 'operations-must-not-write',
        'If-Match': '1',
    }

    response = client.request(
        method,
        path_template.format(claim_id=claim_id),
        headers=headers,
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'


def test_claims_professional_retains_workbench_read_access(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim_id = _create_claim(client, auth_headers, 'claims-professional')

    queue = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)

    assert queue.status_code == 200
    assert detail.status_code == 200


def test_read_only_effective_scope_projects_no_executable_actions(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _claim_with_support_request(client, auth_headers, repository)
    read_write = Principal(
        subject='stf_demo',
        actor_type='staff',
        scopes=frozenset({'workbench:read', 'workbench:write'}),
        roles=frozenset({'claims_professional'}),
    )
    read_only = Principal(
        subject='stf_demo',
        actor_type='staff',
        scopes=frozenset({'workbench:read'}),
        roles=frozenset({'claims_professional'}),
    )

    writable_detail = get_workbench_claim_detail(repository, read_write, claim_id)
    read_only_detail = get_workbench_claim_detail(repository, read_only, claim_id)

    assert any(
        action.action_code == 'human.accept_handoff' for action in writable_detail.allowed_actions
    )
    assert read_only_detail.allowed_actions == []


class _RepositoryThatMustNotBeRead:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f'authorization must run before repository access: {name}')


@pytest.mark.parametrize('operation', ('read', 'write'))
def test_service_authorization_runs_before_repository_access(operation: str) -> None:
    repository = _RepositoryThatMustNotBeRead()
    principal = Principal(
        subject='stf_operations',
        actor_type='staff',
        roles=frozenset({'operations'}),
    )

    with pytest.raises(ApiError) as error:
        if operation == 'read':
            get_workbench_claim_detail(repository, principal, 'clm_protected')  # type: ignore[arg-type]
        else:
            send_staff_message(
                repository,  # type: ignore[arg-type]
                principal,
                'clm_protected',
                CreateStaffMessageRequest(
                    content={'type': 'text', 'text': 'This must not reach persistence.'}
                ),
                'blocked-write',
                '1',
            )

    assert error.value.status_code == 403
    assert error.value.code == 'ACCESS_DENIED'
