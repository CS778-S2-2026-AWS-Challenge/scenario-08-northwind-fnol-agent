"""INV-18: a claimant who sends a file and says nothing still gets a full turn.

Two provider realities are covered. An image the provider can read: the model
reads the file and records facts sourced to it. A PDF the provider cannot read:
the file is saved and listed for the model as received, the turn still runs,
and the claimant is never shown an error for a document Runtime accepted.
"""

from hashlib import sha256

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import create_claim


def _upload(
    app: FastAPI,
    client: TestClient,
    claim_id: str,
    revision: int,
    *,
    kind: str,
    filename: str,
    media_type: str,
    content: bytes,
    key: str,
) -> tuple[str, int]:
    upload = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={**CLAIMANT, 'Idempotency-Key': f'{key}-upload', 'If-Match': str(revision)},
        json={
            'kind': kind,
            'original_filename': filename,
            'media_type': media_type,
            'size_bytes': len(content),
        },
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()['evidence_id']
    app.state.evidence_storage.put_upload(
        claim_id=claim_id, evidence_id=evidence_id, content=content
    )
    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **CLAIMANT,
            'Idempotency-Key': f'{key}-complete',
            'If-Match': str(upload.json()['revision']),
        },
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    assert completed.status_code == 202, completed.text
    return evidence_id, completed.json()['revision']


def _send_file_only(
    client: TestClient, claim_id: str, session_id: str, revision: int, ref: str
) -> httpx.Response:
    return client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**CLAIMANT, 'Idempotency-Key': f'{ref}-turn', 'If-Match': str(revision)},
        json={'client_message_id': f'{ref}-message', 'evidence_refs': [ref]},
    )


def test_photo_without_text_starts_the_report_and_facts_are_document_sourced(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    created = create_claim(client, CLAIMANT, key='photo-only-claim').json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    evidence_id, revision = _upload(
        app,
        client,
        claim_id,
        created['claim']['revision'],
        kind='incident_image',
        filename='bumper.jpg',
        media_type='image/jpeg',
        content=b'synthetic rear bumper photo',
        key='photo-only',
    )
    scripted = envelope(
        reply=(
            'Thanks for the photo. I can see a car with rear bumper damage, so I will start a '
            'motor claim. Where and when did this happen?'
        ),
        fields=[
            fact('claim.product_family', 'motor', None),
            fact('vehicle.damage_description', 'Rear bumper damaged', None),
        ],
        interpretations=[{'evidence_id': evidence_id, 'document_kind': 'incident_image'}],
        question='incident.location',
    )
    for change in scripted['field_changes']:
        change['source_evidence_id'] = evidence_id
    provider = V8JourneyProvider([scripted])
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)

    response = _send_file_only(client, claim_id, session_id, revision, evidence_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['recovery'] is None
    assert body['agent_message']['content']['text'].startswith('Thanks for the photo.')
    # The model was called once and handed the image.
    assert len(provider.gateway.requests) == 1
    assert any(
        getattr(block, 'evidence_id', None) == evidence_id
        for message in provider.gateway.requests[0].messages
        for block in (message.content_blocks or [])
    )
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    for code in ('claim.product_family', 'vehicle.damage_description'):
        assert claim.form[code].source.value == 'image'
        assert claim.form[code].status.value == 'proposed'
        assert claim.form[code].source_refs == [evidence_id]
    assert claim.incident_type == 'motor'


def test_pdf_the_provider_cannot_read_is_kept_and_acknowledged_not_errored(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    created = create_claim(client, CLAIMANT, key='pdf-only-claim').json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    evidence_id, revision = _upload(
        app,
        client,
        claim_id,
        created['claim']['revision'],
        kind='police_report',
        filename='police-report.pdf',
        media_type='application/pdf',
        content=b'%PDF-1.4 synthetic police report',
        key='pdf-only',
    )
    provider = V8JourneyProvider(
        [
            envelope(
                action='answer_only',
                reply=(
                    'I have received your police report and attached it to your file for the '
                    'claims team. Can you tell me briefly what happened?'
                ),
            )
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)

    response = _send_file_only(client, claim_id, session_id, revision, evidence_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['recovery'] is None
    assert body['agent_message']['content']['text'].startswith('I have received your police report')
    # The provider (gpt-4o-mini, no PDF input) was not handed the bytes, but was
    # told the document arrived.
    assert len(provider.gateway.requests) == 1
    request = provider.gateway.requests[0]
    assert not any(
        getattr(block, 'evidence_id', None) == evidence_id
        for message in request.messages
        for block in (message.content_blocks or [])
    )
    user_payload = next(m for m in request.messages if m.role.value == 'user').content or ''
    assert evidence_id in user_payload
    assert 'received_but_unreadable' in user_payload
    # The message and the evidence are both persisted.
    assert len(repository.list_messages(claim_id, session_id, 'cus_demo')) == 2
    assert any(
        item.evidence_id == evidence_id for item in repository.list_evidence(claim_id, 'cus_demo')
    )
