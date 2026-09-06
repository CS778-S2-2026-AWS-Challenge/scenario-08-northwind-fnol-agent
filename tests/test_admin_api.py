from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.configuration import ValidationRequest
from backend.services.configuration import read_active, validate


def _client() -> TestClient:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    return TestClient(create_app(settings))


def _model_client() -> TestClient:
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        model_protocol_adapter='openai_compatible',
        model_base_url='https://approved-model.example/v1',
        model_api_key_env='NORTHWIND_MODEL_API_KEY',
    )
    return TestClient(create_app(settings))


def _model_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        'protocol': 'openai_compatible',
        'provider': 'approved-provider',
        'model_identifier': 'approved-model',
        'base_url': 'https://approved-model.example/v1',
        'credential_environment_variable': 'NORTHWIND_MODEL_API_KEY',
        'profile_id': 'approved-profile',
        'purpose': 'agent_turn',
        'privacy_class': 'synthetic_fnol',
        'prompt_version': 'northwind-fnol-motor-claimant-v4',
        'evaluation_status': 'configured',
        'timeout_seconds': 30,
        'structured_output': True,
        'tools': False,
    }
    values.update(overrides)
    return values


def _headers(token: str = 'synthetic-admin') -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def _post_headers(
    key: str,
    revision: int | None = None,
    *,
    token: str = 'synthetic-admin',
) -> dict[str, str]:
    headers = {**_headers(token), 'Idempotency-Key': key}
    if revision is not None:
        headers['If-Match'] = f'"{revision}"'
    return headers


def test_admin_configuration_lifecycle_and_audit() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('create-1'),
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
            headers=_post_headers('validate-1', 1),
            json={
                'scenario_results': [
                    {
                        'scenario_id': 'motor-handoff',
                        'outcome': 'passed',
                        'evidence': '4 checks passed.',
                    }
                ]
            },
        )
        assert validation.status_code == 200
        assert validation.json()['state'] == 'awaiting_approval'

        published = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            headers=_post_headers('publish-1', 2, token='synthetic-release-approver'),
            json={'reason': 'Approved after scenario validation.'},
        )
        assert published.status_code == 200
        assert published.json()['state'] == 'published'

        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit',
            headers=_post_headers('create-2'),
        )
        assert audits.status_code == 200
        assert [item['action'] for item in audits.json()['items']] == [
            'create_draft',
            'validate',
            'publish',
        ]


def test_high_impact_publish_rejects_the_sole_author_and_audits_attempt() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('author-conflict-create'),
            json={
                'domain': 'agent_rule',
                'impact': 'high',
                'values': {'rule_id': 'motor-intake'},
                'reason': 'Create a high-impact rule.',
            },
        ).json()
        configuration_id = created['configuration_id']
        validated = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers=_post_headers('author-conflict-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'authority', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert validated.status_code == 200

        rejected = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            headers=_post_headers('author-conflict-publish', 2),
            json={'reason': 'The author must not approve this change.'},
        )

        assert rejected.status_code == 403
        assert rejected.json()['error']['code'] == 'CONFIGURATION_APPROVER_CONFLICT'
        record = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}', headers=_headers()
        ).json()
        assert record['state'] == 'awaiting_approval'
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        assert audits[-1]['action'] == 'publish'
        assert audits[-1]['outcome'] == 'rejected'


def test_admin_boundary_and_revision_errors() -> None:
    with _client() as client:
        denied = client.get(
            '/internal/v1/admin/configurations',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        assert denied.status_code == 403

        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('create-boundary'),
            json={'domain': 'feature', 'values': {'enabled': True}, 'reason': 'Demo flag.'},
        )
        configuration_id = created.json()['configuration_id']
        stale = client.patch(
            f'/internal/v1/admin/configurations/{configuration_id}',
            headers={**_post_headers('stale-patch'), 'If-Match': '"99"'},
            json={'values': {'enabled': False}, 'reason': 'Stale update.'},
        )
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        rejected = audits[-1]
        assert rejected['action'] == 'update_draft'
        assert rejected['outcome'] == 'rejected'
        assert rejected['error_code'] == 'REVISION_CONFLICT'
        assert rejected['revision'] == 1
        assert rejected['actor'] == 'adm_demo'


