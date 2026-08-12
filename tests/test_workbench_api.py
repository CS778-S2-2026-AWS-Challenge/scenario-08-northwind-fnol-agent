from datetime import timedelta

from fastapi.testclient import TestClient

from backend.domain.models import (
    FraudSignal,
    MessageRecord,
    MessageVisibility,
    WorkflowState,
)
from backend.repositories.fixture import FixtureRepository


def _create_claim_with_context(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> tuple[str, str]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'workbench-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'workbench-message',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'workbench-message',
            'content': {
                'type': 'text',
                'text': 'A synthetic rear-end incident with no reported injuries.',
            },
            'evidence_refs': [],
        },
    ).json()
    evidence = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'workbench-evidence',
            'If-Match': str(turn['claim_revision']),
        },
        json={
            'kind': 'police_report',
            'status': 'pending_generation',
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
            'claimant_note': 'The synthetic report is not available yet.',
        },
    ).json()

    claim = repository.get_claim(claim_id, 'cus_demo')
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    decision = repository.find_agent_decision_for_trigger(
        claim_id,
        turn['claimant_message']['message_id'],
        'cus_demo',
    )
    evidence_record = repository.get_evidence(
        claim_id,
        evidence['evidence']['evidence_id'],
        'cus_demo',
    )
    assert claim is not None
    assert session is not None
    assert decision is not None
    assert evidence_record is not None

    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'route': 'professional_review',
                'claim_state': claim.claim_state.model_copy(
                    update={
                        'fraud_signal': FraudSignal.REVIEW_REQUIRED,
                        'workflow_state': WorkflowState.PROFESSIONAL_REVIEW,
                    }
                ),
            }
        ),
        expected_revision=claim.revision,
    )
    repository.save_session(
        session.model_copy(
            update={
                'summary': 'The claimant confirmed a synthetic rear-end incident.',
                'unresolved_questions': ['confirm:vehicle.drivable'],
                'pending_items': ['police_report'],
                'prior_commitments': ['The police report can be supplied later.'],
                'context_revision': claim.revision + 1,
            }
        )
    )
    repository.save_agent_decision(
        decision.model_copy(
            update={
                'proposed_signals': [
                    {
                        'code': 'HISTORY_INCONSISTENCY_REVIEW',
                        'status': 'review_required',
                    }
                ],
                'required_tools': [
                    {
                        'tool': 'claim_history_lookup',
                        'status': 'completed',
                        'result_refs': ['his_synthetic'],
                    }
                ],
            }
        ),
        'cus_demo',
    )
    repository.save_evidence(
        evidence_record.model_copy(
            update={'provenance': {'internal_object_ref': 'fixture://evidence/synthetic'}}
        ),
        'cus_demo',
    )
    repository.save_message(
        MessageRecord(
            message_id='msg_internal_note',
            claim_id=claim_id,
            session_id=session_id,
            actor='staff',
            visibility=MessageVisibility.INTERNAL_ONLY,
            content={'type': 'note', 'text': 'Internal review note.'},
            created_at=decision.created_at + timedelta(seconds=1),
        ),
        'cus_demo',
    )
    return claim_id, session_id


def test_staff_reads_complete_claim_detail_from_shared_state(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _create_claim_with_context(client, auth_headers, repository)
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None

    response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail['claim_id'] == stored_claim.claim_id
    assert detail['revision'] == stored_claim.revision
    assert detail['claim_state'] == stored_claim.claim_state.model_dump(mode='json')
    assert detail['route'] == stored_claim.route
    assert detail['active_session_id'] == session_id
    assert detail['form'] == stored_claim.model_dump(mode='json')['form']
    assert detail['evidence_summary'] == stored_claim.evidence_summary.model_dump(mode='json')
    assert detail['sessions'][0]['summary'].startswith('The claimant confirmed')
    assert detail['sessions'][0]['unresolved_questions'] == ['confirm:vehicle.drivable']
    assert detail['sessions'][0]['pending_items'] == ['police_report']
    assert detail['evidence'][0]['provenance']['internal_object_ref'].startswith('fixture://')
    assert detail['decisions'][0]['required_tools'][0]['tool'] == 'claim_history_lookup'
    assert detail['signals'][0]['code'] == 'HISTORY_INCONSISTENCY_REVIEW'
    assert any(message['message_id'] == 'msg_internal_note' for message in detail['messages'])
    assert detail['handoffs'] == []
    assert detail['staff_actions'] == []
    assert detail['customer_updates'] == []


def test_workbench_claim_detail_returns_documented_not_found(
    client: TestClient,
    staff_auth_headers: dict[str, str],
) -> None:
    response = client.get(
        '/api/v1/workbench/claims/clm_missing',
        headers=staff_auth_headers,
    )

    assert response.status_code == 404
    assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_workbench_rejects_claimant_and_invalid_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claimant = client.get('/api/v1/workbench/claims/clm_any', headers=auth_headers)
    invalid = client.get(
        '/api/v1/workbench/claims/clm_any',
        headers={'Authorization': 'Bearer not-valid'},
    )
    missing = client.get('/api/v1/workbench/claims/clm_any')

    assert claimant.status_code == 403
    assert claimant.json()['error']['code'] == 'ACCESS_DENIED'
    assert invalid.status_code == 401
    assert missing.status_code == 401


def test_claimant_projections_do_not_expose_workbench_only_data(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _create_claim_with_context(client, auth_headers, repository)

    staff = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    ).json()
    claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).json()
    claimant_messages = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers=auth_headers,
    ).json()
    claimant_evidence = client.get(
        f'/api/v1/claims/{claim_id}/evidence',
        headers=auth_headers,
    ).json()

    assert staff['claim_state']['fraud_signal'] == 'review_required'
    assert staff['route'] == 'professional_review'
    assert staff['signals']
    assert any(message['visibility'] == 'internal_only' for message in staff['messages'])
    assert 'claim_state' not in claimant_claim
    assert 'route' not in claimant_claim
    assert 'signals' not in claimant_claim
    assert 'decisions' not in claimant_claim
    assert 'sessions' not in claimant_claim
    assert all(
        message['message_id'] != 'msg_internal_note' for message in claimant_messages['items']
    )
    assert 'provenance' not in claimant_evidence['items'][0]
