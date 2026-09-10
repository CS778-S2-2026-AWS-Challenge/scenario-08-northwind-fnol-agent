from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.domain.models import (
    FollowUpContactPermission,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
)
from backend.repositories.fixture import FixtureRepository


def _create_claim(
    client: TestClient,
    headers: dict[str, str],
    key: str,
) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    body = response.json()
    return (
        str(body['claim']['claim_id']),
        str(body['session']['session_id']),
        int(body['claim']['revision']),
    )


def test_active_collecting_claim_is_not_projected_as_incomplete(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim_id, _, _ = _create_claim(client, auth_headers, 'p17-active-create')

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert detail.status_code == 200
    assert detail.json()['work_summary']['queue_key'] != 'incomplete_claims'
    assert detail.json()['work_summary']['incomplete_context'] is None

    incomplete = client.get(
        '/api/v1/workbench/claims',
        params={'view': 'incomplete_claims'},
        headers=staff_auth_headers,
    )
    assert incomplete.status_code == 200
    assert claim_id not in {item['claim_id'] for item in incomplete.json()['items']}


def test_pause_resume_resolves_follow_up_and_resumed_session_can_pause_again(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, first_session_id, revision = _create_claim(
        client,
        auth_headers,
        'p17-roundtrip-create',
    )
    first_pause = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-roundtrip-pause-1',
            'If-Match': f'"{revision}"',
        },
    )
    assert first_pause.status_code == 200
    first_follow_up = repository.list_follow_ups(claim_id, 'cus_demo')[0]
    assert first_follow_up.status is FollowUpStatus.PENDING
    assert first_follow_up.purpose == 'resume_incomplete_claim'
    assert first_follow_up.channel is PreferredChannel.IN_APP
    assert first_follow_up.contact_permission is FollowUpContactPermission.AUTHORISED
    assert first_follow_up.due_at is not None
    assert first_follow_up.source_refs

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'p17-roundtrip-resume'},
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    resumed_session_id = str(resumed.json()['session_id'])

    after_resume = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(after_resume) == 1
    assert after_resume[0].status is FollowUpStatus.RESOLVED
    assert after_resume[0].outcome == 'claimant_resumed'

    workbench = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert workbench.status_code == 200
    assert workbench.json()['work_summary']['queue_key'] != 'incomplete_claims'
    assert workbench.json()['work_summary']['incomplete_context'] is None

    current = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert current.status_code == 200
    current_revision = int(current.json()['revision'])
    second_pause = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{resumed_session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-roundtrip-pause-2',
            'If-Match': f'"{current_revision}"',
        },
    )
    assert second_pause.status_code == 200
    all_follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(all_follow_ups) == 2
    open_follow_ups = [
        item
        for item in all_follow_ups
        if item.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
        and item.purpose == 'resume_incomplete_claim'
    ]
    assert len(open_follow_ups) == 1
    assert open_follow_ups[0].source_session_id == resumed_session_id


def test_anonymous_pause_persists_blocked_not_authorised_follow_up(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    anonymous_session = '4c7f9f6e-0f31-4ce3-a5cc-5e3a4d8e4b10'
    headers = {'X-Northwind-Anonymous-Session': anonymous_session}
    claim_id, session_id, revision = _create_claim(client, headers, 'p17-anon-create')

    paused = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers={
            **headers,
            'Idempotency-Key': 'p17-anon-pause',
            'If-Match': f'"{revision}"',
        },
    )
    assert paused.status_code == 200
    assert paused.json()['claim']['incomplete_context']['follow_up_status'] == 'blocked'

    follow_ups = repository.list_follow_ups(claim_id, f'anonymous:{anonymous_session}')
    assert len(follow_ups) == 1
    follow_up = follow_ups[0]
    assert follow_up.status is FollowUpStatus.BLOCKED
    assert follow_up.contact_permission is FollowUpContactPermission.NOT_AUTHORISED
    assert follow_up.channel is None
    assert follow_up.due_at is None
    assert follow_up.attempt_count == 0


def test_follow_up_record_validation_paths() -> None:
    now = datetime(2026, 9, 10, tzinfo=UTC)

    default_refs = FollowUpRecord(
        follow_up_id='fup-default-refs',
        claim_id='clm-validation',
        source_session_id='ses-default-refs',
        responsible_party=ResponsibleParty.CLAIMANT,
        created_at=now,
        updated_at=now,
    )
    assert default_refs.source_refs == ['session:ses-default-refs']

    with pytest.raises(ValueError, match='updated before'):
        FollowUpRecord(
            follow_up_id='fup-invalid-time',
            claim_id='clm-validation',
            source_session_id='ses-invalid-time',
            responsible_party=ResponsibleParty.CLAIMANT,
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match='source references must be unique'):
        FollowUpRecord(
            follow_up_id='fup-duplicate-refs',
            claim_id='clm-validation',
            source_session_id='ses-duplicate-refs',
            responsible_party=ResponsibleParty.CLAIMANT,
            source_refs=['session:ses-duplicate-refs', 'session:ses-duplicate-refs'],
            created_at=now,
            updated_at=now,
        )

    with pytest.raises(ValueError, match='authorised channel and due time'):
        FollowUpRecord(
            follow_up_id='fup-invalid-pending',
            claim_id='clm-validation',
            source_session_id='ses-invalid-pending',
            responsible_party=ResponsibleParty.CLAIMANT,
            status=FollowUpStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

    with pytest.raises(ValueError, match='must not claim an authorised channel or schedule'):
        FollowUpRecord(
            follow_up_id='fup-invalid-blocked',
            claim_id='clm-validation',
            source_session_id='ses-invalid-blocked',
            responsible_party=ResponsibleParty.CLAIMANT,
            contact_permission=FollowUpContactPermission.AUTHORISED,
            status=FollowUpStatus.BLOCKED,
            created_at=now,
            updated_at=now,
        )
