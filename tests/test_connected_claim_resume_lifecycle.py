from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.domain.models import HandoffStatus, SessionStatus
from backend.repositories.fixture import FixtureRepository


def _pause_active_session(repository: FixtureRepository, claim_id: str) -> int:
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
    # There is no production pause route. Seed only the inactive-session prerequisite
    # used by the current resume API; the recovery itself still runs through the real
    # session service and repository mutation boundary.
    repository._claims[claim.claim_id] = updated
    return updated.revision


@pytest.mark.parametrize(
    ('product_family', 'description'),
    [
        ('motor', 'My parked car was hit from behind.'),
        ('home', 'A burst pipe damaged the kitchen wall.'),
        ('contents', 'Water damaged my laptop and furniture.'),
    ],
)
def test_connected_handoff_reply_continuation_and_resume_share_one_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    product_family: str,
    description: str,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'issue-257-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': product_family},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    first_session_id = created.json()['session']['session_id']
    assert created.json()['claim']['revision'] == 1

    claimant_turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue-257-first-message',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'issue-257-first-message',
            'content': {'type': 'text', 'text': description},
            'evidence_refs': [],
        },
    )
    assert claimant_turn.status_code == 200
    assert claimant_turn.json()['claim_revision'] == 2

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue-257-support',
            'If-Match': '2',
        },
        json={
            'reason': 'I want a staff member to help me continue.',
            'support_need': 'human_requested',
        },
    )
    assert support.status_code == 201
    assert support.json()['revision'] == 3
    handoff_id = support.json()['handoff']['handoff_id']

    queue = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    assert queue.status_code == 200
    assert any(item['claim_id'] == claim_id for item in queue.json()['items'])

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-257-accept',
            'If-Match': '3',
        },
        json={},
    )
    assert accepted.status_code == 200
    assert accepted.json()['revision'] == 4
    assert accepted.json()['handoff']['assigned_to'] == 'stf_demo'

    staff_content = {
        'type': 'text',
        'text': 'I have the saved claim and can continue from these details.',
    }
    staff_reply = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-257-staff-reply',
            'If-Match': '4',
        },
        json={'content': staff_content},
    )
    assert staff_reply.status_code == 200
    assert staff_reply.json()['claim_revision'] == 5
    staff_message_id = staff_reply.json()['message']['message_id']

    history = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/messages?limit=100',
        headers=auth_headers,
    )
    assert history.status_code == 200
    visible_staff = next(
        item for item in history.json()['items'] if item['message_id'] == staff_message_id
    )
    assert visible_staff['actor'] == 'staff'
    assert 'claim_id' not in visible_staff
    assert 'session_id' not in visible_staff

    continuation = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue-257-continuation',
            'If-Match': '5',
        },
        json={
            'client_message_id': 'issue-257-continuation',
            'content': {'type': 'text', 'text': 'Thanks. I will continue here.'},
            'evidence_refs': [],
        },
    )
    assert continuation.status_code == 200
    assert continuation.json()['claim_revision'] == 6
    assert continuation.json()['decision'] is None
    assert continuation.json()['agent_message'] is None

    before_resume = repository.get_claim(claim_id, 'cus_demo')
    handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert before_resume is not None
    assert handoff is not None
    assert before_resume.revision == 6
    assert before_resume.active_session_id == first_session_id
    assert handoff.status is HandoffStatus.IN_PROGRESS
    assert handoff.assigned_to == 'stf_demo'
    assert repository.claim_count == 1

    assert _pause_active_session(repository, claim_id) == 7
    resume_headers = {**auth_headers, 'Idempotency-Key': 'issue-257-resume'}
    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers=resume_headers,
        json={'intent': 'resume'},
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers=resume_headers,
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    assert replay.status_code == 201
    resumed_session_id = resumed.json()['session_id']
    assert resumed_session_id != first_session_id
    assert replay.json()['session_id'] == resumed_session_id

    after_resume = repository.get_claim(claim_id, 'cus_demo')
    resumed_session = repository.get_session(claim_id, resumed_session_id, 'cus_demo')
    preserved_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert after_resume is not None
    assert resumed_session is not None
    assert preserved_handoff is not None
    assert after_resume.revision == 8
    assert after_resume.active_session_id == resumed_session_id
    assert resumed_session.context_revision == 7
    assert preserved_handoff.status is HandoffStatus.IN_PROGRESS
    assert preserved_handoff.assigned_to == 'stf_demo'
    assert repository.claim_count == 1

    messages_before_stale = repository.list_messages(claim_id, resumed_session_id, 'cus_demo')
    stale_staff_reply = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-257-stale-staff-reply',
            'If-Match': '7',
        },
        json={'content': {'type': 'text', 'text': 'This stale reply must not persist.'}},
    )
    assert stale_staff_reply.status_code == 409
    assert stale_staff_reply.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.get_claim(claim_id, 'cus_demo') == after_resume
    messages_after_stale = repository.list_messages(claim_id, resumed_session_id, 'cus_demo')
    assert messages_after_stale == messages_before_stale

    resumed_turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{resumed_session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue-257-resumed-turn',
            'If-Match': '8',
        },
        json={
            'client_message_id': 'issue-257-resumed-turn',
            'content': {'type': 'text', 'text': 'I am continuing after resuming the claim.'},
            'evidence_refs': [],
        },
    )
    assert resumed_turn.status_code == 200
    assert resumed_turn.json()['claim_revision'] == 9
    assert resumed_turn.json()['decision'] is None
    assert resumed_turn.json()['agent_message'] is None
    resumed_message_id = resumed_turn.json()['claimant_message']['message_id']

    final_claim = repository.get_claim(claim_id, 'cus_demo')
    sessions = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    final_handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert final_claim is not None
    assert final_handoff is not None
    assert final_claim.revision == 9
    assert final_claim.incident_type == product_family
    assert final_claim.active_session_id == resumed_session_id
    assert final_handoff.status is HandoffStatus.IN_PROGRESS
    assert final_handoff.assigned_to == 'stf_demo'
    assert repository.claim_count == 1
    assert sum(session.status is SessionStatus.ACTIVE for session in sessions) == 1
    assert all(session.context_revision <= final_claim.revision for session in sessions)

    evaluations = repository.list_branch_evaluations(claim_id, 'cus_demo')
    applied_evaluations = [item for item in evaluations if item.status.value == 'applied']
    assert applied_evaluations
    assert all(item.selected_family == product_family for item in applied_evaluations)
    assert all(
        item.resulting_claim_revision == item.evaluated_against_claim_revision
        for item in applied_evaluations
    )
    recomputation_reasons = {item.recomputation_reason for item in applied_evaluations}
    assert {'agent_turn_applied', 'handoff_created', 'session_resumed'} <= recomputation_reasons

    events_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}/events?limit=100',
        headers=staff_auth_headers,
    )
    assert events_response.status_code == 200
    events = events_response.json()['items']
    created_event = next(item for item in events if item['event_type'] == 'claim.created')
    assert created_event['source_refs'] == [claim_id]
    assert created_event['resulting_revision'] == 1

    handoff_event = next(item for item in events if item['event_id'] == handoff_id)
    assert handoff_event['event_type'] == 'handoff.in_progress'
    assert handoff_event['actor_id'] == 'stf_demo'
    assert handoff_event['source_refs'] == [handoff_id]

    staff_event = next(item for item in events if item['event_id'] == staff_message_id)
    assert staff_event['event_type'] == 'message.appended'
    assert staff_event['actor_id'] == 'staff'
    assert staff_event['source_refs'] == [staff_message_id, first_session_id]

    resumed_event = next(item for item in events if item['event_id'] == resumed_message_id)
    assert resumed_event['event_type'] == 'message.appended'
    assert resumed_event['actor_id'] == 'claimant'
    assert resumed_event['source_refs'] == [resumed_message_id, resumed_session_id]
