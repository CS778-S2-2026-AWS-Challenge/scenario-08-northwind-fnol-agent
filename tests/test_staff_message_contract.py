from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient

from backend.domain.models import ActorType, MessageRecord, MessageVisibility, SessionStatus
from backend.repositories.fixture import FixtureRepository


def _accepted_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    run_id: str,
) -> tuple[str, str, str, int]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'{run_id}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    created_body = created.json()
    claim_id = cast(str, created_body['claim']['claim_id'])
    session_id = cast(str, created_body['session']['session_id'])

    requested = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': f'{run_id}-request-human',
            'If-Match': str(created_body['claim']['revision']),
        },
        json={
            'client_message_id': f'{run_id}-request-human',
            'content': {'type': 'text', 'text': 'I want to speak to a person.'},
            'evidence_refs': [],
        },
    )
    assert requested.status_code == 200
    requested_body = requested.json()
    handoff_id = cast(str, requested_body['handoff']['handoff_id'])

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': f'{run_id}-accept',
            'If-Match': str(requested_body['claim_revision']),
        },
        json={},
    )
    assert accepted.status_code == 200
    accepted_body = accepted.json()
    assert accepted_body['handoff']['assigned_to'] == 'stf_demo'
    return claim_id, session_id, handoff_id, cast(int, accepted_body['revision'])


def test_staff_message_fails_closed_without_authoritative_active_session(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _, _, revision = _accepted_handoff(
        client, auth_headers, staff_auth_headers, 'missing-active-session'
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    before_messages = sum(
        len(repository.list_messages(claim_id, session.session_id, stored.customer_id))
        for session in repository.list_sessions_for_claim(claim_id, stored.customer_id)
    )
    before_handoffs = repository.list_handoffs(claim_id, stored.customer_id)
    repository.save_claim(
        stored.model_copy(update={'active_session_id': None}),
        expected_revision=stored.revision,
    )

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'missing-active-session-send',
            'If-Match': str(revision),
        },
        json={'content': {'type': 'text', 'text': 'I can help with your report.'}},
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.revision == revision
    after_messages = sum(
        len(repository.list_messages(claim_id, session.session_id, after.customer_id))
        for session in repository.list_sessions_for_claim(claim_id, after.customer_id)
    )
    assert after_messages == before_messages
    assert repository.list_handoffs(claim_id, after.customer_id) == before_handoffs
    assert (
        repository.find_idempotency(
            'stf_demo',
            f'/api/v1/workbench/claims/{claim_id}/messages',
            'missing-active-session-send',
        )
        is None
    )


def test_staff_message_fails_closed_when_active_session_record_is_not_active(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, _, revision = _accepted_handoff(
        client, auth_headers, staff_auth_headers, 'closed-active-session'
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    session = repository.get_session(claim_id, session_id, stored.customer_id)
    assert session is not None
    repository.save_session(
        session.model_copy(update={'status': SessionStatus.CLOSED, 'closed_at': datetime.now(UTC)})
    )
    before_claim = repository.get_claim_internal(claim_id)
    before_messages = repository.list_messages(claim_id, session_id, stored.customer_id)

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'closed-active-session-send',
            'If-Match': str(revision),
        },
        json={'content': {'type': 'text', 'text': 'I can help with your report.'}},
    )

    assert response.status_code == 422
    assert repository.get_claim_internal(claim_id) == before_claim
    assert repository.list_messages(claim_id, session_id, stored.customer_id) == before_messages


def test_staff_reply_cannot_target_internal_only_message(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, _, revision = _accepted_handoff(
        client, auth_headers, staff_auth_headers, 'internal-reply'
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    internal = MessageRecord(
        message_id='msg_internal_reply_target',
        claim_id=claim_id,
        session_id=session_id,
        actor=ActorType.SYSTEM,
        visibility=MessageVisibility.INTERNAL_ONLY,
        content={'type': 'review_signal', 'code': 'INTERNAL_ONLY_FIXTURE'},
        created_at=datetime.now(UTC),
    )
    repository.save_message(internal, stored.customer_id)
    before_claim = repository.get_claim_internal(claim_id)
    before_messages = repository.list_messages(claim_id, session_id, stored.customer_id)

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'internal-reply-send',
            'If-Match': str(revision),
        },
        json={
            'content': {'type': 'text', 'text': 'This must not be sent as a reply.'},
            'in_reply_to': internal.message_id,
        },
    )

    assert response.status_code == 422
    assert repository.get_claim_internal(claim_id) == before_claim
    assert repository.list_messages(claim_id, session_id, stored.customer_id) == before_messages


def test_valid_staff_message_uses_active_session_and_replays_without_duplication(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id, _, revision = _accepted_handoff(
        client, auth_headers, staff_auth_headers, 'staff-replay'
    )
    route = f'/api/v1/workbench/claims/{claim_id}/messages'
    headers = {
        **staff_auth_headers,
        'Idempotency-Key': 'staff-replay-send',
        'If-Match': str(revision),
    }
    payload = {'content': {'type': 'text', 'text': 'I am reviewing the report with you now.'}}
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    before_count = len(repository.list_messages(claim_id, session_id, stored.customer_id))

    sent = client.post(route, headers=headers, json=payload)
    replay = client.post(route, headers=headers, json=payload)
    conflict = client.post(
        route,
        headers=headers,
        json={'content': {'type': 'text', 'text': 'Changed payload with the same key.'}},
    )

    assert sent.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == sent.json()
    assert sent.json()['session_id'] == session_id
    assert sent.json()['message']['actor'] == 'staff'
    assert sent.json()['message']['visibility'] == 'shared'
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.revision == revision + 1
    messages = repository.list_messages(claim_id, session_id, after.customer_id)
    assert len(messages) == before_count + 1
    assert sum(message.actor is ActorType.STAFF for message in messages) == 1
    idempotency = repository.find_idempotency('stf_demo', route, 'staff-replay-send')
    assert idempotency is not None
    assert idempotency.session_id == session_id
    assert idempotency.message_id == sent.json()['message']['message_id']
