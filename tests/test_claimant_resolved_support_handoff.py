from datetime import timedelta

from fastapi.testclient import TestClient

from backend.domain.models import (
    ActorReference,
    ClaimTerminalDisposition,
    HandoffStatus,
    HandoffType,
    StaffActionRecord,
    StaffActionResult,
    StaffActionStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
)
from backend.repositories.fixture import FixtureRepository


def _create_claim(client: TestClient, headers: dict[str, str], key: str) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def _resolve_support_handoff(
    client: TestClient,
    repository: FixtureRepository,
    headers: dict[str, str],
    claim_id: str,
    key: str,
    support_need: str,
) -> tuple[str, str]:
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    response = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={**headers, 'Idempotency-Key': key, 'If-Match': str(claim.revision)},
        json={
            'reason': 'Please have a staff member continue this report.',
            'support_need': support_need,
        },
    )
    assert response.status_code == 201
    handoff_id = response.json()['handoff']['handoff_id']
    handoff = repository.get_handoff(claim_id, handoff_id, claim.customer_id)
    assert handoff is not None
    resolved_at = handoff.created_at + timedelta(minutes=2)
    resolved = handoff.model_copy(
        update={
            'status': HandoffStatus.RESOLVED,
            'resolved_at': resolved_at,
            'assigned_to': 'stf_demo',
        }
    )
    repository.save_handoff(resolved, claim.customer_id)
    action = StaffActionRecord(
        action_id=f'act_{handoff_id}',
        claim_id=claim_id,
        action_type='handoff_support',
        status=StaffActionStatus.COMPLETED,
        assigned_to='stf_demo',
        requested_outcome=handoff.requested_action,
        source_refs=[handoff_id],
        result=StaffActionResult(
            outcome='support_completed',
            summary='Support was completed.',
            reason_codes=['SUPPORT_NEED_MET'],
            source_refs=handoff.packet.source_refs,
        ),
        completed_by='stf_demo',
        created_at=handoff.created_at,
        completed_at=resolved_at,
    )
    repository._staff_actions[action.action_id] = action
    return handoff_id, action.action_id


def test_claimant_detail_projects_only_latest_resolved_support_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'resolved-support-claim')
    claim_id = str(created['claim']['claim_id'])  # type: ignore[index]
    handoff_id, action_id = _resolve_support_handoff(
        client, repository, auth_headers, claim_id, 'resolved-support', 'human_requested'
    )

    first = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    second = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert first.status_code == second.status_code == 200
    projection = first.json()['resolved_support_handoff']
    assert projection == second.json()['resolved_support_handoff']
    assert projection['handoff_id'] == handoff_id
    assert projection['type'] == HandoffType.HUMAN_SUPPORT.value
    assert projection['resolution_event_id'] == action_id
    assert (
        'resolved_support_handoff'
        not in client.get('/api/v1/claims', headers=auth_headers).json()['items'][0]
    )


def test_urgent_support_projection_rejects_unrelated_or_ordinary_records(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'urgent-resolved-support-claim')
    claim_id = str(created['claim']['claim_id'])  # type: ignore[index]
    handoff_id, action_id = _resolve_support_handoff(
        client, repository, auth_headers, claim_id, 'urgent-resolved-support', 'urgent'
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    resolved = repository.get_handoff(claim_id, handoff_id, claim.customer_id)
    assert resolved is not None

    ordinary = StaffActionRecord(
        action_id='act_ordinary_update',
        claim_id=claim_id,
        action_type='claimant_write_back',
        status=StaffActionStatus.COMPLETED,
        assigned_to='stf_demo',
        requested_outcome='Send an ordinary update.',
        source_refs=[],
        result=None,
        completed_by='stf_demo',
        created_at=resolved.created_at,
        completed_at=resolved.resolved_at,
    )
    repository._staff_actions[ordinary.action_id] = ordinary
    projection = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()[
        'resolved_support_handoff'
    ]
    assert projection['type'] == HandoffType.URGENT_SUPPORT.value
    assert projection['resolution_event_id'] == action_id

    internal = resolved.model_copy(
        update={
            'handoff_id': 'hnd_internal_review',
            'type': HandoffType.PROFESSIONAL_REVIEW,
            'support_need': None,
            'status': HandoffStatus.RESOLVED,
        }
    )
    repository.save_handoff(internal, claim.customer_id)
    unchanged = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert unchanged['resolved_support_handoff']['handoff_id'] == handoff_id


def test_new_support_start_replaces_resolution_and_terminal_claim_clears_it(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'support-replacement-claim')
    claim_id = str(created['claim']['claim_id'])  # type: ignore[index]
    first_handoff_id, _ = _resolve_support_handoff(
        client, repository, auth_headers, claim_id, 'support-replacement-first', 'human_requested'
    )
    first_claim = repository.get_claim_internal(claim_id)
    assert first_claim is not None
    assert (
        client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()[
            'resolved_support_handoff'
        ]['handoff_id']
        == first_handoff_id
    )

    started = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'support-replacement-second',
            'If-Match': str(first_claim.revision),
        },
        json={'reason': 'I need another support handoff.', 'support_need': 'human_requested'},
    )
    assert started.status_code == 201
    second_handoff_id = started.json()['handoff']['handoff_id']
    assert (
        client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()[
            'resolved_support_handoff'
        ]
        is None
    )

    second = repository.get_handoff(claim_id, second_handoff_id, first_claim.customer_id)
    assert second is not None
    resolved_at = second.created_at + timedelta(minutes=3)
    repository.save_handoff(
        second.model_copy(update={'status': HandoffStatus.RESOLVED, 'resolved_at': resolved_at}),
        first_claim.customer_id,
    )
    repository._staff_actions['act_second_support'] = StaffActionRecord(
        action_id='act_second_support',
        claim_id=claim_id,
        action_type='handoff_support',
        status=StaffActionStatus.COMPLETED,
        assigned_to='stf_demo',
        requested_outcome=second.requested_action,
        source_refs=[second_handoff_id],
        result=None,
        completed_by='stf_demo',
        created_at=second.created_at,
        completed_at=resolved_at,
    )
    replaced = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert replaced['resolved_support_handoff']['handoff_id'] == second_handoff_id

    current = repository.get_claim_internal(claim_id)
    assert current is not None
    terminal = current.model_copy(
        update={
            'terminal_disposition': ClaimTerminalDisposition(
                value=TerminalDispositionValue.ABANDONED,
                reason_code=TerminalDispositionReasonCode.ABANDONMENT_POLICY_APPLIED,
                source_refs=[second_handoff_id],
                recorded_by=ActorReference(actor_type='system', actor_id='system'),
                recorded_at=current.updated_at,
                recorded_revision=current.revision,
            )
        }
    )
    repository._claims[claim_id] = terminal
    assert (
        client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()[
            'resolved_support_handoff'
        ]
        is None
    )
