from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.knowledge_admin import KnowledgeSourceRecord, KnowledgeVersionState
from backend.domain.release import (
    ConfigurationReference,
    KnowledgeReference,
    ReleaseSetAuditEvent,
    ReleaseSetRecord,
    ReleaseSetState,
)
from backend.repositories.release_set import (
    ReleaseSetIdempotencyRecord,
    ReleaseSetRepository,
    SQLiteReleaseSetRepository,
)


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
    values = {
        'feature_version': f'{key}-v1',
        'model_assisted_turns': True,
        'knowledge_retrieval': True,
    }
    created = client.post(
        '/internal/v1/admin/configurations',
        headers=_post_headers(f'{key}-create'),
        json={'domain': domain, 'values': values, 'reason': f'Create {domain}.'},
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
    return cast(dict[str, object], validated.json())


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
        draft_projection = client.get(
            f'/internal/v1/admin/release-sets/{release_id}',
            headers={'Authorization': 'Bearer synthetic-admin'},
        ).json()
        draft_actions = {item['action_code']: item for item in draft_projection['allowed_actions']}
        assert draft_actions['admin.release_set.validate']['availability'] == 'available'
        assert draft_actions['admin.release_set.validate']['expected_revision'] == 1
        assert draft_actions['admin.release_set.publish']['availability'] == 'blocked'

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
        validated_projection = client.get(
            f'/internal/v1/admin/release-sets/{release_id}',
            headers={'Authorization': 'Bearer synthetic-admin'},
        ).json()
        publish_action = next(
            item
            for item in validated_projection['allowed_actions']
            if item['action_code'] == 'admin.release_set.publish'
        )
        assert publish_action['availability'] == 'confirmation_required'
        assert publish_action['expected_revision'] == 2

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
            json={
                'domain': 'feature',
                'values': {
                    'feature_version': 'unpublished-feature-v1',
                    'model_assisted_turns': True,
                    'knowledge_retrieval': True,
                },
                'reason': 'Keep this draft.',
            },
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


def test_release_set_rejects_unpublished_knowledge_reference() -> None:
    with _client() as client:
        configuration = _published_configuration(client, 'feature', 'unpublished-knowledge')
        knowledge = KnowledgeSourceRecord(
            knowledge_id='knw_draft',
            document_id='motor-policy',
            version='2026.2',
            source_key='knowledge/policies/2026.2.md',
            title='Motor policy',
            document_type='policy',
            source_uri='https://example.invalid/motor-policy',
            jurisdiction='NZ',
            insurer='Northwind Insurance',
            product='motor',
            authority='northwind_synthetic_demo',
            visibility='customer_and_staff',
            state=KnowledgeVersionState.DRAFT,
            revision=1,
            author='test-admin',
            updated_at=datetime.now(UTC),
        )
        cast(Any, client.app).state.knowledge_admin_repository.create(knowledge)
        release = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('unpublished-knowledge-release'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': configuration['configuration_id'],
                        'revision': configuration['revision'],
                    }
                },
                'knowledge_refs': {
                    'motor': KnowledgeReference(
                        knowledge_id=knowledge.knowledge_id,
                        revision=knowledge.revision,
                    ).model_dump(mode='json')
                },
                'reason': 'This should not validate.',
            },
        )
        assert release.status_code == 201
        validation = client.post(
            f'/internal/v1/admin/release-sets/{release.json()["release_set_id"]}/validate',
            headers=_post_headers('unpublished-knowledge-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert validation.status_code == 422
        assert validation.json()['error']['code'] == 'RELEASE_SET_KNOWLEDGE_NOT_PUBLISHED'


def test_release_set_snapshot_contains_selected_integration() -> None:
    with _client() as client:
        feature = _published_configuration(client, 'feature', 'integration-release-feature')
        integration = client.post(
            '/internal/v1/admin/configurations',
            headers=_post_headers('integration-release-create'),
            json={
                'domain': 'integration',
                'values': {
                    'service_id': 'assessor_service',
                    'capability': 'assessor_routing',
                    'source': 'fixture',
                },
                'reason': 'Register the assessor service.',
            },
        ).json()
        published = client.post(
            f'/internal/v1/admin/configurations/{integration["configuration_id"]}/validate',
            headers=_post_headers('integration-release-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'integration-health', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        ).json()
        release = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('integration-release-set'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': feature['configuration_id'],
                        'revision': feature['revision'],
                    }
                },
                'integration_refs': {
                    'assessor_service': {
                        'configuration_id': published['configuration_id'],
                        'revision': published['revision'],
                    }
                },
                'reason': 'Pin the assessor service configuration.',
            },
        ).json()
        client.post(
            f'/internal/v1/admin/release-sets/{release["release_set_id"]}/validate',
            headers=_post_headers('integration-release-set-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        client.post(
            f'/internal/v1/admin/release-sets/{release["release_set_id"]}/publish',
            headers=_post_headers('integration-release-set-publish', 2),
            json={'reason': 'Publish the integration release.'},
        )

        snapshot = client.get(
            '/internal/v1/admin/runtime-snapshots',
            headers={'Authorization': 'Bearer synthetic-admin'},
            params={'environment': 'test', 'runtime_profile': 'fixture'},
        )

        assert snapshot.status_code == 200
        assert (
            snapshot.json()['integrations']['assessor_service']['configuration_id']
            == published['configuration_id']
        )


def test_release_set_rejects_missing_configuration_and_missing_active_snapshot() -> None:
    with _client() as client:
        missing = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('missing-reference'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {'configuration_id': 'cfg_missing', 'revision': 1}
                },
                'reason': 'The reference must exist.',
            },
        )
        assert missing.status_code == 422
        assert missing.json()['error']['code'] == 'RELEASE_SET_CONFIGURATION_NOT_FOUND'

        snapshot = client.get(
            '/internal/v1/admin/runtime-snapshots',
            headers={'Authorization': 'Bearer synthetic-admin'},
            params={'environment': 'test', 'runtime_profile': 'fixture'},
        )
        assert snapshot.status_code == 404
        assert snapshot.json()['error']['code'] == 'ACTIVE_RELEASE_SET_NOT_FOUND'


