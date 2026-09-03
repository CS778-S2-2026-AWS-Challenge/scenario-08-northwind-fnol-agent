import pytest
from fastapi.testclient import TestClient

from backend.core.auth import CLAIMANT_SCOPES, Principal
from backend.core.errors import ApiError
from backend.repositories.fixture import FixtureRepository
from backend.services.claimant_events import claimant_change_after, claimant_event_revision


def _claimant_principal(customer_id: str = 'cus_demo') -> Principal:
    return Principal(
        subject=customer_id,
        actor_type='claimant',
        scopes=CLAIMANT_SCOPES,
        auth_source='developer:synthetic_claimant',
        synthetic=True,
    )


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    suffix: str,
) -> tuple[str, str]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'claim-events-{suffix}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload['claim']['claim_id'], payload['session']['session_id']


def test_claimant_event_cursor_reports_only_an_authorised_resource_hint(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _create_claim(client, auth_headers, suffix='authorised')

    event = claimant_change_after(
        repository,
        _claimant_principal(),
        claim_id,
        session_id,
        after_revision=0,
    )

    assert event is not None
    assert event.claim_revision == 1
    assert event.event_id == '1'
    assert event.resources == ['claim', 'messages']
    assert event.model_dump().keys() == {
        'event_id',
        'claim_id',
        'session_id',
        'claim_revision',
        'resources',
        'emitted_at',
    }
    assert (
        claimant_change_after(
            repository,
            _claimant_principal(),
            claim_id,
            session_id,
            after_revision=1,
        )
        is None
    )


def test_claimant_event_cursor_rejects_cross_customer_and_cross_session_reads(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _create_claim(client, auth_headers, suffix='boundary')

    with pytest.raises(ApiError) as cross_customer:
        claimant_event_revision(
            repository,
            _claimant_principal('cus_other'),
            claim_id,
            session_id,
        )
    assert cross_customer.value.status_code == 404

    with pytest.raises(ApiError) as cross_session:
        claimant_event_revision(
            repository,
            _claimant_principal(),
            claim_id,
            'ses_other',
        )
    assert cross_session.value.status_code == 404


def test_claimant_event_cursor_rejects_a_revision_from_the_future(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _create_claim(client, auth_headers, suffix='future')

    with pytest.raises(ApiError) as future_cursor:
        claimant_change_after(
            repository,
            _claimant_principal(),
            claim_id,
            session_id,
            after_revision=2,
        )

    assert future_cursor.value.status_code == 409
    assert future_cursor.value.code == 'INVALID_EVENT_CURSOR'
    assert future_cursor.value.current_revision == 1
