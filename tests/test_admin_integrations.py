from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.handoff_dispatch import HandoffDispatchUnavailable
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.integration_health import IntegrationHealthCheckRecord
from backend.domain.integration_registry import IntegrationHealthState
from backend.repositories.integration_health import SQLiteIntegrationHealthRepository
from backend.services.integration_registry import _connection_status, _health_state, _source


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _admin_headers() -> dict[str, str]:
    return {'Authorization': 'Bearer synthetic-admin'}


def test_admin_integration_list_reads_real_fixture_adapter_statuses() -> None:
    with _client() as client:
        denied = client.get('/internal/v1/admin/integrations')
        assert denied.status_code == 401

        response = client.get('/internal/v1/admin/integrations', headers=_admin_headers())
        assert response.status_code == 200
        items = response.json()['items']
        assert {item['integration_id'] for item in items} == {
            'persistence',
            'evidence_storage',
            'policy',
            'claim_history',
            'knowledge_documents',
            'knowledge_retrieval',
            'claims_service',
            'assessor_service',
            'handoff_dispatch',
        }
        assert all(item['health'] == 'using_fixture' for item in items)
        assert all(item['source'] == 'fixture' for item in items)
        assert all(item['latency_ms'] is not None and item['latency_ms'] >= 0 for item in items)
        assert all(item['failure_code'] is None for item in items)
        assert all(
            item['allowed_actions']
            == [
                {
                    'action_code': 'admin.integration.health_check',
                    'availability': 'available',
                    'expected_revision': None,
                    'reason': None,
                }
            ]
            for item in items
        )


