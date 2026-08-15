from datetime import timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.domain.models import HandoffStatus, SessionStatus
from backend.repositories.fixture import FixtureRepository


def pause_active_session(repository: FixtureRepository, claim_id: str) -> int:
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.active_session_id is not None
    session = repository.get_session(claim_id, claim.active_session_id, 'cus_demo')
    assert session is not None

    repository.save_session(session.model_copy(update={'status': SessionStatus.PAUSED}))
    updated = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': claim.updated_at + timedelta(minutes=1),
        }
    )
    repository.save_claim(updated, expected_revision=claim.revision)
    return updated.revision


def test_resume_and_handoff_share_one_authoritative_claim_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'integration-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    first_session_id = created.json()['session']['session_id']
    assert isinstance(claim_id, str)
    assert isinstance(first_session_id, str)
    assert created.json()['claim']['revision'] == 1
    assert repository.claim_count == 1

    assert pause_active_session(repository, claim_id) == 2

    first_resume = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'integration-resume-one'},
        json={'intent': 'resume'},
    )
    assert first_resume.status_code == 201
    first_resume_body = cast(dict[str, Any], first_resume.json())
    second_session_id = first_resume_body['session_id']
    assert isinstance(second_session_id, str)
    assert second_session_id != first_session_id

    after_first_resume = repository.get_claim(claim_id, 'cus_demo')
    assert after_first_resume is not None
    assert after_first_resume.revision == 3
    assert after_first_resume.active_session_id == second_session_id
    resumed_session = repository.get_session(claim_id, second_session_id, 'cus_demo')
    assert resumed_session is not None
    assert resumed_session.context_revision == 2

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'integration-support',
            'If-Match': '3',
        },
        json={
            'reason': 'I want a staff member to continue this synthetic claim.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        },
    )
    assert support.status_code == 201
    support_body = cast(dict[str, Any], support.json())
    handoff_id = support_body['handoff']['handoff_id']
    assert isinstance(handoff_id, str)
    assert support_body['revision'] == 4
    assert support_body['handoff']['claim_id'] == claim_id
    assert support_body['handoff']['status'] == 'queued'

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'integration-accept',
            'If-Match': '4',
        },
        json={},
    )
    assert accepted.status_code == 200
    accepted_body = cast(dict[str, Any], accepted.json())
    assert accepted_body['revision'] == 5
    assert accepted_body['handoff']['assigned_to'] == 'stf_demo'
    assert accepted_body['handoff']['status'] == 'accepted'

    assert pause_active_session(repository, claim_id) == 6

    second_resume = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'integration-resume-two'},
        json={'intent': 'resume'},
    )
    assert second_resume.status_code == 201
    second_resume_body = cast(dict[str, Any], second_resume.json())
    third_session_id = second_resume_body['session_id']
    assert isinstance(third_session_id, str)
    assert third_session_id not in {first_session_id, second_session_id}

    after_second_resume = repository.get_claim(claim_id, 'cus_demo')
    assert after_second_resume is not None
    assert after_second_resume.revision == 7
    assert after_second_resume.active_session_id == third_session_id
    assert repository.claim_count == 1

    preserved_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert preserved_handoff is not None
    assert preserved_handoff.status is HandoffStatus.ACCEPTED
    assert preserved_handoff.assigned_to == 'stf_demo'

    stale_staff_write = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'integration-stale-message',
            'If-Match': '6',
        },
        json={'content': {'type': 'text', 'text': 'This stale write must not be accepted.'}},
    )
    assert stale_staff_write.status_code == 409
    stale_body = cast(dict[str, Any], stale_staff_write.json())
    assert stale_body['error']['code'] == 'REVISION_CONFLICT'
    assert stale_body['error']['current_revision'] == 7

    staff_write = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'integration-current-message',
            'If-Match': '7',
        },
        json={
            'content': {'type': 'text', 'text': 'I am continuing from the current claim revision.'}
        },
    )
    assert staff_write.status_code == 200
    assert staff_write.json()['claim_revision'] == 8

    final_claim = repository.get_claim(claim_id, 'cus_demo')
    final_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    sessions = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_handoff is not None
    assert final_claim.revision == 8
    assert final_claim.active_session_id == third_session_id
    assert final_handoff.status is HandoffStatus.IN_PROGRESS
    assert final_handoff.assigned_to == 'stf_demo'
    assert repository.claim_count == 1
    assert len(sessions) == 3
    assert sum(session.status is SessionStatus.ACTIVE for session in sessions) == 1
    assert all(session.claim_id == claim_id for session in sessions)
    assert all(session.context_revision <= final_claim.revision for session in sessions)
