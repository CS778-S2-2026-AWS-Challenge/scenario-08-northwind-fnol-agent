from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _post_headers(key: str, revision: int | None = None) -> dict[str, str]:
    headers = {'Authorization': 'Bearer synthetic-admin', 'Idempotency-Key': key}
    if revision is not None:
        headers['If-Match'] = f'"{revision}"'
    return headers


def _published_configuration(client: TestClient, domain: str, key: str) -> dict[str, object]:
    created = client.post(
        '/internal/v1/admin/configurations',
        headers=_post_headers(f'{key}-create'),
        json={'domain': domain, 'reason': f'Create {domain}.'},
    )
    assert created.status_code == 201
    configuration = created.json()
    validated = client.post(
        f'/internal/v1/admin/configurations/{configuration["configuration_id"]}/validate',
        headers=_post_headers(f'{key}-validate', 1),
        json={
            'scenario_results': [
                {'scenario_id': f'{domain}-check', 'outcome': 'passed', 'evidence': 'passed'}
            ]
        },
    )
    assert validated.status_code == 200
    assert validated.json()['state'] == 'published'
    return validated.json()


def test_release_set_validates_publishes_and_resolves_runtime_snapshot() -> None:
    with _client() as client:
        model = _published_configuration(client, 'feature', 'release-feature')
        release = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('release-create'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': model['configuration_id'],
                        'revision': model['revision'],
                    }
                },
                'reason': 'Assemble the test runtime release.',
            },
        )
        assert release.status_code == 201
        release_id = release.json()['release_set_id']
        assert release.json()['state'] == 'draft'

        validated = client.post(
            f'/internal/v1/admin/release-sets/{release_id}/validate',
            headers=_post_headers('release-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert validated.status_code == 200
        assert validated.json()['state'] == 'validation'

        published = client.post(
            f'/internal/v1/admin/release-sets/{release_id}/publish',
            headers=_post_headers('release-publish', 2),
            json={'reason': 'Publish the validated runtime release.'},
        )
        assert published.status_code == 200
        assert published.json()['state'] == 'published'

        snapshot = client.get(
            '/internal/v1/admin/runtime-snapshots',
            headers={'Authorization': 'Bearer synthetic-admin'},
            params={'environment': 'test', 'runtime_profile': 'fixture'},
        )
        assert snapshot.status_code == 200
        assert snapshot.json()['release_set_id'] == release_id
        assert snapshot.json()['configurations']['feature']['state'] == 'published'


def test_release_set_rejects_unpublished_configuration_reference() -> None:
    with _client() as client:
        draft = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('unpublished-create'),
            json={'domain': 'feature', 'reason': 'Keep this draft.'},
        ).json()
        release = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('unpublished-release'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': draft['configuration_id'],
                        'revision': draft['revision'],
                    }
                },
                'reason': 'This should not validate.',
            },
        )
        assert release.status_code == 201
        validation = client.post(
            f'/internal/v1/admin/release-sets/{release.json()["release_set_id"]}/validate',
            headers=_post_headers('unpublished-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert validation.status_code == 422
        assert validation.json()['error']['code'] == 'RELEASE_SET_CONFIGURATION_NOT_PUBLISHED'
