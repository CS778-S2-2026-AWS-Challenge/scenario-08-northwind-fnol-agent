"""Durable #1106 regression: decoded image readiness is not fact extraction.

These tests exercise synthetic bytes and the fixture API/persistence boundary;
they do not claim real object-provider or model-success evidence.
"""

from hashlib import sha256
from io import BytesIO
from struct import pack
from typing import cast
from zlib import crc32

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.adapters.evidence_storage import EvidenceStorageUnavailable, MockEvidenceStorage
from backend.adapters.identity import FixtureIdentityRepository
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.models import EvidenceFileStatus, EvidenceStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence import repair_processing_image
from backend.services.image_readiness import validate_image_content


def _image(format_name: str = 'PNG', *, animated: bool = False) -> bytes:
    output = BytesIO()
    with Image.new('RGB', (4, 3), color='red') as first:
        if animated:
            with Image.new('RGB', (4, 3), color='blue') as second:
                first.save(output, format=format_name, save_all=True, append_images=[second])
        else:
            first.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize(
    ('case', 'media_type', 'valid'),
    [
        ('png', 'image/png', True),
        ('jpeg', 'image/jpeg', True),
        ('mismatch', 'image/jpeg', False),
        ('corrupt', 'image/png', False),
        ('truncated', 'image/jpeg', False),
        ('animated', 'image/png', False),
        ('oversized', 'image/png', False),
        ('gif', 'image/png', False),
    ],
)
def test_image_decoder_accepts_only_bounded_complete_declared_images(
    case: str, media_type: str, valid: bool
) -> None:
    content = _image('JPEG' if case in {'jpeg', 'truncated'} else 'PNG')
    if case == 'corrupt':
        content = b'not an image'
    elif case == 'truncated':
        content = content[:-20]
    elif case == 'animated':
        content = _image(animated=True)
    elif case == 'oversized':
        # A valid IHDR CRC allows the decoder to inspect dimensions without
        # allocating a 25-million-pixel synthetic fixture in the test process.
        header = pack('>II', 5001, 5000) + content[24:29]
        content = content[:16] + header + pack('>I', crc32(b'IHDR' + header)) + content[33:]
    elif case == 'gif':
        content = _image('GIF')
    assert validate_image_content(content, media_type) is valid


def _prepare_upload(
    client: TestClient, headers: dict[str, str], content: bytes, media_type: str = 'image/png'
) -> tuple[str, str, MockEvidenceStorage]:
    created = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': 'image-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = str(created.json()['claim']['claim_id'])
    requirement = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={**headers, 'Idempotency-Key': 'image-requirement', 'If-Match': '1'},
        json={'kind': 'incident_image', 'status': 'missing', 'needed_for': ['current_action']},
    )
    assert requirement.status_code == 201
    evidence_id = str(requirement.json()['evidence']['evidence_id'])
    intent = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={**headers, 'Idempotency-Key': 'image-upload', 'If-Match': '2'},
        json={
            'evidence_id': evidence_id,
            'kind': 'incident_image',
            'original_filename': 'synthetic-image.png',
            'media_type': media_type,
            'size_bytes': len(content),
        },
    )
    assert intent.status_code == 201
    storage = cast(MockEvidenceStorage, cast(FastAPI, client.app).state.evidence_storage)
    storage.put_upload(claim_id=claim_id, evidence_id=evidence_id, content=content)
    return claim_id, evidence_id, storage


