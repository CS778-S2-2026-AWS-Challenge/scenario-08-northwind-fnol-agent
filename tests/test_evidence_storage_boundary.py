import base64
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import (
    EvidenceStorageUnavailable,
    MockEvidenceStorage,
)
from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}

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
    app = create_app(Settings(), storage_repository, evidence_storage=storage)
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


def test_claimant_upload_content_is_available_to_authorised_staff(
    storage_client: TestClient,
) -> None:
    upload_size = cast(int, UPLOAD_PAYLOAD['size_bytes'])
    media_type = cast(str, UPLOAD_PAYLOAD['media_type'])
    content = b'fixture-image-bytes' + (b'.' * (upload_size - 19))
    assert len(content) == upload_size

    with storage_client as client:
        claim_id = create_claim(client, 'viewable-evidence-claim')
        requested = request_upload(client, claim_id, 'viewable-evidence-upload')
        assert requested.status_code == 201
        evidence_id = requested.json()['evidence_id']
        uploaded = client.put(
            requested.json()['upload']['url'],
            headers={**CLAIMANT_AUTH, 'Content-Type': media_type},
            content=content,
        )
        completed = client.post(
            f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'viewable-evidence-complete',
                'If-Match': str(requested.json()['revision']),
            },
            json={'upload_checksum': 'sha256:' + ('a' * 64)},
        )
        staff_view = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=STAFF_AUTH,
        )
        staff_data = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content-data',
            headers=STAFF_AUTH,
        )
        claimant_view = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=CLAIMANT_AUTH,
        )

    assert uploaded.status_code == 204
    assert completed.status_code == 202
    assert staff_view.status_code == 200
    assert staff_view.content == content
    assert staff_view.headers['content-type'] == 'image/jpeg'
    assert staff_view.headers['content-disposition'] == 'inline; filename="damage.jpg"'
    assert staff_data.status_code == 200
    assert staff_data.json() == {
        'filename': 'damage.jpg',
        'media_type': 'image/jpeg',
        'base64_data': base64.b64encode(content).decode('ascii'),
    }
    assert claimant_view.status_code == 403


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
