import pytest
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository


def create_claim(client: TestClient, headers: dict[str, str], key: str) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


def submit_message(
    client: TestClient,
    headers: dict[str, str],
    claim_id: str,
    session_id: str,
    text: str,
    *,
    key: str,
    revision: int = 1,
) -> dict[str, object]:
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **headers,
            'Idempotency-Key': key,
            'If-Match': str(revision),
        },
        json={
            'client_message_id': key,
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def test_explicit_injury_interrupts_intake_and_persists_urgent_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, 'urgent-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)

    turn = submit_message(
        client,
        auth_headers,
        str(claim['claim_id']),
        str(session['session_id']),
        'A passenger is injured and the road is still unsafe.',
        key='urgent-message',
    )

    assert turn['form_changes'] == []
    assert turn['decision']['action'] == 'URGENT_HANDOFF'  # type: ignore[index]
    assert 'priority' not in turn['handoff']  # type: ignore[operator]
    summary = str(turn['handoff']['summary'])  # type: ignore[index]
    assert 'Contact local emergency services yourself' in summary
    assert 'contacted emergency services' not in summary
    assert 'queue' not in turn['handoff']  # type: ignore[operator]
    assert 'reason_codes' not in turn['handoff']  # type: ignore[operator]
    assert 'packet' not in turn['handoff']  # type: ignore[operator]

    handoffs = repository.list_handoffs(str(claim['claim_id']), 'cus_demo')
    stored_claim = repository.get_claim(str(claim['claim_id']), 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].priority.value == 'urgent'
    assert handoffs[0].queue == 'urgent_support'
    assert handoffs[0].source_message_id == turn['claimant_message']['message_id']  # type: ignore[index]
    assert stored_claim is not None
    assert stored_claim.claim_state.urgency.value == 'urgent'
    assert stored_claim.claim_state.workflow_state.value == 'professional_review'


@pytest.mark.parametrize(
    'description',
    [
        'Nobody was injured. A synthetic rear bumper was damaged.',
        'I was not hurt.',
        'I hurt the bumper.',
        'Everyone is safe and we are no longer in danger.',
        'A support person emailed me yesterday.',
        'I do not need to speak to a person.',
        'Another person saw the collision.',
        (
            'My parked car was hit from behind on Queen Street at 10:30 this morning. '
            'No one was injured and there is no continuing danger. The rear bumper is damaged.'
        ),
    ],
)
def test_non_injury_wording_does_not_trigger_urgent_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    description: str,
) -> None:
    created = create_claim(client, auth_headers, 'safe-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)

    turn = submit_message(
        client,
        auth_headers,
        str(claim['claim_id']),
        str(session['session_id']),
        description,
        key='safe-message',
    )

    assert turn['decision']['action'] == 'CONFIRM'  # type: ignore[index]
    assert turn['handoff'] is None
    assert turn['form_changes'][0]['field_code'] == 'incident.description'  # type: ignore[index]


def test_ordinary_intake_does_not_restart_after_urgent_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, 'paused-urgent-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    first_turn = submit_message(
        client,
        auth_headers,
        str(claim['claim_id']),
        str(session['session_id']),
        'A passenger is injured.',
        key='paused-urgent-message',
    )

    follow_up = submit_message(
        client,
        auth_headers,
        str(claim['claim_id']),
        str(session['session_id']),
        'Here is one more detail for the support team.',
        key='paused-follow-up',
        revision=int(str(first_turn['claim_revision'])),
    )

    assert follow_up['decision'] is None
    assert follow_up['agent_message'] is None
    assert follow_up['form_changes'] == []


def test_explicit_human_request_preserves_confirmed_context(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, 'human-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    first_turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        'A synthetic vehicle hit my parked car. Nobody was injured.',
        key='incident-message',
    )
    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'confirm-incident',
            'If-Match': str(first_turn['claim_revision']),
        },
        json={'field_codes': ['incident.description']},
    )
    assert confirmed.status_code == 200

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        'I want to speak to a person now.',
        key='human-message',
        revision=confirmed.json()['revision'],
    )

    assert turn['decision']['action'] == 'HANDOFF'  # type: ignore[index]
    assert turn['handoff']['support_need'] == 'human_requested'  # type: ignore[index]
    assert 'priority' not in turn['handoff']  # type: ignore[operator]
    handoff = repository.list_handoffs(claim_id, 'cus_demo')[0]
    assert handoff.priority.value == 'standard'
    assert handoff.applied_rule == 'prototype_immediate_transfer'
    assert handoff.packet.incident_summary == (
        'A synthetic vehicle hit my parked car. Nobody was injured.'
    )
    assert handoff.packet.form_snapshot['incident.description'].status.value == 'confirmed'
    assert handoff.packet.low_confidence_items == []
    assert handoff.requested_action.startswith('Contact the claimant')
    evaluation = repository.list_branch_evaluations(claim_id, 'cus_demo')[-1]
    support_branch = next(
        item for item in evaluation.branch_results if item.branch_id == 'human_support'
    )
    assert support_branch.status == 'active'
    assert turn['claimant_message']['message_id'] in support_branch.source_refs  # type: ignore[index]
    assert evaluation.handoff_intents[0]['support_need'] == 'human_requested'

    repeated = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        '@agent I still want to speak to a person.',
        key='repeated-human-message',
        revision=int(str(turn['claim_revision'])),
    )
    assert repeated['decision']['reason_codes'] == ['HANDOFF_ALREADY_QUEUED']  # type: ignore[index]
    assert len(repository.list_handoffs(claim_id, 'cus_demo')) == 1


