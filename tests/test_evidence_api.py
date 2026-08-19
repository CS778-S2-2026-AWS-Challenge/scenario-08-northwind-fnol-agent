from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import EvidenceUploadNotFound, MockEvidenceStorage
from backend.domain.models import EvidenceFileStatus
from backend.repositories.fixture import FixtureRepository


def create_claim(client: TestClient, auth_headers: dict[str, str], key: str) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_pending_evidence_is_saved_visible_and_does_not_block_current_work(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, 'pending-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    endpoint = f'/api/v1/claims/{claim_id}/evidence'
    headers = {
        **auth_headers,
        'Idempotency-Key': 'pending-police-report',
        'If-Match': '1',
    }
    payload = {
        'kind': 'police_report',
        'status': 'pending_generation',
        'related_fields': ['authorities.police_report_reference'],
        'needed_for': ['later_action'],
        'claimant_note': 'The report will be available next week.',
    }

    response = client.post(endpoint, headers=headers, json=payload)
    replay = client.post(endpoint, headers=headers, json=payload)
    conflict = client.post(endpoint, headers=headers, json={**payload, 'kind': 'receipt'})
    listed = client.get(endpoint, headers=auth_headers)
    read_claim = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert response.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == response.json()
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert listed.status_code == 200
    assert listed.json()['items'] == [response.json()['evidence']]
    assert 'provenance' not in listed.json()['items'][0]
    assert read_claim.json()['revision'] == 2
    assert read_claim.json()['workflow_state'] == 'collecting'
    assert read_claim.json()['customer_next_step']['status'] == 'describe_incident'
    assert read_claim.json()['evidence_summary'] == {
        'received': 0,
        'pending': 1,
        'needs_attention': 0,
    }
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.claim_state.evidence.value == 'pending_generation'


@pytest.mark.parametrize(
    'file_status',
    [EvidenceFileStatus.READY, EvidenceFileStatus.NOT_AVAILABLE],
)
def test_incomplete_evidence_remains_in_staff_pending_evidence_view(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    file_status: EvidenceFileStatus,
) -> None:
    created = create_claim(client, auth_headers, f'incomplete-{file_status.value}-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])

    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': f'incomplete-{file_status.value}',
            'If-Match': '1',
        },
        json={
            'kind': 'repair_quote',
            'status': 'incomplete',
            'needed_for': ['later_action'],
            'claimant_note': 'The final page is still required.',
        },
    )
    assert registered.status_code == 201
    evidence_id = registered.json()['evidence']['evidence_id']
    evidence = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert evidence is not None
    if file_status is EvidenceFileStatus.READY:
        repository.save_evidence(
            evidence.model_copy(update={'file_status': EvidenceFileStatus.READY}),
            'cus_demo',
        )

    response = client.get(
        '/api/v1/workbench/claims?view=awaiting_evidence',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )

    assert response.status_code == 200
    item = next(item for item in response.json()['items'] if item['claim_id'] == claim_id)
    assert item['evidence_summary']['needs_attention'] == 1
    assert item['pending_evidence_count'] == 1
    assert item['pending_wait_types'] == ['claimant']
    assert item['pending_evidence'][0]['status'] == 'incomplete'
    assert item['pending_evidence'][0]['file_status'] == file_status.value
    assert item['pending_evidence'][0]['responsible_party'] == 'claimant'
    assert item['pending_evidence'][0]['context_summary'] == 'Needed for: later_action'