def test_failed_draft_update_is_audited_without_mutating_revision() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('failed-update-create'),
            json={
                'domain': 'data_profile',
                'values': {
                    'data_runtime_profile': 'fixture',
                    'object_storage_adapter': 'fixture',
                },
                'reason': 'Create a valid draft.',
            },
        ).json()
        configuration_id = created['configuration_id']

        invalid = client.patch(
            f'/internal/v1/admin/configurations/{configuration_id}',
            headers=_post_headers('failed-update-invalid', 1),
            json={
                'values': {
                    'data_runtime_profile': 'local_mvp',
                    'object_storage_adapter': 'fixture',
                },
                'reason': 'Reject an incoherent provider bundle.',
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()['error']['code'] == 'PROVIDER_CONFIGURATION_INVALID'

        stored = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}', headers=_headers()
        ).json()
        assert stored['revision'] == 1
        assert stored['values'] == {
            'data_runtime_profile': 'fixture',
            'object_storage_adapter': 'fixture',
        }
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        rejected = audits[-1]
        assert rejected['action'] == 'update_draft'
        assert rejected['outcome'] == 'rejected'
        assert rejected['error_code'] == 'PROVIDER_CONFIGURATION_INVALID'
        assert rejected['revision'] == 1
        assert rejected['changed_fields'] == []


def test_draft_update_records_version_actor_time_and_changed_fields() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('change-create'),
            json={
                'domain': 'feature',
                'values': {'enabled': False},
                'reason': 'Create disabled feature.',
            },
        ).json()
        configuration_id = created['configuration_id']

        updated = client.patch(
            f'/internal/v1/admin/configurations/{configuration_id}',
            headers=_post_headers('change-patch', 1),
            json={'values': {'enabled': True}, 'reason': 'Enable controlled feature.'},
        )

        assert updated.status_code == 200
        assert updated.json()['revision'] == 2
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        change = audits[-1]
        assert change['action'] == 'update_draft'
        assert change['revision'] == 2
        assert change['previous_revision'] == 1
        assert change['actor'] == 'adm_demo'
        assert change['changed_fields'] == ['reason', 'values']
        assert change['created_at']


def test_plaintext_secret_is_rejected() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('secret-1'),
            json={
                'domain': 'model',
                'values': {'api_key': 'do-not-store'},
                'reason': 'Invalid secret attempt.',
            },
        )
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'SECRET_VALUE_FORBIDDEN'


@pytest.mark.parametrize('impact_fields', [{}, {'impact': 'normal'}], ids=['omitted', 'normal'])
def test_model_configuration_cannot_downgrade_its_impact_classification(
    impact_fields: dict[str, str],
) -> None:
    with _model_client() as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers(f'model-normal-impact-{impact_fields}'),
            json={
                'domain': 'model',
                'values': _model_values(),
                'reason': 'Attempt to bypass independent approval.',
                **impact_fields,
            },
        )

        assert response.status_code == 422
        assert response.json()['error']['code'] == 'PROVIDER_CONFIGURATION_INVALID'
        repository = cast(Any, client.app).state.configuration_repository
        assert repository.list_configurations(domain='model') == []


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('protocol', 'unregistered_protocol'),
        ('base_url', 'https://unapproved.example/v1'),
        ('credential_environment_variable', 'UNAPPROVED_PROCESS_SECRET'),
        ('evaluation_status', 'degraded'),
        ('evaluation_status', 'unavailable'),
        ('purpose', 'batch_evaluation'),
        ('privacy_class', 'unrestricted'),
        ('prompt_version', 'northwind-fnol-motor-claimant-v2'),
        ('structured_output', False),
    ],
)
def test_model_validation_rejects_unverified_runtime_authority(
    field: str,
    value: object,
) -> None:
    with _model_client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers(f'model-authority-create-{field}-{value}'),
            json={
                'domain': 'model',
                'impact': 'high',
                'values': _model_values(**{field: value}),
                'reason': 'Retain an unverified model profile as a draft.',
            },
        )
        assert created.status_code == 201, created.text
        configuration_id = created.json()['configuration_id']

        validation = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers=_post_headers(f'model-authority-validate-{field}-{value}', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'model-authority', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )

        assert validation.status_code == 422
        assert validation.json()['error']['code'] == 'PROVIDER_CONFIGURATION_UNAVAILABLE'
        stored = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}', headers=_headers()
        ).json()
        assert stored['state'] == 'draft'
        repository = cast(Any, client.app).state.configuration_repository
        assert repository.active('model') is None