@pytest.mark.parametrize('valid', [True, False])
def test_image_completion_settles_requirement_without_extracting_or_leaking_storage(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    valid: bool,
) -> None:
    content = _image() if valid else b'corrupt synthetic image'
    claim_id, evidence_id, _ = _prepare_upload(client, auth_headers, content)
    route = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete'
    headers = {**auth_headers, 'Idempotency-Key': 'image-complete', 'If-Match': '3'}
    payload = {'upload_checksum': f'sha256:{sha256(content).hexdigest()}'}
    before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    completed = client.post(route, headers=headers, json=payload)
    replay = client.post(route, headers=headers, json=payload)
    assert completed.status_code == replay.status_code == 200
    assert replay.json() == completed.json()
    body = completed.json()
    assert body['revision'] == 4
    assert body['evidence']['file_status'] == ('ready' if valid else 'failed')
    assert body['evidence']['can_remove'] is valid
    assert body['evidence']['evidence_id'] == evidence_id
    assert body['evidence']['needed_for'] == ['current_action']
    for private_name in ('storage_key', 'upload_checksum', 'image_validation', 'provenance'):
        assert private_name not in completed.text
    claim = repository.get_claim(claim_id, 'cus_demo')
    stored = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert before is not None and claim is not None and stored is not None
    assert claim.revision == 4 and claim.form == {}
    assert claim.evidence_summary.received == int(valid)
    assert claim.evidence_summary.needs_attention == int(not valid)
    assert claim.evidence_summary.pending == 0
    assert stored.material_version == before.material_version
    assert stored.material_history == before.material_history
    assert stored.created_at == before.created_at
    assert stored.provenance.get('extraction_state') != 'proposed'
    if valid:
        assert stored.provenance['image_validation'] == 'decoded-v1'
    assert len(repository.list_evidence(claim_id, 'cus_demo')) == 1
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    assert evaluations[-1].resulting_claim_revision == 4
    assert repository.find_idempotency('cus_demo', route, 'image-complete') is not None
    listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth_headers)
    assert listed.json()['items'] == [body['evidence']]
    conflicting = client.post(
        route, headers=headers, json={'upload_checksum': 'sha256:' + '0' * 64}
    )
    assert conflicting.status_code == 409
    assert conflicting.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('failure', ['missing', 'outage', 'checksum', 'size', 'race'])
