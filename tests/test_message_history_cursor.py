from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient

from backend.domain.models import ActorType, MessageRecord, MessageVisibility
from backend.repositories.fixture import FixtureRepository


def _claim_and_session(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str,
) -> tuple[str, str]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201
    body = created.json()
    return (
        cast(str, body['claim']['claim_id']),
        cast(str, body['session']['session_id']),
    )


def _save_message(
    repository: FixtureRepository,
    claim_id: str,
    session_id: str,
    message_id: str,
    timestamp: datetime,
    *,
    visibility: MessageVisibility = MessageVisibility.CLAIMANT_VISIBLE,
) -> None:
    repository.save_message(
        MessageRecord(
            message_id=message_id,
            claim_id=claim_id,
            session_id=session_id,
            actor=ActorType.AGENT,
            visibility=visibility,
            content={'type': 'text', 'text': message_id},
            created_at=timestamp,
        ),
        'cus_demo',
    )


def test_message_cursor_uses_total_order_and_filters_visibility_before_paging(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _claim_and_session(client, auth_headers, 'cursor-order-claim')
    timestamp = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)
    for message_id in ('msg_a', 'msg_b', 'msg_c'):
        _save_message(repository, claim_id, session_id, message_id, timestamp)
    _save_message(
        repository,
        claim_id,
        session_id,
        'msg_ab_internal',
        timestamp,
        visibility=MessageVisibility.INTERNAL_ONLY,
    )

    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    first = client.get(route, headers=auth_headers, params={'limit': 1})
    assert first.status_code == 200
    assert [item['message_id'] for item in first.json()['items']] == ['msg_a']
    first_cursor = cast(str, first.json()['page']['next_cursor'])
    assert first_cursor

    # Simulate a concurrent record whose durable order key sorts before the cursor.
    # An offset cursor would now risk returning msg_a again on page two.
    _save_message(repository, claim_id, session_id, 'msg_0_inserted_later', timestamp)

    second = client.get(
        route,
        headers=auth_headers,
        params={'limit': 1, 'cursor': first_cursor},
    )
    assert second.status_code == 200
    assert [item['message_id'] for item in second.json()['items']] == ['msg_b']
    second_cursor = cast(str, second.json()['page']['next_cursor'])
    assert second_cursor

    third = client.get(
        route,
        headers=auth_headers,
        params={'limit': 1, 'cursor': second_cursor},
    )
    assert third.status_code == 200
    assert [item['message_id'] for item in third.json()['items']] == ['msg_c']
    assert third.json()['page']['next_cursor'] is None

    traversed = [
        first.json()['items'][0]['message_id'],
        second.json()['items'][0]['message_id'],
        third.json()['items'][0]['message_id'],
    ]
    assert traversed == ['msg_a', 'msg_b', 'msg_c']
    assert len(traversed) == len(set(traversed))
    assert 'msg_ab_internal' not in traversed
    assert 'msg_0_inserted_later' not in traversed


def test_message_cursor_rejects_non_api_cursor(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claim_id, session_id = _claim_and_session(client, auth_headers, 'cursor-invalid-claim')

    response = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers=auth_headers,
        params={'cursor': 'not-a-valid-message-cursor'},
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert response.json()['error']['details'][0]['field'] == 'cursor'