def test_data_profile_configuration_is_closed_and_provider_neutral() -> None:
    with _client() as client:
        invalid = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('data-profile-invalid'),
            json={
                'domain': 'data_profile',
                'values': {
                    'data_runtime_profile': 'local_mvp',
                    'object_storage_adapter': 'fixture',
                },
                'reason': 'Reject incoherent provider bundle.',
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()['error']['code'] == 'PROVIDER_CONFIGURATION_INVALID'

        aws_fixture = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('data-profile-aws-fixture'),
            json={
                'domain': 'data_profile',
                'values': {
                    'data_runtime_profile': 'aws',
                    'object_storage_adapter': 'fixture',
                },
                'reason': 'Reject a mixed cloud and fixture bundle.',
            },
        )
        assert aws_fixture.status_code == 422
        assert aws_fixture.json()['error']['code'] == 'PROVIDER_CONFIGURATION_INVALID'

        draft = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('data-profile-draft'),
            json={
                'domain': 'data_profile',
                'values': {
                    'data_runtime_profile': 'mongodb',
                    'object_storage_adapter': 's3_compatible',
                },
                'reason': 'Record an unverified provider for review.',
            },
        )
        assert draft.status_code == 201
        configuration_id = draft.json()['configuration_id']
        read_back = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}', headers=_headers()
        )
        assert read_back.status_code == 200
        assert read_back.json()['values']['data_runtime_profile'] == 'mongodb'
        validation = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers=_post_headers('data-profile-validate', 1),
            json={
                'scenario_results': [
                    {
                        'scenario_id': 'provider-readiness',
                        'outcome': 'passed',
                        'evidence': 'checked',
                    }
                ]
            },
        )
        assert validation.status_code == 422
        assert validation.json()['error']['code'] == 'PROVIDER_CONFIGURATION_UNAVAILABLE'
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        assert audits[-1]['action'] == 'validate'
        assert audits[-1]['outcome'] == 'rejected'


@pytest.mark.parametrize('profile', ['local_mvp', 'cloudflare', 'mongodb', 'aws'])
def test_data_profile_rejects_fixture_storage_for_every_external_profile(profile: str) -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers(f'data-profile-mixed-{profile}'),
            json={
                'domain': 'data_profile',
                'values': {
                    'data_runtime_profile': profile,
                    'object_storage_adapter': 'fixture',
                },
                'reason': 'Reject mixed provider configuration.',
            },
        )

        assert response.status_code == 422
        assert response.json()['error']['code'] == 'PROVIDER_CONFIGURATION_INVALID'


def test_publish_supersedes_previous_and_rollback_keeps_history() -> None:
    with _client() as client:
        first = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('first-create'),
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
            headers=_post_headers('first-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'motor-intake', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        client.post(
            f'/internal/v1/admin/configurations/{first_id}/publish',
            headers=_post_headers('first-publish', 2, token='synthetic-release-approver'),
            json={'reason': 'Publish first rule.'},
        )
        second = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('second-create'),
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
            headers=_post_headers('second-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'motor-intake', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        published = client.post(
            f'/internal/v1/admin/configurations/{second_id}/publish',
            headers=_post_headers('second-publish', 2, token='synthetic-release-approver'),
            json={'reason': 'Publish second rule.'},
        ).json()
        assert published['previous_version'] == first_id
        rolled_back = client.post(
            f'/internal/v1/admin/configurations/{second_id}/rollback',
            headers=_post_headers('rollback-1', 3),
            json={'reason': 'Restore first rule.', 'rollback_target': first_id},
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()['rollback_target'] == first_id
        assert (
            client.get(f'/internal/v1/admin/configurations/{second_id}', headers=_headers()).json()[
                'state'
            ]
            == 'superseded'
        )
        second_audits = client.get(
            f'/internal/v1/admin/configurations/{second_id}/audit', headers=_headers()
        ).json()['items']
        assert second_audits[-1]['action'] == 'supersede'
        assert second_audits[-1]['changed_fields'] == ['state']
        rollback_audits = client.get(
            f'/internal/v1/admin/configurations/{rolled_back.json()["configuration_id"]}/audit',
            headers=_headers(),
        ).json()['items']
        assert rollback_audits[-1]['action'] == 'rollback'
        assert rollback_audits[-1]['actor'] == 'adm_demo'
        assert rollback_audits[-1]['previous_revision'] == 3
        assert rollback_audits[-1]['changed_fields'] == [
            'effective_time',
            'previous_version',
            'rollback_target',
            'state',
        ]


def test_runtime_reads_only_the_active_published_configuration() -> None:
    with _client() as client:
        repository = cast(Any, client.app).state.configuration_repository
        draft = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('runtime-draft'),
            json={'domain': 'feature', 'values': {'enabled': False}, 'reason': 'Draft only.'},
        ).json()

        with pytest.raises(Exception) as missing:
            read_active(repository, 'feature')
        assert getattr(missing.value, 'code', None) == 'ACTIVE_CONFIGURATION_NOT_FOUND'

        published = client.post(
            f'/internal/v1/admin/configurations/{draft["configuration_id"]}/validate',
            headers=_post_headers('runtime-publish', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'feature-runtime', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        ).json()
        later_draft = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('runtime-later-draft'),
            json={'domain': 'feature', 'values': {'enabled': True}, 'reason': 'Not published.'},
        ).json()

        active = read_active(repository, 'feature')
        assert active.configuration_id == published['configuration_id']
        assert active.configuration_id != later_draft['configuration_id']
        assert active.state.value == 'published'


