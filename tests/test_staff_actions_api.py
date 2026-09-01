from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    MessageRecord,
    MessageVisibility,
)
from backend.repositories.fixture import FixtureRepository


def create_claim(client: TestClient, auth_headers: dict[str, str]) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'staff-action-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return response.json()['claim']  # type: ignore[no-any-return]


def test_staff_action_is_audited_and_writes_customer_safe_shared_state(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = create_claim(client, auth_headers)
    claim_id = str(claim['claim_id'])
    created = client.post(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions',
        headers={**staff_auth_headers, 'Idempotency-Key': 'create-review', 'If-Match': '1'},
        json={
            'action_type': 'coverage_review',
            'requested_outcome': 'Review the policy wording.',
            'source_refs': ['pol_fixture'],
        },
    )
    assert created.status_code == 201
    action = created.json()['action']
    assert action['assigned_to'] == 'stf_demo'
    assert created.json()['revision'] == 2

    completed = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions/{action["action_id"]}',
        headers={**staff_auth_headers, 'Idempotency-Key': 'complete-review', 'If-Match': '2'},
        json={
            'status': 'completed',
            'result': {
                'outcome': 'professional_review_completed',
                'summary': 'The fixture wording was reviewed.',
                'reason_codes': ['POLICY_SECTION_CONFIRMED'],
                'source_refs': ['pol_fixture'],
            },
            'state_changes': [
                {'path': 'claim_state.coverage', 'to': 'clear'},
                {'path': 'claim_state.workflow_state', 'to': 'ready_for_next'},
            ],
            'customer_update': {
                'summary': 'The policy review is complete and your report can continue.',
                'responsible_party': 'claimant',
            },
        },
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body['action']['completed_by'] == 'stf_demo'
    assert body['customer_update']['summary'].startswith('The policy review')
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == 3
    assert stored.claim_state.coverage.value == 'clear'
    assert stored.claim_state.workflow_state.value == 'ready_for_next'
    assert len(repository.list_customer_updates(claim_id)) == 1

    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant.status_code == 200
    projection = claimant.json()
    assert projection['customer_next_step']['summary'].startswith('The policy review')
    assert 'staff_actions' not in projection
    assert 'reason_codes' not in projection


def test_staff_write_back_requires_staff_current_revision_and_allowed_paths(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim = create_claim(client, auth_headers)
    claim_id = str(claim['claim_id'])
    endpoint = f'/api/v1/workbench/claims/{claim_id}/staff-actions'
    payload = {'action_type': 'review', 'requested_outcome': 'Review the fixture.'}
    claimant_attempt = client.post(
        endpoint,
        headers={**auth_headers, 'Idempotency-Key': 'claimant-create', 'If-Match': '1'},
        json=payload,
    )
    assert claimant_attempt.status_code == 403
    created = client.post(
        endpoint,
        headers={**staff_auth_headers, 'Idempotency-Key': 'staff-create', 'If-Match': '1'},
        json=payload,
    )
    action_id = created.json()['action']['action_id']
    stale = client.patch(
        f'{endpoint}/{action_id}',
        headers={**staff_auth_headers, 'Idempotency-Key': 'stale', 'If-Match': '1'},
        json={'status': 'in_progress'},
    )
    assert stale.status_code == 409
    forbidden = client.patch(
        f'{endpoint}/{action_id}',
        headers={**staff_auth_headers, 'Idempotency-Key': 'forbidden', 'If-Match': '2'},
        json={
            'status': 'completed',
            'result': {'outcome': 'done', 'summary': 'Done.', 'reason_codes': ['REVIEWED']},
            'state_changes': [{'path': 'customer_id', 'to': 'another_customer'}],
        },
    )
    assert forbidden.status_code == 422


def test_signal_decision_is_internal_idempotent_and_never_declares_fraud(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = create_claim(client, auth_headers)
    claim_id = str(claim['claim_id'])
    stored_before = repository.get_claim_internal(claim_id)
    assert stored_before is not None
    assert stored_before.active_session_id is not None
    repository.save_message(
        MessageRecord(
            message_id='sig-message',
            claim_id=claim_id,
            session_id=stored_before.active_session_id,
            actor=ActorType.SYSTEM,
            visibility=MessageVisibility.INTERNAL_ONLY,
            content={'type': 'review_signal', 'code': 'sig_fixture'},
            created_at=datetime.now(UTC),
        ),
        stored_before.customer_id,
    )
    endpoint = f'/api/v1/workbench/claims/{claim_id}/signals/sig_fixture/decisions'
    headers = {**staff_auth_headers, 'Idempotency-Key': 'signal-decision', 'If-Match': '1'}
    payload = {
        'decision': 'dismissed',
        'reason_codes': ['SOURCE_RECORD_NOT_COMPARABLE'],
        'summary': 'The fixture history concerns a different item.',
        'evidence_refs': ['his_fixture'],
    }
    response = client.post(endpoint, headers=headers, json=payload)
    replay = client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 201
    assert replay.json() == response.json()
    assert len(repository.list_signal_decisions(claim_id)) == 1
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.claim_state.fraud_signal.value == 'none'
    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers
    ).json()
    assert workbench['signals'][0]['code'] == 'sig_fixture'
    assert workbench['signals'][0]['decisions'][0]['decision'] == 'dismissed'
    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert 'signal_decision' not in claimant
    assert 'SOURCE_RECORD_NOT_COMPARABLE' not in str(claimant)


def test_signal_decision_finds_claim_decision_without_trigger_message(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = create_claim(client, auth_headers)
    claim_id = str(claim['claim_id'])
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.active_session_id is not None
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id='dec_without_trigger_message',
            claim_id=claim_id,
            session_id=stored.active_session_id,
            trigger_message_id='msg_not_persisted',
            action=AgentAction.PROCEED,
            reason_codes=['SIGNAL_REVIEW_REQUIRED'],
            customer_reason='Continue while the internal signal is reviewed.',
            customer_response='Your report can continue while Northwind reviews it.',
            proposed_signals=[
                {'signal_id': 'sig_without_trigger_message', 'status': 'review_required'}
            ],
            customer_next_step=stored.customer_next_step,
            authority=AgentAuthority(
                proposed_by='fixture_rule',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.AUTHORISED,
            ),
            resulting_revision=stored.revision,
            created_at=datetime.now(UTC),
        ),
        stored.customer_id,
    )

    response = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/sig_without_trigger_message/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'decision-without-trigger-message',
            'If-Match': '1',
        },
        json={
            'decision': 'confirmed',
            'reason_codes': ['CLAIM_LEVEL_SIGNAL_CONFIRMED'],
            'summary': 'The persisted claim-level signal requires review.',
            'evidence_refs': [],
        },
    )

    assert response.status_code == 201
    assert response.json()['signal_decision']['signal_id'] == 'sig_without_trigger_message'
    assert len(repository.list_signal_decisions(claim_id)) == 1


