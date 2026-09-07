from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.evaluations import SQLiteEvaluationRepository


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _headers(key: str | None = None) -> dict[str, str]:
    headers = {'Authorization': 'Bearer synthetic-admin'}
    if key is not None:
        headers['Idempotency-Key'] = key
    return headers


def _payload() -> dict[str, object]:
    return {
        'purpose': 'claimant_motor_intake',
        'model_version': 'model-profile-v4',
        'knowledge_version': 'motor-policy-MVP-2026.1',
        'rule_version': 'agent-rule-v3',
        'dataset_id': 'northwind-fnol-regression',
        'dataset_version': '2026-09-06',
        'fixture_version': 'presentation-v2',
        'source_versions': ['policy:motor:MVP-2026.1'],
        'scenario_results': [
            {
                'scenario_id': 'motor-rear-end-handoff',
                'outcome': 'succeeded',
                'score': 1,
                'evidence': 'Handoff preserved accepted facts and missing police report.',
            }
        ],
        'metrics': {'trajectory_accuracy': 1.0, 'citation_support': 1.0},
        'threshold': 0.95,
    }


def test_evaluation_records_are_admin_protected_idempotent_and_queryable() -> None:
    with _client() as client:
        denied = client.get('/internal/v1/admin/evaluations')
        assert denied.status_code == 401

        created = client.post(
            '/internal/v1/admin/evaluations', headers=_headers('evaluation-create'), json=_payload()
        )
        assert created.status_code == 201, created.text
        record = created.json()
        assert record['evaluation_id'].startswith('eval_')
        assert record['model_version'] == 'model-profile-v4'
        assert record['scenario_results'][0]['scenario_id'] == 'motor-rear-end-handoff'

        replay = client.post(
            '/internal/v1/admin/evaluations', headers=_headers('evaluation-create'), json=_payload()
        )
        assert replay.status_code == 201
        assert replay.json() == record

        conflict_payload = _payload()
        conflict_payload['dataset_version'] = 'different'
        conflict = client.post(
            '/internal/v1/admin/evaluations',
            headers=_headers('evaluation-create'),
            json=conflict_payload,
        )
        assert conflict.status_code == 409
        assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

        listed = client.get(
            '/internal/v1/admin/evaluations?purpose=claimant_motor_intake', headers=_headers()
        )
        assert listed.status_code == 200
        assert [item['evaluation_id'] for item in listed.json()['items']] == [
            record['evaluation_id']
        ]
        detail = client.get(
            f'/internal/v1/admin/evaluations/{record["evaluation_id"]}', headers=_headers()
        )
        assert detail.status_code == 200
        assert detail.json() == record


def test_evaluation_repository_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'control-plane.sqlite3'
    with _client() as client:
        record = client.post(
            '/internal/v1/admin/evaluations', headers=_headers('evaluation-sqlite'), json=_payload()
        ).json()
    # The application above uses the fixture repository. Verify the durable repository's
    # immutable write/read contract independently with the same serialized domain record.
    from backend.domain.evaluation import EvaluationRecord

    durable = SQLiteEvaluationRepository(str(path))
    durable.create(EvaluationRecord.model_validate(record))
    reopened = SQLiteEvaluationRepository(str(path))
    assert reopened.get(record['evaluation_id']) == EvaluationRecord.model_validate(record)
