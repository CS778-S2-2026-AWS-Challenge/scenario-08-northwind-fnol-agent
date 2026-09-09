from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str,
) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )
    assert response.status_code == 201
    body = response.json()
    return (
        str(body['claim']['claim_id']),
        str(body['session']['session_id']),
        int(body['claim']['revision']),
    )


def test_pause_missing_claim_fails_without_creating_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        '/api/v1/claims/clm_missing/sessions/ses_missing/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-missing-claim',
            'If-Match': '"1"',
        },
    )

    assert response.status_code == 404


def test_pause_missing_session_fails_without_follow_up(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _, revision = _create_claim(client, auth_headers, 'p17-edge-create-missing')

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/ses_missing/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-missing-session',
            'If-Match': f'"{revision}"',
        },
    )

    assert response.status_code == 404
    assert repository.list_follow_ups(claim_id, 'cus_demo') == []


def test_pause_rejects_a_session_that_is_already_paused(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claim_id, session_id, revision = _create_claim(client, auth_headers, 'p17-edge-create-pause')
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'

    first = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-edge-first-pause',
            'If-Match': f'"{revision}"',
        },
    )
    assert first.status_code == 200

    second = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-edge-second-pause',
            'If-Match': f'"{revision + 1}"',
        },
    )

    assert second.status_code == 409
    assert second.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


def test_pause_rejects_an_idempotency_key_with_a_conflicting_record(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, revision = _create_claim(client, auth_headers, 'p17-edge-create-key')
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id='cus_demo',
            route=route,
            key='p17-edge-conflict-key',
            request_fingerprint='different-fingerprint',
            claim_id=claim_id,
            session_id=session_id,
            response_payload={},
        )
    )

    response = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-edge-conflict-key',
            'If-Match': f'"{revision}"',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
