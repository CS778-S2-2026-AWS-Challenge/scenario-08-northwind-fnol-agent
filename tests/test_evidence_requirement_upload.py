from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import EvidenceStorageUnavailable, MockEvidenceStorage
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.fixture import FixtureRepository


def _create_claim(client: TestClient, headers: dict[str, str], key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(response.json()['claim']['claim_id'])


def _upload_payload(evidence_id: str, *, kind: str = 'repair_quote') -> dict[str, object]:
    return {
        'evidence_id': evidence_id,
        'kind': kind,
        'original_filename': 'replacement-quote.pdf',
        'media_type': 'application/pdf',
        'size_bytes': 8,
    }


def test_upload_targets_existing_requirement_and_preserves_metadata(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(client, auth_headers, 'requirement-upload-claim')
    requirement = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'register-repair-quote',
            'If-Match': '1',
        },
        json={
            'kind': 'repair_quote',
            'status': 'missing',
            'related_fields': ['incident.description'],
            'needed_for': ['current_action'],
            'claimant_note': 'A repair quote is required for the current step.',
        },
    )
    assert requirement.status_code == 201
    original = requirement.json()['evidence']
    evidence_id = str(original['evidence_id'])
    upload_headers = {
        **auth_headers,
        'Idempotency-Key': 'upload-existing-repair-quote',
        'If-Match': '2',
    }

    requested = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers=upload_headers,
        json=_upload_payload(evidence_id),
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers=upload_headers,
        json=_upload_payload(evidence_id),
    )

    assert requested.status_code == 201
    assert requested.json()['evidence_id'] == evidence_id
    assert replay.status_code == 201
    assert replay.json() == requested.json()
    listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()['items']) == 1
    awaiting = listed.json()['items'][0]
    assert awaiting['evidence_id'] == evidence_id
    assert awaiting['status'] == 'pending'
    assert awaiting['file_status'] == 'awaiting_upload'
    assert awaiting['related_fields'] == original['related_fields']
    assert awaiting['needed_for'] == original['needed_for']
    assert awaiting['claimant_note'] == original['claimant_note']
    assert awaiting['created_at'] == original['created_at']

    content = b'quote-v1'
    storage = cast(MockEvidenceStorage, cast(FastAPI, client.app).state.evidence_storage)
    storage.put_upload(claim_id=claim_id, evidence_id=evidence_id, content=content)
    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': 'complete-existing-repair-quote',
            'If-Match': '3',
        },
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )

    assert completed.status_code == 202
    completed_item = completed.json()['evidence']
    assert completed_item['evidence_id'] == evidence_id
    assert completed_item['status'] == 'received'
    assert completed_item['file_status'] == 'processing'
    assert completed_item['related_fields'] == original['related_fields']
    assert completed_item['needed_for'] == original['needed_for']
    assert completed_item['claimant_note'] == original['claimant_note']
    assert len(repository.list_evidence(claim_id, 'cus_demo')) == 1
    stored = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert stored is not None
    assert stored.provenance['transition_history'][-2]['to'] == 'awaiting_upload'
    assert stored.provenance['transition_history'][-2]['actor_id'] == 'cus_demo'
    assert stored.provenance['transition_history'][-1]['to'] == 'processing'


@pytest.mark.parametrize(
    ('status', 'file_status'),
    [
        (EvidenceStatus.RECEIVED, EvidenceFileStatus.FAILED),
        (EvidenceStatus.INVALID, EvidenceFileStatus.READY),
    ],
)
def test_upload_replaces_failed_or_invalid_material_on_the_same_identity(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    status: EvidenceStatus,
    file_status: EvidenceFileStatus,
) -> None:
    claim_id = _create_claim(client, auth_headers, f'replace-{status.value}-{file_status.value}')
    timestamp = datetime.now(UTC)
    evidence = EvidenceRecord(
        evidence_id=f'evd_{status.value}_{file_status.value}',
        claim_id=claim_id,
        kind='repair_quote',
        status=status,
        file_status=file_status,
        original_filename='old-quote.pdf',
        media_type='application/pdf',
        size_bytes=4,
        source=EvidenceSource.CLAIMANT,
        related_fields=['incident.description'],
        needed_for=['current_action'],
        claimant_note='Replace this unusable quote.',
        provenance={'upload_checksum': 'sha256:old'},
        created_at=timestamp,
        updated_at=timestamp,
    )
    repository.save_evidence(evidence, 'cus_demo')

    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': f'replace-{status.value}-{file_status.value}',
            'If-Match': '1',
        },
        json=_upload_payload(evidence.evidence_id),
    )

    assert response.status_code == 201
    assert response.json()['evidence_id'] == evidence.evidence_id
    replaced = repository.get_evidence(claim_id, evidence.evidence_id, 'cus_demo')
    assert replaced is not None
    assert replaced.file_status is EvidenceFileStatus.AWAITING_UPLOAD
    assert replaced.status is EvidenceStatus.PENDING
    assert replaced.related_fields == evidence.related_fields
    assert replaced.needed_for == evidence.needed_for
    assert replaced.claimant_note == evidence.claimant_note
    assert replaced.created_at == evidence.created_at


