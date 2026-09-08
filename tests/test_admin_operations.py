from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.operations import (
    OperationIdempotencyRecord,
    OperationRepository,
    SQLiteOperationRepository,
)


def _headers() -> dict[str, str]:
    return {'Authorization': 'Bearer synthetic-admin'}


def _model_operation(
    operation_id: str,
    *,
    state: OperationState,
    error_code: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reported_usage: bool = True,
) -> OperationRecord:
    now = datetime.now(UTC)
    return OperationRecord(
        operation_id=operation_id,
        kind=OperationKind.MODEL_INVOCATION,
        subject_type='model_purpose',
        subject_id='agent_turn',
        state=state,
        revision=1,
        status_url=f'/internal/v1/admin/operations/{operation_id}',
        progress_percent=100,
        result={
            'purpose': 'agent_turn',
            'provider_model': 'fast-model' if reported_usage else None,
            'input_tokens': input_tokens if reported_usage else None,
            'output_tokens': output_tokens if reported_usage else None,
            'total_tokens': input_tokens + output_tokens if reported_usage else None,
            'latency_ms': 12.5,
        },
        error_code=error_code,
        created_at=now,
        updated_at=now,
    )


def test_operation_metrics_use_persisted_model_usage_and_published_thresholds() -> None:
    now = datetime.now(UTC)
    configurations = ConfigurationRepository()
    configurations.create(
        ConfigurationRecord(
            configuration_id='cfg_operations',
            domain='operational',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.NORMAL,
            values={
                'currency': 'USD',
                'model_cost_rates': [
                    {
                        'model_identifier': 'fast-model',
                        'input_microunits_per_million_tokens': 1_000_000,
                        'output_microunits_per_million_tokens': 2_000_000,
                    }
                ],
                'rate_limit_window_seconds': 3600,
                'token_alert_threshold': 100,
                'cost_alert_threshold_microunits': 200,
                'rate_limit_alert_count': 1,
            },
            author='adm_demo',
            reason='Configure bounded operational projections.',
            effective_time=now,
            updated_at=now,
        )
    )
    operations = OperationRepository()
    operations.create(
        _model_operation(
            'opr_model_success',
            state=OperationState.SUCCEEDED,
            input_tokens=100,
            output_tokens=20,
        )
    )
    operations.create(
        _model_operation(
            'opr_model_limited',
            state=OperationState.FAILED,
            error_code='MODEL_RATE_LIMIT',
            reported_usage=False,
        )
    )

    with TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            configuration_repository=configurations,
            operation_repository=operations,
        )
    ) as client:
        response = client.get('/internal/v1/admin/operations/metrics', headers=_headers())

    assert response.status_code == 200
    metrics = response.json()
    assert metrics['total'] == 2
    assert metrics['by_kind'] == {'model_invocation': 2}
    assert metrics['usage'] == {
        'calls': 2,
        'reported_calls': 1,
        'input_tokens': 100,
        'output_tokens': 20,
        'total_tokens': 120,
    }
    assert metrics['cost'] == {
        'status': 'partial',
        'currency': 'USD',
        'estimated_microunits': 140,
        'priced_calls': 1,
        'unpriced_calls': 1,
        'configuration_id': 'cfg_operations',
        'configuration_revision': 1,
    }
    assert metrics['rate_limit']['status'] == 'limited'
    assert metrics['rate_limit']['events_in_window'] == 1
    assert [item['status'] for item in metrics['alerts']] == [
        'unknown',
        'unknown',
        'triggered',
    ]