def test_staff_takeover_question_decision_and_writeback_share_claim_context(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = create_claim(client, auth_headers)
    claim_id = str(claim['claim_id'])
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.active_session_id is not None

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue-418-support',
            'If-Match': '1',
        },
        json={
            'reason': 'I need a staff member to help with the next step.',
            'support_need': 'human_requested',
        },
    )
    assert support.status_code == 201
    handoff_id = support.json()['handoff']['handoff_id']

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-418-takeover',
            'If-Match': '2',
        },
        json={},
    )
    assert accepted.status_code == 200
    assert accepted.json()['handoff']['status'] == 'accepted'
    assert accepted.json()['handoff']['assigned_to'] == 'stf_demo'

    question_text = 'Can you confirm whether the vehicle can still be driven safely?'
    question = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-418-question',
            'If-Match': '3',
        },
        json={'content': {'type': 'text', 'text': question_text}},
    )
    assert question.status_code == 200
    assert question.json()['message']['visibility'] == 'shared'
    question_id = question.json()['message']['message_id']

    action = client.post(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-418-decision',
            'If-Match': '4',
        },
        json={
            'action_type': 'staff_review',
            'requested_outcome': 'Record whether more claimant information is required.',
            'source_refs': [handoff_id, question_id],
        },
    )
    assert action.status_code == 201
    action_id = action.json()['action']['action_id']

    completed = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions/{action_id}',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'issue-418-writeback',
            'If-Match': '5',
        },
        json={
            'status': 'completed',
            'result': {
                'outcome': 'more_information_required',
                'summary': 'Vehicle usability must be confirmed before the next review step.',
                'reason_codes': ['CLAIMANT_CONFIRMATION_REQUIRED'],
                'source_refs': [handoff_id, question_id],
            },
            'state_changes': [{'path': 'claim_state.workflow_state', 'to': 'awaiting_evidence'}],
            'customer_update': {
                'summary': (
                    'Northwind needs your answer about whether the vehicle can still be driven.'
                ),
                'responsible_party': 'claimant',
                'related_refs': [question_id],
            },
        },
    )
    assert completed.status_code == 200
    assert completed.json()['revision'] == 6

    staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()
    assert staff['revision'] == 6
    assert staff['claim_state']['workflow_state'] == 'awaiting_evidence'
    assert staff['handoffs'][0]['assigned_to'] == 'stf_demo'
    assert staff['handoffs'][0]['status'] == 'in_progress'
    assert staff['staff_actions'][0]['result']['reason_codes'] == ['CLAIMANT_CONFIRMATION_REQUIRED']
    assert any(message['content'].get('text') == question_text for message in staff['messages'])

    claimant_history = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{stored.active_session_id}/messages?limit=100',
        headers=auth_headers,
    ).json()
    assert any(item['content'].get('text') == question_text for item in claimant_history['items'])

    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    assert claimant['workflow_state'] == 'awaiting_evidence'
    assert claimant['customer_next_step']['responsible_party'] == 'claimant'
    assert claimant['customer_next_step']['summary'].startswith('Northwind needs your answer')
    assert 'staff_actions' not in claimant
    assert 'handoffs' not in claimant
    assert 'CLAIMANT_CONFIRMATION_REQUIRED' not in str(claimant)
    assert 'Vehicle usability must be confirmed' not in str(claimant)
