from datetime import datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import EvidenceUploadNotFound, MockEvidenceStorage
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


@pytest.mark.parametrize(
    ('media_type', 'filename', 'decision', 'expected_status', 'expected_source'),
    [
        ('image/jpeg', 'damage.jpg', 'confirmed', 'confirmed', 'image'),
        ('application/pdf', 'statement.pdf', 'rejected', 'disputed', 'document'),
    ],
)
def test_processed_evidence_facts_stay_proposed_until_the_claimant_decides(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    media_type: str,
    filename: str,
    decision: str,
    expected_status: str,
    expected_source: str,
) -> None:
    case = decision
    created = create_claim(client, auth_headers, f'{case}-evidence-fact-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])

    requested = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{case}-evidence-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_image' if expected_source == 'image' else 'claimant_statement',
            'original_filename': filename,
            'media_type': media_type,
            'size_bytes': 512,
        },
    )
    assert requested.status_code == 201
    evidence_id = requested.json()['evidence_id']

    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{case}-evidence-complete',
            'If-Match': '2',
        },
        json={'upload_checksum': f'sha256:{"e" * 64}'},
    )
    assert completed.status_code == 202

    processing_endpoint = f'/internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing'
    processing_headers = {
        'Authorization': 'Bearer synthetic-integration',
        'Idempotency-Key': f'{case}-evidence-processing',
        'If-Match': '3',
    }
    processing_payload = {
        'facts': [
            {
                'field_code': 'incident.description',
                'value': 'Rear panel damage shown in the supplied evidence.',
                'confidence': 0.87,
            }
        ]
    }
    processed = client.post(
        processing_endpoint,
        headers=processing_headers,
        json=processing_payload,
    )
    processing_replay = client.post(
        processing_endpoint,
        headers=processing_headers,
        json=processing_payload,
    )

    assert processed.status_code == 200
    assert processing_replay.json() == processed.json()
    proposal = processed.json()['proposed_fields']['incident.description']
    assert processed.json()['revision'] == 4
    assert processed.json()['file_status'] == 'ready'
    assert proposal['status'] == 'proposed'
    assert proposal['source'] == expected_source
    assert proposal['source_refs'] == [evidence_id]

    before_decision = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )
    assert before_decision.status_code == 200
    assert before_decision.json()['form']['incident.description']['status'] == 'proposed'

    decision_endpoint = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/fact-decisions'
    decision_headers = {
        **auth_headers,
        'Idempotency-Key': f'{case}-evidence-decision',
        'If-Match': '4',
    }
    decision_payload = {
        'field_codes': ['incident.description'],
        'decision': decision,
    }
    decided = client.post(
        decision_endpoint,
        headers=decision_headers,
        json=decision_payload,
    )
    decision_replay = client.post(
        decision_endpoint,
        headers=decision_headers,
        json=decision_payload,
    )

    assert decided.status_code == 200
    assert decision_replay.json() == decided.json()
    updated = decided.json()['updated_fields']['incident.description']
    assert decided.json()['revision'] == 5
    assert updated['status'] == expected_status
    assert updated['source'] == expected_source
    assert updated['source_refs'] == [evidence_id]
    assert updated['updated_at'] >= proposal['updated_at']

    repeated_decision = client.post(
        decision_endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': f'{case}-second-evidence-decision',
            'If-Match': '5',
        },
        json=decision_payload,
    )
    assert repeated_decision.status_code == 422
    assert repeated_decision.json()['error']['code'] == 'VALIDATION_ERROR'

    stored = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert stored is not None
    transitions = stored.provenance['transition_history']
    assert isinstance(transitions, list)
    assert [(entry['from'], entry['to']) for entry in transitions] == [
        ('awaiting_upload', 'processing'),
        ('processing', 'ready'),
        ('processing', 'proposed'),
        ('proposed', decision),
    ]
    fact_transition = transitions[-1]
    assert fact_transition['source'] == expected_source
    proposed_at = datetime.fromisoformat(str(fact_transition['proposed_at']))
    decided_at = datetime.fromisoformat(str(fact_transition['at']))
    assert proposed_at == datetime.fromisoformat(proposal['updated_at'].replace('Z', '+00:00'))
    assert decided_at == datetime.fromisoformat(updated['updated_at'].replace('Z', '+00:00'))


def test_fact_decisions_require_completed_processing_and_the_owning_claimant(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, 'guarded-evidence-fact-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    requested = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'guarded-evidence-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_image',
            'original_filename': 'guarded.jpg',
            'media_type': 'image/jpeg',
            'size_bytes': 512,
        },
    )
    assert requested.status_code == 201
    evidence_id = requested.json()['evidence_id']
    endpoint = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/fact-decisions'
    payload = {'field_codes': ['incident.description'], 'decision': 'confirmed'}

    before_processing = client.post(
        endpoint,
        headers={
            **auth_headers,
            'Idempotency-Key': 'early-evidence-decision',
            'If-Match': '2',
        },
        json=payload,
    )
    integration_credential = client.post(
        endpoint,
        headers={
            'Authorization': 'Bearer synthetic-integration',
            'Idempotency-Key': 'integration-evidence-decision',
            'If-Match': '2',
        },
        json=payload,
    )

    assert before_processing.status_code == 409
    assert before_processing.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert integration_credential.status_code == 403
    assert integration_credential.json()['error']['code'] == 'ACCESS_DENIED'


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