@pytest.mark.parametrize(
    ('message', 'expected_need', 'expected_reason'),
    [
        ('I need an interpreter to continue.', 'accessibility_required', 'accessibility_need'),
        ('I am overwhelmed and cannot cope.', 'distress', 'distress_signal'),
    ],
)
def test_accessibility_and_distress_create_high_priority_source_linked_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    message: str,
    expected_need: str,
    expected_reason: str,
) -> None:
    key = f'{expected_need}-message'
    created = create_claim(client, auth_headers, f'{expected_need}-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])

    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        message,
        key=key,
    )
    replay = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        message,
        key=key,
    )

    assert replay == turn
    assert turn['decision']['action'] == 'HANDOFF'  # type: ignore[index]
    assert turn['handoff']['support_need'] == expected_need  # type: ignore[index]
    assert 'priority' not in turn['handoff']  # type: ignore[operator]
    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].priority.value == 'high'
    assert handoffs[0].trigger.value == expected_reason
    evaluation = repository.list_branch_evaluations(claim_id, 'cus_demo')[-1]
    support_branch = next(
        item for item in evaluation.branch_results if item.branch_id == 'human_support'
    )
    assert support_branch.status == 'active'
    assert turn['claimant_message']['message_id'] in support_branch.source_refs  # type: ignore[index]
    assert evaluation.handoff_intents[0]['support_need'] == expected_need


def test_support_endpoint_is_revision_protected_idempotent_and_claimant_safe(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, 'support-claim')
    claim = created['claim']
    assert isinstance(claim, dict)
    claim_id = str(claim['claim_id'])
    endpoint = f'/api/v1/claims/{claim_id}/support-requests'
    payload = {
        'reason': 'I want to speak to a person.',
        'support_need': 'human_requested',
        'preferred_channel': 'phone',
    }
    headers = {**auth_headers, 'Idempotency-Key': 'support-1', 'If-Match': '1'}

    response = client.post(endpoint, headers=headers, json=payload)
    replay = client.post(endpoint, headers=headers, json=payload)
    conflicting_key = client.post(
        endpoint,
        headers=headers,
        json={**payload, 'support_need': 'urgent'},
    )
    duplicate = client.post(
        endpoint,
        headers={**auth_headers, 'Idempotency-Key': 'support-2', 'If-Match': '2'},
        json=payload,
    )
    stale = client.post(
        endpoint,
        headers={**auth_headers, 'Idempotency-Key': 'support-stale', 'If-Match': '1'},
        json={**payload, 'support_need': 'accessibility_required'},
    )

    assert response.status_code == 201
    assert response.json()['revision'] == 2
    evaluation = repository.list_branch_evaluations(claim_id, 'cus_demo')[-1]
    assert evaluation.recomputation_reason == 'handoff_created'
    assert evaluation.resulting_claim_revision == 2
    assert replay.json() == response.json()
    assert duplicate.json() == response.json()
    assert len(repository.list_handoffs(claim_id, 'cus_demo')) == 1
    assert conflicting_key.status_code == 409
    assert conflicting_key.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert set(response.json()['handoff']) == {
        'handoff_id',
        'status',
        'support_need',
        'summary',
        'created_at',
    }


def test_support_endpoint_enforces_claim_ownership(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers, 'owned-claim')
    claim = created['claim']
    assert isinstance(claim, dict)

    response = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/support-requests',
        headers={
            'Authorization': 'Bearer another-synthetic-claimant',
            'Idempotency-Key': 'not-owner',
            'If-Match': '1',
        },
        json={
            'reason': 'I want support.',
            'support_need': 'human_requested',
        },
    )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
