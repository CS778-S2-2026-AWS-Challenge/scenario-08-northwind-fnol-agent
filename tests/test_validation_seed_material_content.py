"""Every produced demonstration material seeded for validation can be opened.

The validation seed associates the P8 materials with their Claims, but association alone left
their bytes in the repository. The Workbench content route reads only what evidence storage
holds, so every material with a file answered `404` and rendered as a broken image. These tests
drive the seed through its API and open each material the way the Workbench preview does.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import EvidenceStorageUnavailable, MockEvidenceStorage
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import EvidenceRecord
from backend.repositories.fixture import FixtureRepository
from backend.services.demo_materials import (
    DEMO_MATERIAL_SCHEME,
    MATERIALS_DIRECTORY,
    MaterialAssociationError,
    material_content,
)

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
SEED_PATH = '/api/v1/workbench/demo/seed-validation'
SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
PRODUCED_FILES = 24


def _materials(
    repository: FixtureRepository, claim_ids: list[str]
) -> Iterator[tuple[str, EvidenceRecord, str]]:
    for claim_id in claim_ids:
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None
        for record in repository.list_evidence(claim_id, claim.customer_id):
            reference = record.provenance.get('demo_material_ref')
            if isinstance(reference, str) and record.media_type is not None:
                yield claim_id, record, reference.removeprefix(DEMO_MATERIAL_SCHEME)


def _content_path(claim_id: str, evidence_id: str) -> str:
    return f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content'


def test_every_seeded_material_with_a_file_can_be_opened() -> None:
    """All 24 produced files are served, with their declared type and committed bytes."""

    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        seeded = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'content-1'})
        assert seeded.status_code == 200, seeded.text

        opened = 0
        for claim_id, record, path in _materials(repository, seeded.json()['claim_ids']):
            response = client.get(_content_path(claim_id, record.evidence_id), headers=STAFF_AUTH)
            assert response.status_code == 200, (path, response.text)
            assert record.media_type is not None
            assert response.headers['content-type'].startswith(record.media_type)
            assert response.content == (MATERIALS_DIRECTORY / path).read_bytes()
            assert str(record.provenance['upload_checksum']).startswith('sha256:')
            opened += 1

        assert opened == PRODUCED_FILES


def test_the_synthetic_reference_still_has_no_file() -> None:
    """The cross-role placeholder is not a produced material and gains no storage key."""

    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        seeded = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'content-2'})
        assert seeded.status_code == 200, seeded.text

        for claim_id in seeded.json()['claim_ids']:
            claim = repository.get_claim_internal(claim_id)
            assert claim is not None
            synthetic = [
                record
                for record in repository.list_evidence(claim_id, claim.customer_id)
                if record.kind == 'claimant_attachment'
            ]
            assert len(synthetic) == 1
            assert 'storage_key' not in synthetic[0].provenance
            response = client.get(
                _content_path(claim_id, synthetic[0].evidence_id), headers=STAFF_AUTH
            )
            assert response.status_code == 404
            assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_a_storage_outage_seeds_nothing_and_the_same_request_can_be_retried() -> None:
    """P8.3's failure boundary: a storage outage is visible and retryable."""

    repository = FixtureRepository()
    storage = MockEvidenceStorage()
    with TestClient(create_app(SETTINGS, repository, evidence_storage=storage)) as client:
        # The outage starts after the app is up: a store that is down at start-up is refused
        # by the runtime readiness check before any route can run.
        storage.set_outage(
            EvidenceStorageUnavailable('storage_unavailable', 'Simulated storage outage.')
        )
        refused = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'content-3'})

        assert refused.status_code == 503, refused.text
        assert refused.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
        assert refused.json()['error']['retryable'] is True
        assert repository.list_claims_internal() == []

        storage.set_outage(None)
        retried = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'content-3'})

        assert retried.status_code == 200, retried.text
        assert len(retried.json()['claim_ids']) == 3


def test_material_content_refuses_references_it_cannot_trust() -> None:
    """The resolver reads only produced files inside the materials directory, at their size."""

    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        seeded = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'content-4'})
        assert seeded.status_code == 200, seeded.text
        _, record, _ = next(_materials(repository, seeded.json()['claim_ids']))

    provenance = dict(record.provenance)
    assert material_content(record.model_copy(update={'provenance': {}})) is None
    assert material_content(record.model_copy(update={'media_type': None})) is None

    untrusted = (
        'file:///etc/passwd',
        f'{DEMO_MATERIAL_SCHEME}../../../README.md',
        f'{DEMO_MATERIAL_SCHEME}motor/not-a-produced-file.jpg',
    )
    for reference in untrusted:
        with pytest.raises(MaterialAssociationError):
            material_content(
                record.model_copy(
                    update={'provenance': {**provenance, 'demo_material_ref': reference}}
                )
            )

    assert record.size_bytes is not None
    with pytest.raises(MaterialAssociationError):
        material_content(record.model_copy(update={'size_bytes': record.size_bytes + 1}))