def test_operation_cost_rounds_once_per_model_call() -> None:
    now = datetime.now(UTC)
    configurations = ConfigurationRepository()
    configurations.create(
        ConfigurationRecord(
            configuration_id='cfg_operations_rounding',
            domain='operational',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.NORMAL,
            values={
                'currency': 'USD',
                'model_cost_rates': [
                    {
                        'model_identifier': 'fast-model',
                        'input_microunits_per_million_tokens': 500_000,
                        'output_microunits_per_million_tokens': 500_000,
                    }
                ],
                'rate_limit_window_seconds': 3600,
                'token_alert_threshold': 100,
                'cost_alert_threshold_microunits': 100,
                'rate_limit_alert_count': 1,
            },
            author='adm_demo',
            reason='Verify one rounding boundary per call.',
            effective_time=now,
            updated_at=now,
        )
    )
    operations = OperationRepository()
    operations.create(
        _model_operation(
            'opr_model_rounding',
            state=OperationState.SUCCEEDED,
            input_tokens=1,
            output_tokens=1,
        )
    )

    with TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            configuration_repository=configurations,
            operation_repository=operations,
        )
    ) as client:
        response = client.get('/internal/v1/admin/operations/metrics', headers=_headers())

    assert response.status_code == 200
    assert response.json()['cost']['estimated_microunits'] == 1


def test_operation_metrics_are_explicit_when_operational_configuration_is_absent() -> None:
    operations = OperationRepository()
    operations.create(
        _model_operation(
            'opr_unpriced',
            state=OperationState.SUCCEEDED,
            input_tokens=10,
            output_tokens=5,
        )
    )
    with TestClient(
        create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            operation_repository=operations,
        )
    ) as client:
        response = client.get('/internal/v1/admin/operations/metrics', headers=_headers())

    assert response.status_code == 200
    metrics = response.json()
    assert metrics['usage']['total_tokens'] == 15
    assert metrics['cost']['status'] == 'unconfigured'
    assert metrics['cost']['unpriced_calls'] == 1
    assert metrics['rate_limit']['status'] == 'unconfigured'
    assert metrics['alerts'] == []


def test_operational_configuration_rejects_incomplete_values() -> None:
    with TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    ) as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers={**_headers(), 'Idempotency-Key': 'invalid-operational-configuration'},
            json={
                'domain': 'operational',
                'values': {'currency': 'USD'},
                'reason': 'Reject an incomplete operational contract.',
            },
        )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'OPERATIONAL_CONFIGURATION_INVALID'


def test_operation_repositories_persist_filter_and_guard_revisions(tmp_path: Path) -> None:
    from pathlib import Path

    operation = _model_operation('opr_repository', state=OperationState.SUCCEEDED, input_tokens=10)
    repository = OperationRepository()
    assert repository.create(operation) == operation
    assert repository.get(operation.operation_id) == operation
    assert repository.get('opr_missing') is None
    assert repository.list(kind='model_invocation', state='succeeded') == [operation]
    assert repository.list(kind='other') == []
    with pytest.raises(ValueError, match='operation_exists'):
        repository.create(operation)
    updated = operation.model_copy(update={'revision': 2, 'state': OperationState.FAILED})
    assert repository.save(updated, 1) == updated
    assert repository.metrics_records() == [updated]
    with pytest.raises(ValueError, match='stale_revision'):
        repository.save(updated.model_copy(update={'revision': 3}), 1)

    idempotency = OperationIdempotencyRecord(
        actor='adm_demo',
        route='POST /internal/v1/admin/operations',
        key='operation-key',
        fingerprint='one',
        response={'operation_id': operation.operation_id},
        status_code=200,
    )
    repository.save_idempotency(idempotency)
    assert (
        repository.find_idempotency(idempotency.actor, idempotency.route, idempotency.key)
        == idempotency
    )
    with pytest.raises(ValueError, match='idempotency_conflict'):
        repository.save_idempotency(
            OperationIdempotencyRecord(
                actor=idempotency.actor,
                route=idempotency.route,
                key=idempotency.key,
                fingerprint='two',
                response=idempotency.response,
                status_code=idempotency.status_code,
            )
        )

    sqlite = SQLiteOperationRepository(str(Path(tmp_path) / 'operations.sqlite3'))
    assert sqlite.create(operation) == operation
    assert sqlite.get(operation.operation_id) == operation
    assert sqlite.list(kind='model_invocation', state='succeeded') == [operation]
    assert sqlite.metrics_records() == [operation]
    assert sqlite.find_idempotency('adm_demo', idempotency.route, idempotency.key) is None
    sqlite.save_idempotency(idempotency)
    assert (
        sqlite.find_idempotency(idempotency.actor, idempotency.route, idempotency.key)
        == idempotency
    )