@pytest.mark.parametrize(
    ('kind', 'filename', 'media_type', 'size_bytes'),
    [
        ('incident_image', 'rear-damage.jpg', 'image/jpeg', 1_842_201),
        ('repair_quote', 'repair-quote.pdf', 'application/pdf', 284_120),
    ],
)
def test_upload_completion_exposes_processing_metadata_without_storage_details(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    kind: str,
    filename: str,
    media_type: str,
    size_bytes: int,
) -> None:
    fixture_key = media_type.replace('/', '-')
    created = create_claim(client, auth_headers, f'{fixture_key}-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    upload_endpoint = f'/api/v1/claims/{claim_id}/evidence/uploads'
    upload_headers = {
        **auth_headers,
        'Idempotency-Key': f'upload-{fixture_key}',
        'If-Match': '1',
    }
    upload_payload = {
        'kind': kind,
        'original_filename': filename,
        'media_type': media_type,
        'size_bytes': size_bytes,
    }

    requested = client.post(upload_endpoint, headers=upload_headers, json=upload_payload)
    replay = client.post(upload_endpoint, headers=upload_headers, json=upload_payload)

    assert requested.status_code == 201
    assert replay.json() == requested.json()
    upload = requested.json()
    evidence_id = upload['evidence_id']
    assert upload['revision'] == 2
    assert upload['upload']['method'] == 'PUT'
    assert upload['upload']['headers'] == {'Content-Type': media_type}
    assert media_type in upload['constraints']['allowed_media_types']
    stored_before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert stored_before is not None
    assert stored_before.file_status.value == 'awaiting_upload'
    assert 'url' not in stored_before.provenance

    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': f'complete-{fixture_key}',
            'If-Match': '2',
        },
        json={'upload_checksum': f'sha256:{"a" * 64}'},
    )
    completion_replay = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': f'complete-{fixture_key}',
            'If-Match': '2',
        },
        json={'upload_checksum': f'sha256:{"a" * 64}'},
    )
    completion_conflict = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': f'complete-{fixture_key}',
            'If-Match': '2',
        },
        json={'upload_checksum': f'sha256:{"b" * 64}'},
    )
    second_completion = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': f'complete-{fixture_key}-again',
            'If-Match': '3',
        },
        json={'upload_checksum': f'sha256:{"a" * 64}'},
    )

    listed = client.get(
        f'/api/v1/claims/{claim_id}/evidence',
        headers=auth_headers,
    )
    workbench = client.get(
        '/api/v1/workbench/claims?view=awaiting_evidence',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )

    assert completed.status_code == 202
    body = completed.json()
    assert completion_replay.json() == body
    assert completion_conflict.status_code == 409
    assert second_completion.status_code == 409
    assert second_completion.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert body['revision'] == 3
    assert body['evidence']['status'] == 'received'
    assert body['evidence']['file_status'] == 'processing'
    assert body['evidence']['original_filename'] == filename
    assert body['evidence']['media_type'] == media_type
    assert body['evidence']['size_bytes'] == size_bytes
    assert 'provenance' not in body['evidence']
    assert listed.status_code == 200
    assert listed.json()['items'] == [body['evidence']]
    assert workbench.status_code == 200
    workbench_item = next(
        item for item in workbench.json()['items'] if item['claim_id'] == claim_id
    )
    assert workbench_item['pending_wait_types'] == ['internal']
    assert workbench_item['pending_evidence_count'] == 1
    assert workbench_item['pending_evidence'][0]['status'] == 'received'
    assert workbench_item['pending_evidence'][0]['file_status'] == 'processing'
    assert workbench_item['pending_evidence'][0]['wait_type'] == 'internal'
    assert workbench_item['pending_evidence'][0]['responsible_party'] == 'northwind'
    assert workbench_item['pending_evidence'][0]['context_summary'] == (
        'Northwind is processing the completed evidence upload.'
    )
    assert 'claimant' not in workbench_item['pending_wait_types']
    assert 'Waiting for the claimant' not in str(workbench_item['pending_evidence'])
    public_payload = listed.text
    assert 'storage_key' not in public_payload
    assert 'upload_checksum' not in public_payload
    assert 'processing_state' not in public_payload
    assert 'file_contents' not in public_payload
    stored_after = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert stored_after is not None
    assert stored_after.provenance['processing_state'] == 'queued'
    assert stored_after.provenance['storage_key'].endswith(evidence_id)
    updated_claim = repository.get_claim(claim_id, 'cus_demo')
    assert updated_claim is not None
    assert updated_claim.form == {}
    assert updated_claim.evidence_summary.received == 0
    assert updated_claim.evidence_summary.pending == 1


