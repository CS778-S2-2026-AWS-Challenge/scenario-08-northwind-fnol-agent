from datetime import timedelta
from hashlib import sha256
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.domain.models import SessionStatus
from backend.repositories.fixture import FixtureRepository

PROPOSED_FIELD_CODE = 'incident.description'
PROPOSED_VALUE = 'Rear panel damage shown in the supplied evidence.'


def _pause_active_session(repository: FixtureRepository, claim_id: str) -> int:
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.active_session_id is not None
    session = repository.get_session(claim_id, claim.active_session_id, 'cus_demo')
    assert session is not None

    repository.save_session(session.model_copy(update={'status': SessionStatus.PAUSED}))
    updated = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': claim.updated_at + timedelta(minutes=1),
        }
    )
    # Pausing clears WorkingClaim.active_session_id, and
    # docs/claim-state-transaction-boundary.md reserves pointer changes for the
    # resume/start session mutation, so save_claim() correctly rejects it. No
    # production path performs a pause, so this is fixture seeding rather than a
    # repository operation.
    repository._claims[claim.claim_id] = updated
    return updated.revision


def test_new_session_preserves_saved_evidence_state_provenance_and_visibility(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'day5-evidence-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    assert isinstance(claim_id, str)
    assert isinstance(original_session_id, str)
    assert created.json()['claim']['revision'] == 1

    requested = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **auth_headers,
            'Idempotency-Key': 'day5-evidence-upload',
            'If-Match': '1',
        },
        json={
            'kind': 'incident_image',
            'original_filename': 'day5-damage.jpg',
            'media_type': 'image/jpeg',
            'size_bytes': 2048,
        },
    )
    assert requested.status_code == 201
    evidence_id = requested.json()['evidence_id']
    assert isinstance(evidence_id, str)
    assert requested.json()['revision'] == 2

    content = b'a' * 2048
    storage = cast(MockEvidenceStorage, cast(Any, client.app).state.evidence_storage)
    storage.put_upload(claim_id=claim_id, evidence_id=evidence_id, content=content)
    checksum = f'sha256:{sha256(content).hexdigest()}'
    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **auth_headers,
            'Idempotency-Key': 'day5-evidence-complete',
            'If-Match': '2',
        },
        json={'upload_checksum': checksum},
    )
    assert completed.status_code == 202
    assert completed.json()['revision'] == 3
    assert completed.json()['evidence']['status'] == 'received'
    assert completed.json()['evidence']['file_status'] == 'processing'
    assert completed.json()['evidence']['source'] == 'claimant'
    assert 'provenance' not in completed.json()['evidence']

    processed = client.post(
        f'/internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing',
        headers={
            'Authorization': 'Bearer synthetic-integration',
            'Idempotency-Key': 'day5-evidence-processing',
            'If-Match': '3',
        },
        json={
            'facts': [
                {
                    'field_code': PROPOSED_FIELD_CODE,
                    'value': PROPOSED_VALUE,
                    'confidence': 0.87,
                }
            ]
        },
    )
    assert processed.status_code == 200
    assert processed.json()['revision'] == 4
    assert processed.json()['file_status'] == 'ready'
    proposal = processed.json()['proposed_fields'][PROPOSED_FIELD_CODE]
    assert proposal['status'] == 'proposed'
    assert proposal['source'] == 'image'
    assert proposal['source_refs'] == [evidence_id]

    stored_before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    claim_before = repository.get_claim(claim_id, 'cus_demo')
    assert stored_before is not None
    assert claim_before is not None
    before_payload = stored_before.model_dump(mode='json')
    before_proposed = claim_before.form[PROPOSED_FIELD_CODE].model_dump(mode='json')
    assert stored_before.provenance['upload_checksum'] == checksum
    assert stored_before.provenance['storage_key']

    assert _pause_active_session(repository, claim_id) == 5

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'day5-evidence-resume'},
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    resumed_body = cast(dict[str, Any], resumed.json())
    resumed_session_id = resumed_body['session_id']
    assert isinstance(resumed_session_id, str)
    assert resumed_session_id != original_session_id

    current_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_after = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert current_claim is not None
    assert stored_after is not None
    assert current_claim.revision == 6
    assert current_claim.active_session_id == resumed_session_id
    assert current_claim.evidence_summary.received == 1
    assert current_claim.evidence_summary.pending == 0
    assert stored_after.model_dump(mode='json') == before_payload

    # The facts proposed by processing survive the session boundary as proposals.
    # Resume must not confirm, discard, or rewrite a claimant decision that has
    # not been made yet.
    assert current_claim.form[PROPOSED_FIELD_CODE].model_dump(mode='json') == before_proposed
    assert current_claim.form[PROPOSED_FIELD_CODE].status.value == 'proposed'
    assert current_claim.form[PROPOSED_FIELD_CODE].source_refs == [evidence_id]

    claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_claim.status_code == 200
    assert claimant_claim.json()['form'][PROPOSED_FIELD_CODE]['status'] == 'proposed'
    assert claimant_claim.json()['revision'] == 6

    claimant_evidence = client.get(
        f'/api/v1/claims/{claim_id}/evidence',
        headers=auth_headers,
    )
    assert claimant_evidence.status_code == 200
    claimant_items = claimant_evidence.json()['items']
    assert len(claimant_items) == 1
    assert claimant_items[0]['evidence_id'] == evidence_id
    assert claimant_items[0]['status'] == 'received'
    assert claimant_items[0]['file_status'] == 'ready'
    assert claimant_items[0]['source'] == 'claimant'
    assert 'provenance' not in claimant_items[0]
    assert claimant_evidence.json()['revision'] == 6

    staff_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert staff_detail.status_code == 200
    staff_evidence = next(
        item for item in staff_detail.json()['evidence'] if item['evidence_id'] == evidence_id
    )
    assert staff_evidence['status'] == 'received'
    assert staff_evidence['file_status'] == 'ready'
    assert staff_evidence['source'] == 'claimant'
    assert staff_evidence['provenance'] == before_payload['provenance']
    assert staff_detail.json()['revision'] == 6

    sessions = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    assert len(sessions) == 2
    assert sum(session.status is SessionStatus.ACTIVE for session in sessions) == 1
    assert all(session.claim_id == claim_id for session in sessions)
