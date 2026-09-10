import asyncio
import base64
from hashlib import sha256
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.adapters.evidence_storage import (
    MAX_UPLOAD_SIZE_BYTES,
    EvidenceStorageUnavailable,
    EvidenceUploadNotFound,
    EvidenceUploadSizeMismatch,
    MockEvidenceStorage,
)
from backend.api.evidence import _read_bounded_upload
from backend.api.workbench import _evidence_storage_key, _safe_download_filename
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
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


def test_download_filename_removes_response_header_control_characters() -> None:
    assert _safe_download_filename('damage\r\nX-Injected: yes.jpg') == 'damageX-Injected: yes.jpg'
    assert _safe_download_filename('"\\') == 'evidence'


def test_fixture_upload_rejects_mismatched_bytes_and_completion_metadata() -> None:
    storage = MockEvidenceStorage()
    storage.create_upload_target(
        claim_id='clm_boundary',
        evidence_id='evd_boundary',
        media_type='image/jpeg',
        size_bytes=4,
    )

    with pytest.raises(EvidenceUploadSizeMismatch):
        storage.put_upload(claim_id='clm_boundary', evidence_id='evd_boundary', content=b'bad')
    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_boundary',
            evidence_id='evd_boundary',
            checksum='sha256:' + 'a' * 64,
            media_type='image/jpeg',
            size_bytes=5,
        )

    storage.put_upload(claim_id='clm_boundary', evidence_id='evd_boundary', content=b'good')
    storage.complete_upload(
        claim_id='clm_boundary',
        evidence_id='evd_boundary',
        checksum=f'sha256:{sha256(b"good").hexdigest()}',
        media_type='image/jpeg',
        size_bytes=4,
    )
    assert (
        storage.read_upload(
            claim_id='clm_boundary',
            evidence_id='evd_boundary',
            storage_key='claims/clm_other/evidence/evd_boundary',
        )
        is None
    )


def test_fixture_upload_target_expires_and_checksum_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MockEvidenceStorage()
    target = storage.create_upload_target(
        claim_id='clm_expiry',
        evidence_id='evd_expiry',
        media_type='image/png',
        size_bytes=4,
    )
    monkeypatch.setattr('backend.adapters.evidence_storage.now_utc', lambda: target.expires_at)
    with pytest.raises(EvidenceUploadNotFound):
        storage.put_upload(claim_id='clm_expiry', evidence_id='evd_expiry', content=b'data')

    storage = MockEvidenceStorage()
    storage.create_upload_target(
        claim_id='clm_checksum',
        evidence_id='evd_checksum',
        media_type='image/png',
        size_bytes=4,
    )
    storage.put_upload(claim_id='clm_checksum', evidence_id='evd_checksum', content=b'BBBB')
    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_checksum',
            evidence_id='evd_checksum',
            checksum=f'sha256:{sha256(b"AAAA").hexdigest()}',
            media_type='image/png',
            size_bytes=4,
        )


def test_storage_key_lookup_returns_none_for_unknown_claim_or_evidence(
    storage_client: TestClient, storage_repository: FixtureRepository
) -> None:
    assert _evidence_storage_key(storage_repository, 'clm_missing', 'evd_missing') is None
    with storage_client as client:
        claim_id = create_claim(client, 'storage-key-lookup-claim')
    assert _evidence_storage_key(storage_repository, claim_id, 'evd_missing') is None


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


def test_fixture_proxy_rejects_more_than_registered_size_without_storing_it(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    with storage_client as client:
        claim_id = create_claim(client, 'bounded-proxy-claim')
        requested = request_upload(client, claim_id, 'bounded-proxy-upload')
        evidence_id = requested.json()['evidence_id']
        oversized = client.put(
            requested.json()['upload']['url'],
            headers={**CLAIMANT_AUTH, 'Content-Type': 'image/jpeg'},
            content=iter([b'x' * cast(int, UPLOAD_PAYLOAD['size_bytes']), b'one-byte-too-many']),
        )

    assert oversized.status_code == 422
    assert oversized.json()['error']['code'] == 'VALIDATION_ERROR'
    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            checksum=f'sha256:{sha256(b"x").hexdigest()}',
            media_type='image/jpeg',
            size_bytes=cast(int, UPLOAD_PAYLOAD['size_bytes']),
        )