def test_normal_validation_supersedes_previous_publication() -> None:
    with _client() as client:
        first = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('normal-first-create'),
            json={'domain': 'feature', 'reason': 'First normal config.'},
        ).json()
        first_id = first['configuration_id']
        first_published = client.post(
            f'/internal/v1/admin/configurations/{first_id}/validate',
            headers=_post_headers('normal-first-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'feature-read', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert first_published.status_code == 200
        assert first_published.json()['state'] == 'published'

        second = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('normal-second-create'),
            json={'domain': 'feature', 'reason': 'Second normal config.'},
        ).json()
        second_id = second['configuration_id']
        second_published = client.post(
            f'/internal/v1/admin/configurations/{second_id}/validate',
            headers=_post_headers('normal-second-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'feature-read', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert second_published.status_code == 200
        assert second_published.json()['previous_version'] == first_id
        assert (
            client.get(f'/internal/v1/admin/configurations/{first_id}', headers=_headers()).json()[
                'state'
            ]
            == 'superseded'
        )
        audits = client.get(
            f'/internal/v1/admin/configurations/{first_id}/audit', headers=_headers()
        ).json()['items']
        supersede = next(item for item in audits if item['action'] == 'supersede')
        assert supersede['outcome'] == 'succeeded'
        assert supersede['revision'] == 3


def test_normal_publication_write_failure_restores_previous_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client() as client:
        first = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('atomic-first-create'),
            json={'domain': 'atomic', 'reason': 'First normal config.'},
        ).json()
        first_id = first['configuration_id']
        client.post(
            f'/internal/v1/admin/configurations/{first_id}/validate',
            headers=_post_headers('atomic-first-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'atomic', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        repository = cast(Any, client.app).state.configuration_repository
        original_save = repository.save

        def fail_new_publication(record: object, expected_revision: int) -> object:
            if getattr(record, 'configuration_id', None) != first_id:
                raise RuntimeError('simulated publication write failure')
            return original_save(record, expected_revision)

        monkeypatch.setattr(repository, 'save', fail_new_publication)
        second = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('atomic-second-create'),
            json={'domain': 'atomic', 'reason': 'Second normal config.'},
        ).json()
        with pytest.raises(RuntimeError, match='simulated publication write failure'):
            validate(
                repository,
                second['configuration_id'],
                ValidationRequest(
                    scenario_results=[
                        {
                            'scenario_id': 'atomic',
                            'outcome': 'passed',
                            'evidence': 'passed',
                        }
                    ]
                ),
                'synthetic-admin',
                1,
            )
        assert repository.get(first_id).state.value == 'published'
        assert not any(event.action == 'supersede' for event in repository.audits(first_id))


def test_admin_post_requires_idempotency_and_if_match_is_conflict() -> None:
    with _client() as client:
        missing_key = client.post(
            '/internal/v1/admin/configurations',
            headers=_headers(),
            json={'domain': 'feature', 'reason': 'Missing key.'},
        )
        assert missing_key.status_code == 400
        assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'

        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('if-match-create'),
            json={'domain': 'feature', 'reason': 'Create draft.'},
        ).json()
        missing_revision = client.post(
            f'/internal/v1/admin/configurations/{created["configuration_id"]}/validate',
            headers={
                'Authorization': 'Bearer synthetic-admin',
                'Idempotency-Key': 'if-match-validate',
            },
            json={
                'scenario_results': [
                    {'scenario_id': 'feature', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert missing_revision.status_code == 409
        assert missing_revision.json()['error']['code'] == 'REVISION_REQUIRED'


def test_failed_validation_and_transition_are_audited() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('failure-create'),
            json={'domain': 'agent_rule', 'reason': 'Failure test.'},
        ).json()
        configuration_id = created['configuration_id']
        failed = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers=_post_headers('failure-validate', 1),
            json={
                'scenario_results': [
                    {
                        'scenario_id': 'broken',
                        'outcome': 'failed',
                        'evidence': 'Required assertion failed.',
                    }
                ]
            },
        )
        assert failed.status_code == 422
        assert failed.json()['error']['code'] == 'VALIDATION_FAILED'
        invalid_transition = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            headers=_post_headers('failure-publish', 1),
            json={'reason': 'Not validated.'},
        )
        assert invalid_transition.status_code == 400
        audits = client.get(
            f'/internal/v1/admin/configurations/{configuration_id}/audit', headers=_headers()
        ).json()['items']
        assert audits[-2]['outcome'] == 'rejected'
        assert audits[-1]['outcome'] == 'rejected'


def test_idempotent_create_replays_and_conflicts() -> None:
    with _client() as client:
        first = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('replay-create'),
            json={'domain': 'feature', 'reason': 'Replay.'},
        )
        replay = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('replay-create'),
            json={'domain': 'feature', 'reason': 'Replay.'},
        )
        assert first.status_code == replay.status_code == 201
        assert first.json() == replay.json()
        conflict = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('replay-create'),
            json={'domain': 'feature', 'reason': 'Different request.'},
        )
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