def test_evidence_mutations_enforce_headers_revision_media_and_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, 'evidence-guards')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    endpoint = f'/api/v1/claims/{claim_id}/evidence'
    pending = {'kind': 'police_report', 'status': 'pending_generation'}

    missing_key = client.post(endpoint, headers={**auth_headers, 'If-Match': '1'}, json=pending)
    missing_revision = client.post(
        endpoint,
        headers={**auth_headers, 'Idempotency-Key': 'missing-revision'},
        json=pending,
    )
    received_without_upload = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'received-without-upload',
            'If-Match': '1',
        },
        json={'kind': 'incident_image', 'status': 'received'},
    )
    unsupported = client.post(
        f'{endpoint}/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unsupported-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_audio',
            'original_filename': 'call.wav',
            'media_type': 'audio/wav',
            'size_bytes': 100,
        },
    )
    too_large = client.post(
        f'{endpoint}/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'large-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_image',
            'original_filename': 'large.png',
            'media_type': 'image/png',
            'size_bytes': 10_485_761,
        },
    )

    assert missing_key.status_code == 400
    assert missing_revision.status_code == 409
    assert missing_revision.json()['error']['code'] == 'REVISION_REQUIRED'
    assert received_without_upload.status_code == 422
    assert unsupported.status_code == 415
    assert unsupported.json()['error']['code'] == 'UNSUPPORTED_MEDIA_TYPE'
    assert too_large.status_code == 422


def test_evidence_rejects_stale_revision_and_unknown_completion(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, 'stale-evidence')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'first-evidence',
            'If-Match': '1',
        },
        json={'kind': 'police_report', 'status': 'pending_generation'},
    )
    stale = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'stale-evidence-change',
            'If-Match': '1',
        },
        json={'kind': 'receipt', 'status': 'unofficial'},
    )
    unknown = client.post(
        f'/api/v1/claims/{claim_id}/evidence/evd_missing/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unknown-completion',
            'If-Match': '2',
        },
        json={'upload_checksum': f'sha256:{"b" * 64}'},
    )

    assert registered.status_code == 201
    assert stale.status_code == 409
    assert stale.json()['error']['current_revision'] == 2
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    ('status', 'expected_state'),
    [('unofficial', 'unofficial'), ('inconsistent', 'inconsistent')],
)
def test_attention_evidence_updates_shared_evidence_dimension(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    status: str,
    expected_state: str,
) -> None:
    created = create_claim(client, auth_headers, f'{status}-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])

    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{status}-evidence',
            'If-Match': '1',
        },
        json={'kind': 'receipt', 'status': status},
    )

    assert response.status_code == 201
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.claim_state.evidence.value == expected_state
    assert stored.evidence_summary.needs_attention == 1


def test_unknown_claim_evidence_routes_return_not_found(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    listed = client.get('/api/v1/claims/clm_missing/evidence', headers=auth_headers)
    uploaded = client.post(
        '/api/v1/claims/clm_missing/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'missing-claim-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_image',
            'original_filename': 'missing.png',
            'media_type': 'image/png',
            'size_bytes': 100,
        },
    )
    completed = client.post(
        '/api/v1/claims/clm_missing/evidence/evd_missing/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': 'missing-claim-complete',
            'If-Match': '1',
        },
        json={'upload_checksum': f'sha256:{"c" * 64}'},
    )

    assert listed.status_code == 404
    assert uploaded.status_code == 404
    assert completed.status_code == 404


def test_mock_storage_validates_pending_object_identity() -> None:
    storage = MockEvidenceStorage()
    storage.create_upload_target(
        claim_id='clm_fixture',
        evidence_id='evd_fixture',
        media_type='application/pdf',
        size_bytes=100,
    )

    with pytest.raises(EvidenceUploadNotFound):
        storage.complete_upload(
            claim_id='clm_fixture',
            evidence_id='evd_fixture',
            checksum=f'sha256:{"d" * 64}',
            media_type='application/pdf',
            size_bytes=101,
        )

    completed = storage.complete_upload(
        claim_id='clm_fixture',
        evidence_id='evd_fixture',
        checksum=f'sha256:{"d" * 64}',
        media_type='application/pdf',
        size_bytes=100,
    )
    assert storage.completed_upload('clm_fixture', 'evd_fixture') == completed
