import pytest
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord


def test_start_session_maps_active_session_idempotency_conflict_without_writes(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-active-session-conflict'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    session_id = created.json()['session']['session_id']

    before_claim = repository.get_claim(claim_id, 'cus_demo')
    before_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert before_claim is not None
    assert before_session is not None

    def reject_idempotency(record: IdempotencyRecord) -> None:
        raise IdempotencyConflict(record.key)

    monkeypatch.setattr(repository, 'save_idempotency', reject_idempotency)

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'active-session-conflict'},
        json={'intent': 'resume'},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert repository.get_claim(claim_id, 'cus_demo') == before_claim
    assert repository.list_sessions_for_claim(claim_id, 'cus_demo') == [before_session]
    assert (
        repository.find_idempotency(
            'cus_demo',
            f'/api/v1/claims/{claim_id}/sessions',
            'active-session-conflict',
        )
        is None
    )
