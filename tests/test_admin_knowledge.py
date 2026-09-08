from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.knowledge_admin import KnowledgeSourceRecord
from backend.repositories.knowledge_admin import (
    KnowledgeAdminRepository,
    SQLiteKnowledgeAdminRepository,
)


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _headers(key: str, token: str = 'synthetic-admin') -> dict[str, str]:
    return {'Authorization': f'Bearer {token}', 'Idempotency-Key': key}


def _source_payload() -> dict[str, object]:
    return {
        'document_id': 'nw-guidance-motor-demo',
        'version': '2026.09',
        'source_key': 'knowledge/guidance/2026.09/motor.md',
        'title': 'Northwind Motor Guidance',
        'document_type': 'guidance',
        'source_uri': 'northwind://guidance/motor/2026.09',
        'jurisdiction': 'NZ',
        'insurer': 'Northwind Insurance',
        'product': 'motor',
        'effective_from': '2026-09-01T00:00:00Z',
        'effective_to': '2027-09-01T00:00:00Z',
        'authority': 'northwind_demo',
        'visibility': 'customer_and_staff',
        'content': (
            '# Motor guidance\n\n## Police report\n'
            'Provide a police report when theft is suspected.\n'
        ),
    }


def test_knowledge_version_runs_metadata_ingestion_validation_retrieval_and_publish() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-create'),
            json=_source_payload(),
        )
        assert created.status_code == 201, created.text
        record = created.json()
        knowledge_id = record['knowledge_id']
        assert record['state'] == 'draft'
        assert 'content' not in record
        draft_projection = client.get(
            f'/internal/v1/admin/knowledge/{knowledge_id}',
            headers=_headers('knowledge-read'),
        ).json()
        draft_actions = {item['action_code']: item for item in draft_projection['allowed_actions']}
        assert draft_actions['admin.knowledge.ingest']['availability'] == 'available'
        assert draft_actions['admin.knowledge.ingest']['expected_revision'] is None
        assert draft_actions['admin.knowledge.retrieval_check']['availability'] == 'available'
        assert draft_actions['admin.knowledge.publish']['availability'] == 'blocked'

        ingested = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/ingest',
            headers=_headers('knowledge-ingest'),
        )
        assert ingested.status_code == 200, ingested.text
        assert ingested.json()['state'] == 'indexed'
        assert ingested.json()['chunk_count'] >= 1
        assert ingested.json()['ingestion_operation_id'].startswith('opr_')

        validated = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/validate',
            headers=_headers('knowledge-validate'),
            json={'scenario_results': [{'scenario_id': 'citation', 'outcome': 'passed'}]},
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()['state'] == 'awaiting_approval'
        approver_projection = client.get(
            f'/internal/v1/admin/knowledge/{knowledge_id}',
            headers=_headers('knowledge-approver-read', token='synthetic-release-approver'),
        ).json()
        publish_action = next(
            item
            for item in approver_projection['allowed_actions']
            if item['action_code'] == 'admin.knowledge.publish'
        )
        assert publish_action['availability'] == 'confirmation_required'
        assert publish_action['expected_revision'] is None

        checked = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/retrieval-check',
            headers=_headers('knowledge-retrieval'),
            json={
                'question': 'police report',
                'jurisdiction': 'NZ',
                'visibility': 'customer_and_staff',
                'authority': 'northwind_demo',
                'version': '2026.09',
                'insurer': 'Northwind Insurance',
                'product': 'motor',
                'effective_at': '2026-09-06T00:00:00Z',
                'limit': 5,
            },
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()['result']['status'] == 'evidence_found'
        assert checked.json()['operation_id'].startswith('opr_')

        published = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/publish',
            headers=_headers('knowledge-publish', token='synthetic-release-approver'),
        )
        assert published.status_code == 200, published.text
        assert published.json()['state'] == 'published'

        audit = client.get(
            f'/internal/v1/admin/knowledge/{knowledge_id}/audit',
            headers=_headers('knowledge-audit', token='synthetic-release-approver'),
        )
        assert audit.status_code == 200
        assert any(item['reason'].startswith('publish:') for item in audit.json()['items'])

        replay = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/publish',
            headers=_headers('knowledge-publish', token='synthetic-release-approver'),
        )
        assert replay.status_code == 200
        assert replay.json() == published.json()


def test_knowledge_rejects_claim_and_staff_records() -> None:
    with _client() as client:
        payload = _source_payload()
        payload['document_type'] = 'claim_state'
        response = client.post(
            '/internal/v1/admin/knowledge', headers=_headers('knowledge-forbidden'), json=payload
        )
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'KNOWLEDGE_DOCUMENT_TYPE_FORBIDDEN'


