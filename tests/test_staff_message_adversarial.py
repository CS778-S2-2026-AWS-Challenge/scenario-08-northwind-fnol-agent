from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient

from backend.domain.models import (
    ActorType,
    MessageRecord,
    MessageVisibility,
    SessionRecord,
    SessionStatus,
)
from backend.repositories.fixture import FixtureRepository


def _queued_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    run_id: str,
) -> tuple[str, str, str, int]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'{run_id}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201
    body = created.json()
    claim_id = cast(str, body['claim']['claim_id'])
    session_id = cast(str, body['session']['session_id'])
    requested = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{run_id}-human',
            'If-Match': str(body['claim']['revision']),
        },
        json={
            'client_message_id': f'{run_id}-human',
            'content': {'type': 'text', 'text': 'I want to speak to a person.'},
            'evidence_refs': [],
        },
    )
    assert requested.status_code == 200
    result = requested.json()
    return (
        claim_id,
        session_id,
        cast(str, result['handoff']['handoff_id']),
        cast(int, result['claim_revision']),
    )


def _accept(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    claim_id: str,
    handoff_id: str,
    revision: int,
    run_id: str,
    *,
    assignee_id: str | None = None,
) -> int:
    payload = {} if assignee_id is None else {'assignee_id': assignee_id}
    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': f'{run_id}-accept',
            'If-Match': str(revision),
        },
        json=payload,
    )
    assert response.status_code == 200
    return cast(int, response.json()['revision'])


def test_staff_message_rejects_wrong_handoff_assignee_without_mutation(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, handoff_id, revision = _queued_handoff(
        client, auth_headers, 'wrong-assignee'
    )
    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'wrong-assignee-accept',
            'If-Match': str(revision),
        },
        json={'assignee_id': 'stf_other'},
    )
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    before_messages = repository.list_messages(claim_id, session_id, claim.customer_id)
    before_handoffs = repository.list_handoffs(claim_id, claim.customer_id)
    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.revision == revision
    assert repository.list_messages(claim_id, session_id, claim.customer_id) == before_messages
    assert repository.list_handoffs(claim_id, claim.customer_id) == before_handoffs


def test_staff_reply_rejects_message_from_another_session(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, active_session_id, handoff_id, revision = _queued_handoff(
        client, auth_headers, 'cross-session-reply'
    )
    accepted_revision = _accept(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        revision,
        'cross-session-reply',
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    now = datetime(2026, 8, 26, 7, 30, tzinfo=UTC)
    old_session = SessionRecord(
        session_id='ses_old_reply_target',
        claim_id=claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.CLOSED,
        context_revision=accepted_revision,
        started_at=now,
        last_active_at=now,
        closed_at=now,
    )
    repository.save_session(old_session)
    old_message = MessageRecord(
        message_id='msg_old_session_reply_target',
        claim_id=claim_id,
        session_id=old_session.session_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.SHARED,
        content={'type': 'text', 'text': 'Old session message.'},
        created_at=now,
    )
    repository.save_message(old_message, claim.customer_id)
    before_active = repository.list_messages(claim_id, active_session_id, claim.customer_id)

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'cross-session-reply-send',
            'If-Match': str(accepted_revision),
        },
        json={
            'content': {'type': 'text', 'text': 'Reply should be rejected.'},
            'in_reply_to': old_message.message_id,
        },
    )

    assert response.status_code == 422
    assert repository.list_messages(claim_id, active_session_id, claim.customer_id) == before_active
    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.revision == accepted_revision


def test_staff_message_rejects_stale_revision_before_persistence(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, handoff_id, revision = _queued_handoff(
        client, auth_headers, 'stale-staff-message'
    )
    accepted_revision = _accept(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        revision,
        'stale-staff-message',
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    before_messages = repository.list_messages(claim_id, session_id, claim.customer_id)

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'stale-staff-message-send',
            'If-Match': str(accepted_revision - 1),
        },
        json={'content': {'type': 'text', 'text': 'Stale page message.'}},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.list_messages(claim_id, session_id, claim.customer_id) == before_messages
    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.revision == accepted_revision


def test_multi_session_staff_send_requires_active_reply_and_preserves_retry_identity(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, active_session_id, handoff_id, revision = _queued_handoff(
        client, auth_headers, 'multi-session-send'
    )
    accepted_revision = _accept(
        client,
        staff_auth_headers,
        claim_id,
        handoff_id,
        revision,
        'multi-session-send',
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    active_messages = repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    )
    claimant_message = next(
        message for message in reversed(active_messages) if message.actor is ActorType.CLAIMANT
    )
    now = datetime(2026, 9, 9, 4, 30, tzinfo=UTC)
    old_session = SessionRecord(
        session_id='ses_old_multi_session_send',
        claim_id=claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.CLOSED,
        context_revision=accepted_revision,
        started_at=now,
        last_active_at=now,
        closed_at=now,
    )
    repository.save_session(old_session)
    before_messages = repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    )

    unscoped = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'multi-session-unscoped',
            'If-Match': str(accepted_revision),
        },
        json={'content': {'type': 'text', 'text': 'Unscoped reply must fail closed.'}},
    )

    assert unscoped.status_code == 422
    assert unscoped.json()['error']['code'] == 'VALIDATION_ERROR'
    assert repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    ) == before_messages
    unchanged = repository.get_claim_internal(claim_id)
    assert unchanged is not None
    assert unchanged.revision == accepted_revision

    scoped_payload = {
        'content': {'type': 'text', 'text': 'Reply to the active claimant session.'},
        'in_reply_to': claimant_message.message_id,
    }
    first = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'multi-session-scoped',
            'If-Match': str(accepted_revision),
        },
        json=scoped_payload,
    )

    assert first.status_code == 200
    first_body = first.json()
    assert first_body['session_id'] == active_session_id
    assert first_body['claim_revision'] == accepted_revision + 1
    after_first = repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    )
    assert len(after_first) == len(before_messages) + 1

    replay = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'multi-session-scoped',
            'If-Match': str(accepted_revision),
        },
        json=scoped_payload,
    )

    assert replay.status_code == 200
    assert replay.json() == first_body
    assert repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    ) == after_first

    stale_new_key = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'multi-session-scoped-new-key',
            'If-Match': str(accepted_revision),
        },
        json=scoped_payload,
    )

    assert stale_new_key.status_code == 409
    assert stale_new_key.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.list_messages(
        claim_id, active_session_id, claim.customer_id
    ) == after_first
