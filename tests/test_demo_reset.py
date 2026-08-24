from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import MockAssessorServiceAdapter, MockClaimsServiceAdapter
from backend.adapters.evidence_storage import (
    MinioEvidenceStorage,
    MockEvidenceStorage,
    S3CompatibleObjectStorageConfig,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import AssessorLocation, CreateExternalClaimRequest, RouteAssessorRequest
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository
from scripts import reset_demo as reset_command

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def _populate_demo(
    client: TestClient,
    claims_adapter: MockClaimsServiceAdapter,
    assessor_adapter: MockAssessorServiceAdapter,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'reset-demo-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim = created.json()['claim']
    session = created.json()['session']

    handoff = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions/{session["session_id"]}/messages',
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': 'reset-demo-handoff',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'reset-demo-handoff',
            'content': {'type': 'text', 'text': 'A passenger is injured.'},
        },
    )
    assert handoff.status_code == 200

    upload = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/evidence/uploads',
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': 'reset-demo-upload',
            'If-Match': str(handoff.json()['claim_revision']),
        },
        json={
            'kind': 'incident_image',
            'original_filename': 'synthetic-reset.png',
            'media_type': 'image/png',
            'size_bytes': 100,
        },
    )
    assert upload.status_code == 201
    completed = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/evidence/{upload.json()["evidence_id"]}/complete',
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': 'reset-demo-complete',
            'If-Match': str(upload.json()['revision']),
        },
        json={'upload_checksum': f'sha256:{"a" * 64}'},
    )
    assert completed.status_code == 202

    claim_outcome = claims_adapter.create_claim(
        CreateExternalClaimRequest(
            working_claim_id='clm_reset_adapter',
            claim_revision=1,
            authorised_decision_id='dec_reset_adapter',
            route='standard_motor_intake',
        ),
        'reset-claim-fingerprint',
    )
    assessor_outcome = assessor_adapter.route_assessor(
        RouteAssessorRequest(
            claim_id='clm_reset_adapter',
            external_claim_id=claim_outcome.result.external_claim_id,
            authorisation_ref='dec_reset_assessor',
            requested_action='route_assessor',
            location=AssessorLocation(region='Auckland'),
        ),
        'reset-assessor-fingerprint',
    )
    assert claim_outcome.replayed is False
    assert assessor_outcome.replayed is False


def test_reset_clears_complete_demo_state_and_repeats_from_the_same_start() -> None:
    repository = FixtureRepository()
    claims_adapter = MockClaimsServiceAdapter()
    assessor_adapter = MockAssessorServiceAdapter()
    storage = MockEvidenceStorage()
    app = create_app(
        DEVELOPER_SETTINGS,
        repository,
        claims_service_adapter=claims_adapter,
        assessor_service_adapter=assessor_adapter,
        evidence_storage=storage,
    )

    with TestClient(app) as client:
        _populate_demo(client, claims_adapter, assessor_adapter)
        first = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)
        assert first.status_code == 200
        assert repository.list_claims_internal() == []
        assert first.json()['cleared']['claims'] == 1
        assert first.json()['cleared']['sessions'] == 1
        assert first.json()['cleared']['evidence'] == 1
        assert first.json()['cleared']['handoffs'] == 1
        assert first.json()['cleared']['idempotency_records'] == 4
        assert first.json()['cleared']['mock_claim_results'] == 1
        assert first.json()['cleared']['mock_assessor_results'] == 1
        assert first.json()['cleared']['mock_pending_uploads'] == 1
        assert first.json()['cleared']['mock_completed_uploads'] == 1

        _populate_demo(client, claims_adapter, assessor_adapter)
        second = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert repository.list_claims_internal() == []


@pytest.mark.parametrize(
    ('token', 'expected_status'),
    [('synthetic-claimant', 403), ('synthetic-integration', 403), ('unknown', 401)],
)
def test_reset_rejects_non_staff_credentials(token: str, expected_status: int) -> None:
    with TestClient(create_app(DEVELOPER_SETTINGS)) as client:
        response = client.post(
            '/api/v1/workbench/demo/reset',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert response.status_code == expected_status
    assert response.json()['error']['code'] in {'ACCESS_DENIED', 'AUTHENTICATION_REQUIRED'}


def test_reset_is_unavailable_outside_the_synthetic_environment() -> None:
    with TestClient(create_app(Settings(environment='production'))) as client:
        response = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_reset_refuses_unknown_persistence_without_touching_mock_results() -> None:
    claims_adapter = MockClaimsServiceAdapter()
    command = CreateExternalClaimRequest(
        working_claim_id='clm_out_of_scope',
        claim_revision=1,
        authorised_decision_id='dec_out_of_scope',
        route='standard_motor_intake',
    )
    claims_adapter.create_claim(command, 'out-of-scope-fingerprint')
    app = create_app(
        DEVELOPER_SETTINGS,
        repository=cast(PersistenceRepository, object()),
        claims_service_adapter=claims_adapter,
    )

    with TestClient(app) as client:
        response = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DEMO_RESET_UNAVAILABLE'
    assert 'No state was cleared' in response.json()['error']['message']
    assert claims_adapter.create_claim(command, 'out-of-scope-fingerprint').replayed is True


def test_reset_fails_closed_for_minio_without_clearing_repository() -> None:
    repository = FixtureRepository()
    storage = MinioEvidenceStorage(
        S3CompatibleObjectStorageConfig(
            endpoint_url='http://localhost:9000',
            access_key_id='synthetic-access',
            secret_access_key='synthetic-secret',
            bucket='northwind-evidence',
        ),
        client=object(),
    )
    app = create_app(DEVELOPER_SETTINGS, repository=repository, evidence_storage=storage)

    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'minio-reset-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        response = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)

    assert created.status_code == 201
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DEMO_RESET_UNAVAILABLE'
    assert len(repository.list_claims_internal()) == 1


def test_reset_command_reports_success_and_actionable_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def success(*_args: object) -> dict[str, object]:
        return {'status': 'reset', 'cleared': {'claims': 1}}

    monkeypatch.setattr(reset_command, 'reset_demo', success)
    assert reset_command.main([]) == 0
    assert 'Demo state reset successfully' in capsys.readouterr().out

    def fail(*_args: object) -> dict[str, object]:
        raise reset_command.ResetCommandError('backend unavailable')

    monkeypatch.setattr(reset_command, 'reset_demo', fail)
    assert reset_command.main([]) == 1
    assert 'ERROR: backend unavailable' in capsys.readouterr().err