def test_knowledge_list_filters_and_missing_source_are_contractual() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-list-create'),
            json=_source_payload(),
        )
        assert created.status_code == 201
        knowledge_id = created.json()['knowledge_id']

        listed = client.get(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-list-read'),
            params={'state': 'draft', 'document_id': 'nw-guidance-motor-demo'},
        )
        assert listed.status_code == 200
        assert [item['knowledge_id'] for item in listed.json()['items']] == [knowledge_id]

        missing = client.get(
            '/internal/v1/admin/knowledge/knw_missing',
            headers=_headers('knowledge-missing-read'),
        )
        assert missing.status_code == 404
        assert missing.json()['error']['code'] == 'KNOWLEDGE_NOT_FOUND'


def test_knowledge_validation_failure_and_transition_guards() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-failure-create'),
            json=_source_payload(),
        )
        knowledge_id = created.json()['knowledge_id']
        failed = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/validate',
            headers=_headers('knowledge-failure-validate'),
            json={'scenario_results': [{'scenario_id': 'citation', 'outcome': 'failed'}]},
        )
        assert failed.status_code == 200
        assert failed.json()['state'] == 'failed'
        assert failed.json()['error_code'] == 'VALIDATION_FAILED'

        invalid_publish = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/publish',
            headers=_headers('knowledge-invalid-publish'),
        )
        assert invalid_publish.status_code == 400
        assert invalid_publish.json()['error']['code'] == 'INVALID_KNOWLEDGE_TRANSITION'

        indexed = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/ingest',
            headers=_headers('knowledge-failure-ingest'),
        )
        assert indexed.status_code == 200
        assert indexed.json()['state'] == 'indexed'

        validated = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/validate',
            headers=_headers('knowledge-success-validate'),
            json={'scenario_results': [{'scenario_id': 'citation', 'outcome': 'passed'}]},
        )
        assert validated.status_code == 200

        author_publish = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/publish',
            headers=_headers('knowledge-author-publish'),
        )
        assert author_publish.status_code == 403
        assert author_publish.json()['error']['code'] == 'KNOWLEDGE_APPROVER_CONFLICT'


def test_knowledge_withdrawal_and_replay_are_safe() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-withdraw-create'),
            json=_source_payload(),
        )
        knowledge_id = created.json()['knowledge_id']
        withdrawn = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/withdraw',
            headers=_headers('knowledge-withdraw'),
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()['state'] == 'withdrawn'
        replay = client.post(
            f'/internal/v1/admin/knowledge/{knowledge_id}/withdraw',
            headers=_headers('knowledge-withdraw'),
        )
        assert replay.status_code == 200
        assert replay.json() == withdrawn.json()


def test_knowledge_store_failure_is_reported_without_creating_a_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client() as client:
        store = cast(Any, client.app).state.knowledge_object_store

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError('store down')

        monkeypatch.setattr(store, 'write', fail_write)
        response = client.post(
            '/internal/v1/admin/knowledge',
            headers=_headers('knowledge-store-failure'),
            json=_source_payload(),
        )
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'KNOWLEDGE_STORE_UNAVAILABLE'


def test_knowledge_repositories_filter_and_enforce_revisions(tmp_path: Path) -> None:
    record = KnowledgeSourceRecord.model_validate(
        {
            'knowledge_id': 'knw_repo_test',
            **{key: value for key, value in _source_payload().items() if key != 'content'},
            'state': 'draft',
            'revision': 1,
            'author': 'synthetic-admin',
            'validation_evidence': None,
            'chunk_count': None,
            'ingestion_operation_id': None,
            'error_code': None,
            'previous_version': None,
            'updated_at': '2026-09-07T00:00:00Z',
        }
    )
    repository = KnowledgeAdminRepository()
    assert repository.create(record) == record
    assert repository.list(state=record.state, document_id=record.document_id, limit=0) == [record]
    assert repository.active(record.document_id) is None
    assert record.product is not None
    assert repository.published_for_product(record.product) is None
    with pytest.raises(ValueError, match='knowledge_version_exists'):
        repository.create(record.model_copy(update={'knowledge_id': 'knw_repo_duplicate'}))
    with pytest.raises(ValueError, match='stale_revision'):
        repository.save(record.model_copy(update={'revision': 2}), expected_revision=99)

    sqlite = SQLiteKnowledgeAdminRepository(str(tmp_path / 'knowledge.sqlite3'))
    assert sqlite.create(record) == record
    assert sqlite.get(record.knowledge_id) == record
    assert sqlite.list(document_id=record.document_id) == [record]
    with pytest.raises(ValueError, match='knowledge_version_exists'):
        sqlite.create(record.model_copy(update={'knowledge_id': 'knw_sqlite_duplicate'}))
    with pytest.raises(ValueError, match='stale_revision'):
        sqlite.save(record.model_copy(update={'revision': 2}), expected_revision=99)