def test_image_final_read_failure_does_not_commit_evidence_or_idempotency(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    content = _image()
    claim_id, evidence_id, storage = _prepare_upload(client, auth_headers, content)
    route = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete'
    before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')

    def read_upload(
        *, claim_id: str, evidence_id: str, storage_key: str | None = None
    ) -> bytes | None:
        if failure == 'outage':
            raise EvidenceStorageUnavailable('read', 'synthetic read outage')
        if failure == 'missing':
            return None
        if failure == 'checksum':
            return bytes([content[0] ^ 1]) + content[1:]
        if failure == 'size':
            return content[:-1]
        claim = repository.get_claim(claim_id, 'cus_demo')
        assert claim is not None
        repository.save_claim(claim.model_copy(update={'revision': 4}), expected_revision=3)
        return content

    monkeypatch.setattr(storage, 'read_upload', read_upload)
    result = client.post(
        route,
        headers={**auth_headers, 'Idempotency-Key': 'image-read-failure', 'If-Match': '3'},
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    assert result.status_code == (503 if failure in {'missing', 'outage'} else 409)
    if failure in {'missing', 'outage'}:
        assert result.json()['error']['retryable'] is True
    if failure == 'race':
        assert result.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.get_evidence(claim_id, evidence_id, 'cus_demo') == before
    assert repository.list_branch_evaluations(claim_id, 'cus_demo') == evaluations
    assert repository.find_idempotency('cus_demo', route, 'image-read-failure') is None
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.revision == (4 if failure == 'race' else 3)


def test_image_completion_denies_nonclaimant_before_reading_bytes(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _image()
    claim_id, evidence_id, storage = _prepare_upload(client, auth_headers, content)

    def forbidden_read(**kwargs: object) -> bytes:
        pytest.fail('Unauthorized completion reached protected image bytes.')

    monkeypatch.setattr(storage, 'read_upload', forbidden_read)
    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            'Authorization': 'Bearer synthetic-staff',
            'Idempotency-Key': 'staff-image-complete',
            'If-Match': '3',
        },
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    assert response.status_code == 403


def test_targeted_legacy_image_repair_is_dry_run_by_default_and_replayable(
    client: TestClient, auth_headers: dict[str, str], repository: FixtureRepository
) -> None:
    content = _image()
    claim_id, evidence_id, storage = _prepare_upload(client, auth_headers, content)
    before = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert before is not None
    stored = storage.complete_upload(
        claim_id=claim_id,
        evidence_id=evidence_id,
        checksum=f'sha256:{sha256(content).hexdigest()}',
        media_type='image/png',
        size_bytes=len(content),
    )
    legacy = before.model_copy(
        update={
            'status': EvidenceStatus.RECEIVED,
            'file_status': EvidenceFileStatus.PROCESSING,
            'provenance': {
                **before.provenance,
                'storage_key': stored.storage_key,
                'upload_checksum': stored.checksum,
                'processing_state': 'queued',
            },
        }
    )
    repository.save_evidence(legacy, 'cus_demo')
    claim_before = repository.get_claim(claim_id, 'cus_demo')
    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    preview = repair_processing_image(
        repository, storage, claim_id, evidence_id, 3, legacy.material_version
    )
    assert preview.evidence.file_status is EvidenceFileStatus.READY
    assert repository.get_evidence(claim_id, evidence_id, 'cus_demo') == legacy
    assert repository.get_claim(claim_id, 'cus_demo') == claim_before
    assert repository.list_branch_evaluations(claim_id, 'cus_demo') == evaluations
    with pytest.raises(ApiError) as wrong_generation:
        repair_processing_image(
            repository, storage, claim_id, evidence_id, 3, legacy.material_version + 1, apply=True
        )
    assert wrong_generation.value.status_code == 409
    with pytest.raises(ApiError) as stale_revision:
        repair_processing_image(
            repository, storage, claim_id, evidence_id, 2, legacy.material_version, apply=True
        )
    assert stale_revision.value.status_code == 409
    applied = repair_processing_image(
        repository, storage, claim_id, evidence_id, 3, legacy.material_version, apply=True
    )
    replay = repair_processing_image(
        repository, storage, claim_id, evidence_id, 3, legacy.material_version, apply=True
    )
    assert applied == replay
    assert applied.revision == 4
    settled = repository.get_evidence(claim_id, evidence_id, 'cus_demo')
    assert settled is not None
    assert settled.file_status is EvidenceFileStatus.READY
    assert settled.material_version == legacy.material_version
    assert settled.material_history == legacy.material_history
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None and claim.revision == 4 and claim.form == {}
    assert claim.evidence_summary.received == 1


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb-mock'])
def test_normal_identity_image_completion_has_provider_neutral_persisted_result(
    repository_kind: str,
) -> None:
    """Prove normal auth and logical Mongo serialization, not real transactions."""
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), 'image_readiness_contract')
        # mongomock cannot establish a real transaction or provider-success claim.
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.NORMAL),
        repository=repository,
        identity_repository=FixtureIdentityRepository(),
    )
    with TestClient(app) as client:
        login = client.post(
            '/api/v1/auth/sessions',
            json={'email': 'claimant.one@example.invalid', 'password': 'northwind-demo-one'},
        )
        assert login.status_code == 201
        headers = {'Authorization': f'Bearer {login.json()["access_token"]}'}
        customer_id = str(login.json()['customer_id'])
        content = _image('JPEG')
        claim_id, evidence_id, _ = _prepare_upload(client, headers, content, 'image/jpeg')
        route = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete'
        request_headers = {**headers, 'Idempotency-Key': 'normal-complete', 'If-Match': '3'}
        payload = {'upload_checksum': f'sha256:{sha256(content).hexdigest()}'}
        complete = client.post(route, headers=request_headers, json=payload)
        replay = client.post(route, headers=request_headers, json=payload)
        assert complete.status_code == replay.status_code == 200
        assert complete.json() == replay.json()
        evidence = repository.get_evidence(claim_id, evidence_id, customer_id)
        claim = repository.get_claim(claim_id, customer_id)
        assert evidence is not None and claim is not None
        assert evidence.file_status is EvidenceFileStatus.READY
        assert evidence.provenance['image_validation'] == 'decoded-v1'
        assert claim.revision == 4 and claim.form == {}
        assert claim.evidence_summary.received == 1
        assert repository.find_idempotency(customer_id, route, 'normal-complete') is not None
        assert (
            repository.list_branch_evaluations(claim_id, customer_id)[-1].resulting_claim_revision
            == 4
        )