def test_admin_integration_detail_runs_one_bounded_health_check() -> None:
    with _client() as client:
        denied = client.get('/internal/v1/admin/integrations/assessor_service')
        assert denied.status_code == 401

        response = client.get(
            '/internal/v1/admin/integrations/assessor_service',
            headers=_admin_headers(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload['integration_id'] == 'assessor_service'
        assert payload['capability'] == 'assessor_routing'
        assert payload['health'] == 'using_fixture'
        assert payload['source'] == 'fixture'
        assert payload['latency_ms'] >= 0
        assert payload['failure_code'] is None
        assert payload['allowed_actions'][0]['action_code'] == 'admin.integration.health_check'
        assert payload['allowed_actions'][0]['availability'] == 'available'


def test_admin_integration_detail_rejects_unknown_registration() -> None:
    with _client() as client:
        response = client.get(
            '/internal/v1/admin/integrations/not_registered',
            headers=_admin_headers(),
        )
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'INTEGRATION_NOT_FOUND'


def test_admin_integration_health_check_is_recorded_and_readable() -> None:
    with _client() as client:
        checked = client.post(
            '/internal/v1/admin/integrations/assessor_service/health-check',
            headers={**_admin_headers(), 'Idempotency-Key': 'health-check-1'},
        )
        assert checked.status_code == 200
        record = checked.json()
        assert record['integration_id'] == 'assessor_service'
        assert record['health'] == 'using_fixture'
        assert record['source'] == 'fixture'
        assert record['failure_code'] is None
        assert record['operation_id'].startswith('opr_')

        replay = client.post(
            '/internal/v1/admin/integrations/assessor_service/health-check',
            headers={**_admin_headers(), 'Idempotency-Key': 'health-check-1'},
        )
        assert replay.status_code == 200
        assert replay.json() == record

        operation = client.get(
            f'/internal/v1/admin/operations/{record["operation_id"]}',
            headers=_admin_headers(),
        )
        assert operation.status_code == 200
        assert operation.json()['state'] == 'succeeded'
        assert operation.json()['result']['check_id'] == record['check_id']

        operations = client.get('/internal/v1/admin/operations', headers=_admin_headers())
        assert operations.status_code == 200
        assert operations.json()['items'][0]['operation_id'] == record['operation_id']
        metrics = client.get('/internal/v1/admin/operations/metrics', headers=_admin_headers())
        assert metrics.status_code == 200
        assert metrics.json()['total'] >= 1
        assert metrics.json()['by_state']['succeeded'] >= 1

        history = client.get(
            '/internal/v1/admin/integrations/assessor_service/health-checks',
            headers=_admin_headers(),
        )
        assert history.status_code == 200
        assert history.json()['items'][0] == record


def test_admin_integration_health_exposes_bounded_unavailable_failure() -> None:
    with _client() as client:
        adapter = cast(Any, client.app).state.handoff_dispatch_adapter
        adapter.set_outage(HandoffDispatchUnavailable('TIMEOUT', 'fixture outage'))

        response = client.get(
            '/internal/v1/admin/integrations/handoff_dispatch',
            headers=_admin_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload['health'] == 'unavailable'
    assert payload['source'] == 'unavailable'
    assert payload['failure_code'] == 'INTEGRATION_UNAVAILABLE'
    assert payload['latency_ms'] >= 0


def test_sqlite_health_history_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / 'health.sqlite3'
    record = IntegrationHealthCheckRecord(
        check_id='ihc_persisted',
        integration_id='assessor_service',
        health=IntegrationHealthState.USING_FIXTURE,
        source='fixture',
        implementation='MockAssessorServiceAdapter',
        latency_ms=1.25,
        checked_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    SQLiteIntegrationHealthRepository(str(path)).create(record)
    reopened = SQLiteIntegrationHealthRepository(str(path))
    assert reopened.list('assessor_service') == [record]


def test_admin_integration_list_links_published_configuration_and_paginates() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers={**_admin_headers(), 'Idempotency-Key': 'integration-config-create'},
            json={
                'domain': 'integration',
                'values': {
                    'service_id': 'assessor_service',
                    'capability': 'assessor_routing',
                    'source': 'fixture',
                },
                'reason': 'Register assessor integration metadata.',
            },
        )
        assert created.status_code == 201
        configuration_id = created.json()['configuration_id']
        validated = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers={
                **_admin_headers(),
                'Idempotency-Key': 'integration-config-validate',
                'If-Match': '"1"',
            },
            json={
                'scenario_results': [
                    {'scenario_id': 'integration-config', 'outcome': 'passed', 'evidence': 'passed'}
                ]
            },
        )
        assert validated.status_code == 200
        assert validated.json()['state'] == 'published'

        first = client.get('/internal/v1/admin/integrations?limit=1', headers=_admin_headers())
        assert first.status_code == 200
        assert len(first.json()['items']) == 1
        assert first.json()['page']['next_cursor'] is not None

        all_items = client.get('/internal/v1/admin/integrations', headers=_admin_headers())
        assessor = next(
            item
            for item in all_items.json()['items']
            if item['integration_id'] == 'assessor_service'
        )
        assert assessor['configuration_ids'] == [configuration_id]


def test_publishing_one_integration_does_not_supersede_another_service() -> None:
    with _client() as client:
        published_ids: dict[str, str] = {}
        for service_id, capability in (
            ('assessor_service', 'assessor_routing'),
            ('handoff_dispatch', 'handoff_dispatch'),
        ):
            created = client.post(
                '/internal/v1/admin/configurations',
                headers={
                    **_admin_headers(),
                    'Idempotency-Key': f'{service_id}-configuration-create',
                },
                json={
                    'domain': 'integration',
                    'values': {
                        'service_id': service_id,
                        'capability': capability,
                        'source': 'fixture',
                    },
                    'reason': f'Register {service_id}.',
                },
            )
            assert created.status_code == 201
            configuration_id = created.json()['configuration_id']
            validated = client.post(
                f'/internal/v1/admin/configurations/{configuration_id}/validate',
                headers={
                    **_admin_headers(),
                    'Idempotency-Key': f'{service_id}-configuration-validate',
                    'If-Match': '"1"',
                },
                json={
                    'scenario_results': [
                        {
                            'scenario_id': f'{service_id}-configuration',
                            'outcome': 'passed',
                            'evidence': 'passed',
                        }
                    ]
                },
            )
            assert validated.status_code == 200
            assert validated.json()['state'] == 'published'
            published_ids[service_id] = configuration_id

        configurations = client.get(
            '/internal/v1/admin/configurations',
            headers=_admin_headers(),
        ).json()['items']
        state_by_id = {item['configuration_id']: item['state'] for item in configurations}
        assert state_by_id[published_ids['assessor_service']] == 'published'
        assert state_by_id[published_ids['handoff_dispatch']] == 'published'

        integrations = client.get(
            '/internal/v1/admin/integrations',
            headers=_admin_headers(),
        ).json()['items']
        configuration_ids_by_service = {
            item['integration_id']: item['configuration_ids'] for item in integrations
        }
        assert configuration_ids_by_service['assessor_service'] == [
            published_ids['assessor_service']
        ]
        assert configuration_ids_by_service['handoff_dispatch'] == [
            published_ids['handoff_dispatch']
        ]

        cross_service_rollback = client.post(
            f'/internal/v1/admin/configurations/{published_ids["assessor_service"]}/rollback',
            headers={
                **_admin_headers(),
                'Idempotency-Key': 'cross-service-rollback',
                'If-Match': '"2"',
            },
            json={
                'reason': 'Reject a rollback across service identities.',
                'rollback_target': published_ids['handoff_dispatch'],
            },
        )
        assert cross_service_rollback.status_code == 400
        assert cross_service_rollback.json()['error']['code'] == 'INVALID_ROLLBACK_TARGET'


def test_integration_draft_patch_updates_the_publication_key() -> None:
    with _client() as client:
        created = client.post(
            '/internal/v1/admin/configurations',
            headers={**_admin_headers(), 'Idempotency-Key': 'integration-patch-create'},
            json={
                'domain': 'integration',
                'values': {
                    'service_id': 'assessor_service',
                    'capability': 'assessor_routing',
                    'source': 'fixture',
                },
                'reason': 'Create a draft integration.',
            },
        )
        configuration_id = created.json()['configuration_id']

        patched = client.patch(
            f'/internal/v1/admin/configurations/{configuration_id}',
            headers={
                **_admin_headers(),
                'Idempotency-Key': 'integration-patch-update',
                'If-Match': '"1"',
            },
            json={
                'values': {
                    'service_id': 'handoff_dispatch',
                    'capability': 'handoff_dispatch',
                    'source': 'fixture',
                },
                'reason': 'Retarget the unpublished draft.',
            },
        )

        assert patched.status_code == 200
        assert patched.json()['configuration_key'] == 'handoff_dispatch'


def test_integration_configuration_rejects_unregistered_or_incomplete_values() -> None:
    with _client() as client:
        unknown = client.post(
            '/internal/v1/admin/configurations',
            headers={**_admin_headers(), 'Idempotency-Key': 'unknown-integration'},
            json={
                'domain': 'integration',
                'values': {
                    'service_id': 'unknown_service',
                    'capability': 'unknown',
                    'source': 'configured_service',
                },
                'reason': 'Reject an unregistered integration.',
            },
        )
        incomplete = client.post(
            '/internal/v1/admin/configurations',
            headers={**_admin_headers(), 'Idempotency-Key': 'incomplete-integration'},
            json={
                'domain': 'integration',
                'values': {'service_id': 'assessor_service'},
                'reason': 'Reject incomplete integration metadata.',
            },
        )

    assert unknown.status_code == 422
    assert unknown.json()['error']['code'] == 'INTEGRATION_CONFIGURATION_INVALID'
    assert incomplete.status_code == 422
    assert incomplete.json()['error']['code'] == 'INTEGRATION_CONFIGURATION_INVALID'


def test_integration_configuration_rejects_capability_drift() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/configurations',
            headers={**_admin_headers(), 'Idempotency-Key': 'capability-drift'},
            json={
                'domain': 'integration',
                'values': {
                    'service_id': 'assessor_service',
                    'capability': 'claim_creation',
                    'source': 'fixture',
                },
                'reason': 'Reject capability drift from the runtime registry.',
            },
        )
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'INTEGRATION_CONFIGURATION_INVALID'


def test_integration_status_helpers_classify_unsupported_failure_and_pending_adapters() -> None:
    class Unsupported:
        integration_source = 'fixture'

    class Pending:
        integration_source = 'configured_service'

        def connection_status(self) -> str:
            return 'pending_confirmation'

    class Broken:
        def connection_status(self) -> str:
            raise RuntimeError('status failed')

    class Slow:
        def connection_status(self) -> str:
            import time

            time.sleep(0.05)
            return 'verified'

    assert _connection_status(Unsupported(), 0.1) == ('unknown', 'CONNECTION_STATUS_UNSUPPORTED')
    assert _connection_status(Pending(), 0.1) == (
        'pending_confirmation',
        'INTEGRATION_PENDING_CONFIRMATION',
    )
    assert _connection_status(Broken(), 0.1) == ('unknown', 'INTEGRATION_STATUS_FAILED')
    assert _connection_status(Slow(), 0.001) == ('unavailable', 'INTEGRATION_HEALTH_TIMEOUT')
    assert _health_state('not-a-health-state').value == 'unknown'
    assert _source(Unsupported(), _health_state('using_fixture')) == 'fixture'
    assert _source(Pending(), _health_state('pending_confirmation')) == 'unavailable'


def test_unknown_integration_health_check_fails_and_records_operation_failure() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/integrations/not_registered/health-check',
            headers={**_admin_headers(), 'Idempotency-Key': 'unknown-health-check'},
        )
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'INTEGRATION_NOT_FOUND'
