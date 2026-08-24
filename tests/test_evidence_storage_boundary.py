from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import (
    EvidenceStorageUnavailable,
    MockEvidenceStorage,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)

UPLOAD_PAYLOAD = {
    'kind': 'incident_image',
    'original_filename': 'damage.jpg',
    'media_type': 'image/jpeg',
    'size_bytes': 2048,
}


@pytest.fixture
def storage() -> MockEvidenceStorage:
    return MockEvidenceStorage()


@pytest.fixture
def storage_repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def storage_client(
    storage_repository: FixtureRepository,
    storage: MockEvidenceStorage,
) -> TestClient:
    app = create_app(DEVELOPER_SETTINGS, storage_repository, evidence_storage=storage)
    return TestClient(app)


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def request_upload(client: TestClient, claim_id: str, key: str, revision: int = 1) -> Any:
    return client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
        json=UPLOAD_PAYLOAD,
    )


def test_storage_outage_is_a_retryable_dependency_failure_not_a_rejected_file(
    storage_client: TestClient,
    storage_repository: FixtureRepository,
    storage: MockEvidenceStorage,
) -> None:
    storage.set_outage(
        EvidenceStorageUnavailable(
            code='STORAGE_UNAVAILABLE',
            detail='The object store refused the connection.',
        )
    )

    with storage_client as client:
        claim_id = create_claim(client, 'storage-outage-claim')
        response = request_upload(client, claim_id, 'storage-outage-upload')
        readiness = client.get('/health/ready')

    assert response.status_code == 503
    error = response.json()['error']
    assert error['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert error['retryable'] is True

    # A transport outage must not read as "your file was refused".
    assert error['code'] not in {'UNSUPPORTED_MEDIA_TYPE', 'VALIDATION_ERROR'}

    # The claim is untouched, so the claimant can retry without losing work.
    claim = storage_repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.revision == 1
    assert storage_repository.list_evidence(claim_id, 'cus_demo') == []

    assert readiness.json()['checks']['evidence_storage'] == 'unavailable'


def test_the_fixture_path_still_runs_once_storage_recovers(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    storage.set_outage(
        EvidenceStorageUnavailable(code='STORAGE_UNAVAILABLE', detail='Object store is down.')
    )

    with storage_client as client:
        claim_id = create_claim(client, 'storage-recovery-claim')
        degraded = request_upload(client, claim_id, 'storage-recovery-upload')
        storage.set_outage(None)
        recovered = request_upload(client, claim_id, 'storage-recovery-upload-2')
        readiness = client.get('/health/ready')

    assert degraded.status_code == 503
    # The same request succeeds on the fixture path once the store answers, and
    # the claim advances from the revision it kept during the outage.
    assert recovered.status_code == 201
    assert recovered.json()['revision'] == 2
    assert readiness.json()['checks']['evidence_storage'] == 'using_fixture'


def test_pending_evidence_can_still_be_recorded_while_storage_is_unavailable(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    storage.set_outage(
        EvidenceStorageUnavailable(code='STORAGE_UNAVAILABLE', detail='Object store is down.')
    )

    with storage_client as client:
        claim_id = create_claim(client, 'storage-pending-claim')
        pending = client.post(
            f'/api/v1/claims/{claim_id}/evidence',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'storage-pending-evidence',
                'If-Match': '1',
            },
            json={
                'kind': 'police_report',
                'status': 'pending_generation',
                'related_fields': ['authorities.police_report_reference'],
                'needed_for': ['later_action'],
                'claimant_note': 'The report will be available next week.',
            },
        )

    # Registering evidence the claimant does not yet hold never touches the
    # object store, so an outage must not block the claim from progressing.
    assert pending.status_code == 201
    assert pending.json()['revision'] == 2


def test_demo_reset_clears_storage_state_and_restores_the_adapter(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    storage.set_outage(
        EvidenceStorageUnavailable(code='STORAGE_UNAVAILABLE', detail='Object store is down.')
    )

    with storage_client as client:
        reset = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)
        readiness = client.get('/health/ready')

    assert reset.status_code == 200
    assert 'mock_pending_uploads' in reset.json()['cleared']
    assert readiness.json()['checks']['evidence_storage'] == 'using_fixture'