def test_existing_requirement_upload_rejects_wrong_claim_kind_and_active_state(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(client, auth_headers, 'requirement-boundary-claim')
    other_claim_id = _create_claim(client, auth_headers, 'requirement-boundary-other-claim')
    requirement = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'requirement-boundary-register',
            'If-Match': '1',
        },
        json={
            'kind': 'repair_quote',
            'status': 'missing',
            'related_fields': ['incident.description'],
            'needed_for': ['current_action'],
            'claimant_note': 'Do not lose this requirement.',
        },
    )
    evidence_id = str(requirement.json()['evidence']['evidence_id'])

    wrong_claim = client.post(
        f'/api/v1/claims/{other_claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'wrong-claim-upload',
            'If-Match': '1',
        },
        json=_upload_payload(evidence_id),
    )
    wrong_kind = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'wrong-kind-upload',
            'If-Match': '2',
        },
        json=_upload_payload(evidence_id, kind='receipt'),
    )
    accepted = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'accepted-requirement-upload',
            'If-Match': '2',
        },
        json=_upload_payload(evidence_id),
    )
    active_state = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'duplicate-active-upload',
            'If-Match': '3',
        },
        json=_upload_payload(evidence_id),
    )

    assert wrong_claim.status_code == 404
    assert wrong_kind.status_code == 422
    assert wrong_kind.json()['error']['code'] == 'VALIDATION_ERROR'
    assert accepted.status_code == 201
    assert active_state.status_code == 409
    assert active_state.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    stored = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert stored is not None
    assert stored.related_fields == ['incident.description']
    assert stored.needed_for == ['current_action']
    assert stored.claimant_note == 'Do not lose this requirement.'


def test_existing_requirement_is_unchanged_when_storage_is_unavailable(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(client, auth_headers, 'requirement-storage-outage-claim')
    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'requirement-storage-outage-register',
            'If-Match': '1',
        },
        json={
            'kind': 'repair_quote',
            'status': 'missing',
            'related_fields': ['incident.description'],
            'needed_for': ['current_action'],
            'claimant_note': 'Keep this requirement through an outage.',
        },
    )
    assert registered.status_code == 201
    evidence_id = str(registered.json()['evidence']['evidence_id'])
    before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    claim_before = repository.get_claim(claim_id, 'cus_demo')
    storage = cast(MockEvidenceStorage, cast(FastAPI, client.app).state.evidence_storage)
    storage.set_outage(
        EvidenceStorageUnavailable(
            code='STORAGE_UNAVAILABLE',
            detail='The object store refused the connection.',
        )
    )

    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'requirement-storage-outage-upload',
            'If-Match': '2',
        },
        json=_upload_payload(evidence_id),
    )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert response.json()['error']['retryable'] is True
    assert repository.get_evidence(claim_id, evidence_id, 'cus_demo') == before
    assert repository.get_claim(claim_id, 'cus_demo') == claim_before


@pytest.mark.parametrize(
    ('status', 'file_status', 'source'),
    [
        (EvidenceStatus.INVALID, EvidenceFileStatus.PROCESSING, EvidenceSource.CLAIMANT),
        (EvidenceStatus.SUPERSEDED, EvidenceFileStatus.FAILED, EvidenceSource.CLAIMANT),
        (EvidenceStatus.MISSING, EvidenceFileStatus.NOT_AVAILABLE, EvidenceSource.STAFF),
    ],
)
def test_existing_requirement_upload_rejects_ineligible_identity_or_state(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    status: EvidenceStatus,
    file_status: EvidenceFileStatus,
    source: EvidenceSource,
) -> None:
    claim_id = _create_claim(
        client,
        auth_headers,
        f'ineligible-{status.value}-{file_status.value}-{source.value}',
    )
    timestamp = datetime.now(UTC)
    evidence = EvidenceRecord(
        evidence_id=f'evd_{status.value}_{file_status.value}_{source.value}',
        claim_id=claim_id,
        kind='repair_quote',
        status=status,
        file_status=file_status,
        source=source,
        related_fields=['incident.description'],
        needed_for=['current_action'],
        claimant_note='This metadata must remain unchanged.',
        created_at=timestamp,
        updated_at=timestamp,
    )
    repository.save_evidence(evidence, 'cus_demo')

    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': f'ineligible-{status.value}-{file_status.value}-{source.value}',
            'If-Match': '1',
        },
        json=_upload_payload(evidence.evidence_id),
    )

    assert response.status_code == (404 if source is EvidenceSource.STAFF else 409)
    assert repository.get_evidence(claim_id, evidence.evidence_id, 'cus_demo') == evidence
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.revision == 1