def test_fixture_proxy_stream_is_bounded_by_global_maximum_without_content_length(
    storage_client: TestClient,
) -> None:
    with storage_client as client:
        claim_id = create_claim(client, 'global-bound-claim')
        requested = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads',
            headers={
                **CLAIMANT_AUTH,
                'Idempotency-Key': 'global-bound-upload',
                'If-Match': '1',
            },
            json={
                **UPLOAD_PAYLOAD,
                'size_bytes': MAX_UPLOAD_SIZE_BYTES,
            },
        )
        response = client.put(
            requested.json()['upload']['url'],
            headers={**CLAIMANT_AUTH, 'Content-Type': 'image/jpeg'},
            content=iter([b'x' * MAX_UPLOAD_SIZE_BYTES, b'one-byte-too-many']),
        )

    assert response.status_code == 413
    assert response.json()['error']['code'] == 'UPLOAD_TOO_LARGE'


def test_stream_without_content_length_stops_at_registered_and_global_bounds() -> None:
    async def read_with_chunks(chunks: list[bytes], expected_size: int, max_size: int) -> bytes:
        messages = [
            {
                'type': 'http.request',
                'body': chunk,
                'more_body': index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ]

        async def receive() -> dict[str, object]:
            return messages.pop(0)

        request = Request(
            {'type': 'http', 'method': 'PUT', 'path': '/', 'headers': []},
            receive,
        )
        return await _read_bounded_upload(
            request,
            expected_size_bytes=expected_size,
            max_size_bytes=max_size,
        )

    with pytest.raises(ApiError) as registered_error:
        asyncio.run(read_with_chunks([b'abcd', b'e'], expected_size=4, max_size=8))
    assert registered_error.value.status_code == 422

    with pytest.raises(ApiError) as global_error:
        asyncio.run(
            read_with_chunks(
                [b'x' * MAX_UPLOAD_SIZE_BYTES, b'y'],
                expected_size=MAX_UPLOAD_SIZE_BYTES,
                max_size=MAX_UPLOAD_SIZE_BYTES,
            )
        )
    assert global_error.value.status_code == 413


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
            json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
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


def test_staff_evidence_content_returns_clear_not_found_and_storage_outage_errors(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    with storage_client as client:
        claim_id = create_claim(client, 'staff-evidence-errors-claim')
        missing_content = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/evd_missing/content',
            headers=STAFF_AUTH,
        )
        missing_data = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/evd_missing/content-data',
            headers=STAFF_AUTH,
        )

        requested = request_upload(client, claim_id, 'staff-evidence-errors-upload')
        evidence_id = requested.json()['evidence_id']
        storage.set_outage(
            EvidenceStorageUnavailable(code='STORAGE_UNAVAILABLE', detail='Object store is down.')
        )
        unavailable_content = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=STAFF_AUTH,
        )
        unavailable_data = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content-data',
            headers=STAFF_AUTH,
        )

    assert missing_content.status_code == 404
    assert missing_data.status_code == 404
    assert unavailable_content.status_code == 503
    assert unavailable_content.json()['error']['retryable'] is True
    assert unavailable_data.status_code == 503
    assert unavailable_data.json()['error']['retryable'] is True


def test_staff_evidence_content_is_not_available_after_fixture_storage_reset(
    storage_client: TestClient,
    storage: MockEvidenceStorage,
) -> None:
    with storage_client as client:
        claim_id = create_claim(client, 'staff-evidence-reset-claim')
        requested = request_upload(client, claim_id, 'staff-evidence-reset-upload')
        evidence_id = requested.json()['evidence_id']
        storage.reset_demo_state()

        content = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=STAFF_AUTH,
        )
        content_data = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content-data',
            headers=STAFF_AUTH,
        )

    assert content.status_code == 404
    assert content_data.status_code == 404


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
                'status': 'pending',
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