def test_release_set_validation_and_publish_require_valid_state() -> None:
    with _client() as client:
        configuration = _published_configuration(client, 'feature', 'release-invalid-state')
        created = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('invalid-state-create'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': configuration['configuration_id'],
                        'revision': configuration['revision'],
                    }
                },
                'reason': 'Exercise transition failures.',
            },
        )
        release_id = created.json()['release_set_id']

        failed = client.post(
            f'/internal/v1/admin/release-sets/{release_id}/validate',
            headers=_post_headers('invalid-state-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'failed', 'evidence': 'unavailable'}
                ]
            },
        )
        assert failed.status_code == 422
        assert failed.json()['error']['code'] == 'RELEASE_SET_VALIDATION_FAILED'

        before_publish = client.post(
            f'/internal/v1/admin/release-sets/{release_id}/publish',
            headers=_post_headers('invalid-state-publish', 1),
            json={'reason': 'Cannot publish a draft.'},
        )
        assert before_publish.status_code == 400
        assert before_publish.json()['error']['code'] == 'INVALID_RELEASE_SET_TRANSITION'

        stale = client.post(
            f'/internal/v1/admin/release-sets/{release_id}/validate',
            headers=_post_headers('invalid-state-stale', 2),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
        audit = client.get(
            f'/internal/v1/admin/release-sets/{release_id}/audit',
            headers={'Authorization': 'Bearer synthetic-admin'},
        )
        assert audit.status_code == 200
        assert audit.json()['items'][-1]['action'] == 'validate'
        assert audit.json()['items'][-1]['outcome'] == 'rejected'


def test_release_set_rolls_back_to_a_prior_publication() -> None:
    with _client() as client:
        first_configuration = _published_configuration(client, 'feature', 'rollback-first-config')
        first = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('rollback-first-create'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': first_configuration['configuration_id'],
                        'revision': first_configuration['revision'],
                    }
                },
                'reason': 'Publish the first release.',
            },
        )
        first_id = first.json()['release_set_id']
        client.post(
            f'/internal/v1/admin/release-sets/{first_id}/validate',
            headers=_post_headers('rollback-first-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        first_published = client.post(
            f'/internal/v1/admin/release-sets/{first_id}/publish',
            headers=_post_headers('rollback-first-publish', 2),
            json={'reason': 'Publish the first release.'},
        )
        assert first_published.status_code == 200

        second_configuration = _published_configuration(client, 'feature', 'rollback-second-config')
        second = client.post(
            '/internal/v1/admin/release-sets',
            headers=_post_headers('rollback-second-create'),
            json={
                'environment': 'test',
                'runtime_profile': 'fixture',
                'configuration_refs': {
                    'feature': {
                        'configuration_id': second_configuration['configuration_id'],
                        'revision': second_configuration['revision'],
                    }
                },
                'reason': 'Publish the second release.',
            },
        )
        second_id = second.json()['release_set_id']
        client.post(
            f'/internal/v1/admin/release-sets/{second_id}/validate',
            headers=_post_headers('rollback-second-validate', 1),
            json={
                'scenario_results': [
                    {'scenario_id': 'runtime-load', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        second_published = client.post(
            f'/internal/v1/admin/release-sets/{second_id}/publish',
            headers=_post_headers('rollback-second-publish', 2),
            json={'reason': 'Publish the second release.'},
        )
        assert second_published.status_code == 200

        rollback = client.post(
            f'/internal/v1/admin/release-sets/{second_id}/rollback',
            headers=_post_headers('rollback-run', 3),
            json={'reason': 'Restore the first release.', 'rollback_target': first_id},
        )
        assert rollback.status_code == 200
        assert rollback.json()['state'] == 'published'
        assert rollback.json()['rollback_target'] == first_id

        audit = client.get(
            f'/internal/v1/admin/release-sets/{rollback.json()["release_set_id"]}/audit',
            headers={'Authorization': 'Bearer synthetic-admin'},
        )
        assert audit.status_code == 200
        assert any(item['action'] == 'rollback' for item in audit.json()['items'])


def test_release_set_repositories_round_trip_filters_and_idempotency(tmp_path: Path) -> None:
    record = ReleaseSetRecord(
        release_set_id='rel_repo_test',
        environment='test',
        runtime_profile='fixture',
        revision=1,
        state=ReleaseSetState.DRAFT,
        configuration_refs={
            'feature': ConfigurationReference(configuration_id='cfg_1', revision=1)
        },
        integration_refs={
            'claims_service': ConfigurationReference(configuration_id='cfg_2', revision=1)
        },
        knowledge_refs={'motor': KnowledgeReference(knowledge_id='knw_1', revision=1)},
        author='synthetic-admin',
        reason='Repository contract test.',
        updated_at=datetime(2026, 9, 7, tzinfo=UTC),
    )
    repository = ReleaseSetRepository()
    assert repository.create(record) == record
    assert repository.get(record.release_set_id) == record
    assert repository.get(record.release_set_id, revision=1) == record
    assert repository.get('rel_missing') is None
    assert repository.list_release_sets('test', 'fixture') == [record]
    assert repository.list_release_sets('other') == []
    assert repository.active('test', 'fixture') is None
    updated = record.model_copy(update={'revision': 2, 'reason': 'Updated.'})
    assert repository.save(updated, 1) == updated
    with pytest.raises(ValueError, match='stale_revision'):
        repository.save(updated.model_copy(update={'revision': 3}), 1)

    event = ReleaseSetAuditEvent(
        event_id='aud_rel_repo',
        release_set_id=record.release_set_id,
        revision=2,
        actor='synthetic-admin',
        action='patch',
        reason='Updated.',
        outcome='succeeded',
        created_at=record.updated_at,
    )
    repository.add_audit(event)
    assert repository.audits(record.release_set_id) == [event]
    idempotency = ReleaseSetIdempotencyRecord(
        actor='synthetic-admin',
        route='POST /internal/v1/admin/release-sets',
        key='release-repo-key',
        fingerprint='one',
        response={'release_set_id': record.release_set_id},
        status_code=201,
    )
    repository.save_idempotency(idempotency)
    assert (
        repository.find_idempotency(idempotency.actor, idempotency.route, idempotency.key)
        == idempotency
    )
    repository.save_idempotency(idempotency)
    with pytest.raises(ValueError, match='idempotency_conflict'):
        repository.save_idempotency(
            ReleaseSetIdempotencyRecord(
                actor=idempotency.actor,
                route=idempotency.route,
                key=idempotency.key,
                fingerprint='two',
                response=idempotency.response,
                status_code=idempotency.status_code,
            )
        )

    sqlite = SQLiteReleaseSetRepository(str(Path(tmp_path) / 'release.sqlite3'))
    assert sqlite.create(record) == record
    assert sqlite.get(record.release_set_id) == record
    assert sqlite.list_release_sets(environment='test', runtime_profile='fixture') == [record]
    assert sqlite.active('test', 'fixture') is None
    sqlite.add_audit(event)
    assert sqlite.audits(record.release_set_id) == [event]
