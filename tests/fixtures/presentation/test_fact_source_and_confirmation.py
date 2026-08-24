"""Issue #141, the `bdfa123` half: fact source and confirmation state.

@Ysoseri1224 fixes and demonstrates the claimant and Agent path itself. This is
the independent check of where each fact came from and what confirmation state
it is in along the clear-claim path.

The question worth checking is not whether a value arrived, but whether the
claim can still say *who* said it and whether a person has agreed to it. A
system that loses either can present an extracted guess as a confirmed fact.
"""

import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import FormSource, FormStatus
from backend.repositories.fixture import FixtureRepository

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
CUSTOMER_ID = 'cus_demo'
FIELD = 'incident.description'
EXTRACTED = 'Rear panel damage is visible in the supplied photograph.'


@pytest.fixture
def repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def client(repository: FixtureRepository) -> TestClient:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    return TestClient(create_app(settings, repository))


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def upload_and_process(
    client: TestClient,
    claim_id: str,
    case: str,
    *,
    start_revision: int = 1,
    expect_processing: int = 200,
) -> str:
    """Take one evidence item from upload through completed processing.

    `expect_processing` lets a caller assert that processing is *refused*,
    which is the interesting case when the target field is already owned.
    """
    requested = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': f'{case}-upload',
            'If-Match': str(start_revision),
        },
        json={
            'kind': 'incident_image',
            'original_filename': f'{case}.jpg',
            'media_type': 'image/jpeg',
            'size_bytes': 512,
        },
    )
    assert requested.status_code == 201
    evidence_id = str(requested.json()['evidence_id'])

    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': f'{case}-complete',
            'If-Match': str(start_revision + 1),
        },
        json={'upload_checksum': f'sha256:{"c" * 64}'},
    )
    assert completed.status_code == 202

    processed = client.post(
        f'/internal/v1/claims/{claim_id}/evidence/{evidence_id}/processing',
        headers={
            **INTEGRATION_AUTH,
            'Idempotency-Key': f'{case}-processing',
            'If-Match': str(start_revision + 2),
        },
        json={'facts': [{'field_code': FIELD, 'value': EXTRACTED, 'confidence': 0.87}]},
    )
    assert processed.status_code == expect_processing
    if expect_processing == 409:
        assert processed.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    return evidence_id


def decide(client: TestClient, claim_id: str, evidence_id: str, case: str, decision: str) -> Any:
    return client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/fact-decisions',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': f'{case}-decision', 'If-Match': '4'},
        json={'field_codes': [FIELD], 'decision': decision},
    )


def test_an_extracted_fact_names_its_source_and_waits_for_a_person(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """A machine-read value is attributable and unconfirmed until someone agrees."""
    with client as active:
        claim_id = create_claim(active, 'source-proposed-claim')
        evidence_id = upload_and_process(active, claim_id, 'source-proposed')
        projection = active.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)

    claim = repository.get_claim(claim_id, CUSTOMER_ID)
    assert claim is not None
    field = claim.form[FIELD]

    assert field.source is FormSource.IMAGE
    assert field.source_refs == [evidence_id]
    assert field.confidence == 0.87
    assert field.status is FormStatus.PROPOSED
    assert field.value == EXTRACTED

    assert projection.status_code == 200
    projected_body = projection.json()
    projected_field = projected_body['form'][FIELD]
    assert projected_field['status'] == 'proposed'
    assert projected_field['source'] == 'image'
    assert projected_field['source_refs'] == [evidence_id]
    assert 'provenance' not in json.dumps(projected_body).lower()


@pytest.mark.parametrize(
    ('decision', 'expected_status'),
    [('confirmed', FormStatus.CONFIRMED), ('rejected', FormStatus.DISPUTED)],
)
def test_a_decision_changes_confirmation_state_without_losing_the_source(
    client: TestClient,
    repository: FixtureRepository,
    decision: str,
    expected_status: FormStatus,
) -> None:
    """Agreeing or disagreeing must not rewrite where the value came from."""
    with client as active:
        claim_id = create_claim(active, f'{decision}-source-claim')
        evidence_id = upload_and_process(active, claim_id, f'{decision}-source')
        before = repository.get_claim(claim_id, CUSTOMER_ID)
        assert before is not None
        source_before = before.form[FIELD].source
        refs_before = list(before.form[FIELD].source_refs)
        decided = decide(active, claim_id, evidence_id, f'{decision}-source', decision)

    assert decided.status_code == 200
    claim = repository.get_claim(claim_id, CUSTOMER_ID)
    assert claim is not None
    field = claim.form[FIELD]
    assert field.status is expected_status
    assert field.value == EXTRACTED
    assert field.source is source_before
    assert field.source_refs == refs_before
    assert refs_before == [evidence_id]


def state_claimant_fact(client: TestClient, claim_id: str, revision: int, value: str) -> Any:
    """Create a genuinely claimant-owned field through the claimant form."""
    return client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**CLAIMANT_AUTH, 'If-Match': f'"{revision}"'},
        json={'updates': [{'field_code': FIELD, 'value': value, 'status': 'confirmed'}]},
    )


def test_a_claimant_stated_fact_is_not_relabelled_as_machine_read(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """Extraction may not take over a field the claimant already owns."""
    claimant_value = 'I was rear-ended while stopped at the lights.'

    with client as active:
        claim_id = create_claim(active, 'claimant-owned-claim')
        stated = state_claimant_fact(active, claim_id, 1, claimant_value)
        assert stated.status_code == 200

        before = repository.get_claim(claim_id, CUSTOMER_ID)
        assert before is not None
        owned = before.form[FIELD]
        assert owned.source is FormSource.CLAIMANT
        assert owned.status is FormStatus.CONFIRMED
        assert owned.value == claimant_value
        snapshot = owned.model_dump(mode='json')

        evidence_id = upload_and_process(
            active,
            claim_id,
            'claimant-owned',
            start_revision=2,
            expect_processing=409,
        )

    conflicting = repository.get_claim(claim_id, CUSTOMER_ID)
    assert conflicting is not None
    assert conflicting.form[FIELD].model_dump(mode='json') == snapshot
    assert conflicting.form[FIELD].source is FormSource.CLAIMANT
    assert conflicting.form[FIELD].status is FormStatus.CONFIRMED
    assert evidence_id not in conflicting.form[FIELD].source_refs


def test_the_source_and_confirmation_check_is_repeatable(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """Issue #141: the fixture completes repeatedly."""
    results = []
    with client as active:
        for run in ('first', 'second'):
            claim_id = create_claim(active, f'repeatable-{run}-claim')
            evidence_id = upload_and_process(active, claim_id, f'repeatable-{run}')
            claim = repository.get_claim(claim_id, CUSTOMER_ID)
            assert claim is not None
            field = claim.form[FIELD]
            results.append(
                (
                    field.source,
                    field.status,
                    field.value,
                    field.confidence,
                    field.source_refs == [evidence_id],
                )
            )

    assert results[0] == results[1]
    assert results[0][4] is True
