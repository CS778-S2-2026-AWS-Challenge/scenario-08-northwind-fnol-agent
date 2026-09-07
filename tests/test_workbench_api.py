from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    ContentsItem,
    ContentsLossType,
    ContentsOwnership,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceStatus,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    FormStatus,
    FraudSignal,
    IntegrationSource,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    StructuredFormField,
    WorkflowState,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.staff_access import (
    ClaimStaffAccess,
    claim_staff_access,
    require_claim_collaborator,
)
from backend.services.support import now_utc


def test_public_claim_and_workbench_detail_use_role_safe_contents_projection(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _, _ = _request_staff_support(
        client, auth_headers, repository, key_suffix='contents-projection'
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    item = ContentsItem(
        item_id='item_projection_1',
        description='Synthetic laptop',
        category='electronics',
        loss_type=ContentsLossType.DAMAGED,
        ownership=ContentsOwnership.OWNED,
        estimated_value={'amount': 1200.0, 'currency': 'NZD'},
        source='staff',
        source_refs=['msg_public', 'staff_action_internal', 'ret_policy_internal'],
        status='proposed',
        needed_for='later_action',
        confidence=0.6,
        updated_at=now_utc(),
        updated_by={'actor_type': 'staff', 'actor_id': 'stf_internal'},
    )
    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'contents_items': [item],
                'form': {
                    **claim.form,
                    'claimant.client_number': StructuredFormField(
                        value='internal-client',
                        source='staff',
                        status='confirmed',
                        needed_for='later_action',
                        updated_at=now_utc(),
                        updated_by={'actor_type': 'staff', 'actor_id': 'stf_internal'},
                    ),
                },
            }
        ),
        expected_revision=claim.revision,
    )

    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant.status_code == 200
    claimant_item = claimant.json()['contents_items'][0]
    assert claimant_item['item_id'] == 'item_projection_1'
    assert claimant_item['source_refs'] == ['msg_public']
    assert 'confidence' not in claimant_item
    assert 'updated_by' not in claimant_item
    assert 'claimant.client_number' not in claimant.json()['form']

    staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert staff.status_code == 200
    staff_item = staff.json()['contents_items'][0]
    assert staff_item['source_refs'] == item.source_refs
    assert staff_item['confidence'] == 0.6
    assert staff_item['updated_by']['actor_id'] == 'stf_internal'


def _provision_staff(
    app: FastAPI,
    client: TestClient,
    *,
    email: str,
    display_name: str,
) -> tuple[str, dict[str, str]]:
    password = 'workbench-test-password'
    account = app.state.staff_identity_repository.provision_account(
        email,
        password,
        display_name,
        ('claims_professional',),
    )
    response = client.post(
        '/api/v1/staff/auth/sessions',
        json={'email': email, 'password': password},
    )
    assert response.status_code == 201
    return account.staff_id, {
        'Authorization': f'Bearer {response.json()["access_token"]}',
    }


def _request_staff_support(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    *,
    key_suffix: str = '',
) -> tuple[str, str, int]:
    claim_id, _ = _create_claim_with_context(
        client,
        auth_headers,
        repository,
        key_suffix=key_suffix,
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    response = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': f'support-{claim_id}',
            'If-Match': str(claim.revision),
        },
        json={
            'reason': 'I need a claims professional to help me continue.',
            'support_need': 'human_requested',
            'preferred_channel': 'in_app',
        },
    )
    assert response.status_code == 201
    body = response.json()
    return claim_id, body['handoff']['handoff_id'], body['revision']


def _create_claim_with_context(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    *,
    key_suffix: str = '',
) -> tuple[str, str]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'workbench-claim{key_suffix}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': f'workbench-message{key_suffix}',
            'If-Match': '1',
        },
        json={
            'client_message_id': f'workbench-message{key_suffix}',
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
            'Idempotency-Key': f'workbench-evidence{key_suffix}',
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


def test_staff_reads_progressive_claim_detail_and_paged_resources(
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
    assert detail['incident']['family'] == 'motor'
    assert detail['lifecycle_state'] == 'professional_review'
    assert detail['section_summaries']['fields']['total'] == len(stored_claim.form)
    assert 'form' not in detail
    assert 'evidence' not in detail
    assert 'messages' not in detail

    fields = client.get(
        f'/api/v1/workbench/claims/{claim_id}/fields', headers=staff_auth_headers
    ).json()
    sessions = client.get(
        f'/api/v1/workbench/claims/{claim_id}/sessions', headers=staff_auth_headers
    ).json()
    messages = client.get(
        f'/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
        headers=staff_auth_headers,
    ).json()
    evidence = client.get(
        f'/api/v1/workbench/claims/{claim_id}/evidence', headers=staff_auth_headers
    ).json()
    signals = client.get(
        f'/api/v1/workbench/claims/{claim_id}/signals', headers=staff_auth_headers
    ).json()
    assert {item['code'] for item in fields['items']} == set(stored_claim.form)
    assert sessions['items'][0]['summary'].startswith('The claimant confirmed')
    assert sessions['items'][0]['unresolved_questions'] == ['confirm:vehicle.drivable']
    assert sessions['items'][0]['pending_items'] == ['police_report']
    assert evidence['items'][0]['provenance']['internal_object_ref'].startswith('fixture://')
    assert signals['items'][0]['code'] == 'HISTORY_INCONSISTENCY_REVIEW'
    assert any(item['message_id'] == 'msg_internal_note' for item in messages['items'])


def test_staff_detail_projects_source_context_and_disputed_or_conflicting_gaps(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository)
    claim = repository.get_claim_internal(claim_id)
    evidence = repository.list_evidence(claim_id, 'cus_demo')[0]
    assert claim is not None
    field_code, field = next(iter(claim.form.items()))
    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'form': {
                    **claim.form,
                    field_code: field.model_copy(
                        update={'status': FormStatus.DISPUTED, 'source_refs': ['msg_dispute']}
                    ),
                },
            }
        ),
        expected_revision=claim.revision,
    )
    repository.save_evidence(
        evidence.model_copy(
            update={
                'status': EvidenceStatus.INCONSISTENT,
                'file_status': EvidenceFileStatus.READY,
            }
        ),
        'cus_demo',
    )

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()

    gaps = {
        (item['kind'], item['code']): item for item in detail['work_summary']['missing_information']
    }
    assert gaps[('field', field_code)]['status'] == 'disputed'
    assert gaps[('field', field_code)]['responsible_party'] == 'claims_professional'
    assert gaps[('evidence', evidence.kind)]['status'] == 'conflicting'
    sources = {item['record_ref']: item for item in detail['source_summary']['items']}
    assert detail['source_summary']['status'] == 'available'
    assert sources[f'field:{field_code}']['source_refs'] == ['msg_dispute']
    assert sources[evidence.evidence_id]['status'] == 'inconsistent'
    assert sources[evidence.evidence_id]['related_fields'] == evidence.related_fields


def test_staff_detail_distinguishes_empty_and_unavailable_source_context(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'empty-source-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()
    claim_id = created['claim']['claim_id']
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository.save_claim(
        claim.model_copy(update={'revision': claim.revision + 1, 'form': {}}),
        expected_revision=claim.revision,
    )

    empty = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()
    assert empty['source_summary'] == {'status': 'empty', 'items': [], 'limitation': None}

    def unavailable_external_records(_claim_id: str) -> list[ExternalTaskRecord]:
        raise RuntimeError('synthetic unavailable source')

    monkeypatch.setattr(
        repository,
        'list_external_tasks_internal',
        unavailable_external_records,
    )
    unavailable = client.get(
        f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers
    ).json()
    assert unavailable['source_summary']['status'] == 'unavailable'
    assert unavailable['source_summary']['limitation']
    assert any(
        item['status'] == 'unavailable'
        for item in unavailable['work_summary']['missing_information']
    )


def test_staff_detail_preserves_unknown_external_outcome_as_an_uncertain_gap(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(
        client, auth_headers, repository, key_suffix='unknown-external'
    )
    recorded_at = now_utc()
    task = ExternalTaskRecord(
        task_id='tsk_unknown',
        claim_id=claim_id,
        service_identity='damage_assessment',
        requested_action='request_assessment',
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
        delivery=ExternalTaskDelivery.SUBMITTED,
        delivery_evidence='delivery_receipt_unknown',
        failure_code=ExternalTaskFailureCode.TIMEOUT,
        created_at=recorded_at,
        updated_at=recorded_at,
    )
    repository.save_external_task(task, 'cus_demo')

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()
    gap = next(
        item
        for item in detail['work_summary']['missing_information']
        if item['kind'] == 'external_service'
    )
    source = next(
        item for item in detail['source_summary']['items'] if item['record_ref'] == task.task_id
    )

    assert gap['status'] == 'uncertain'
    assert gap['blocked_action'] == task.requested_action
    assert gap['source_refs'] == [task.task_id, task.delivery_evidence]
    assert source['source_label'] == 'Controlled fixture service'
    assert source['status'] == 'unknown_outcome'


def test_staff_primary_action_pair_resolves_to_the_exact_non_blocked_action(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id, _ = _request_staff_support(client, auth_headers, repository)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository.save_claim(
        claim.model_copy(
            update={'revision': claim.revision + 1, 'assignee_id': 'stf_another_owner'}
        ),
        expected_revision=claim.revision,
    )

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()
    accept = next(
        action
        for action in detail['allowed_actions']
        if action['action_code'] == 'human.accept_handoff' and action['target_ref'] == handoff_id
    )
    primary = next(
        action
        for action in detail['allowed_actions']
        if action['action_code'] == detail['work_summary']['primary_action_code']
        and action['target_ref'] == detail['work_summary']['primary_action_target_ref']
    )

    assert accept['availability'] == 'blocked'
    assert primary['action_code'] == 'ownership.request_cowork'
    assert primary['availability'] != 'blocked'


def test_staff_lists_claims_for_workbench_queue(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository)

    response = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload['page'] == {'next_cursor': None}
    item = next(item for item in payload['items'] if item['claim_id'] == claim_id)
    assert item['claimant']['customer_id'] == 'cus_demo'
    assert item['work_summary']['queue_key'] == 'professional_review'
    assert item['priority_projection']['level'] == 'standard'
    assert item['work_summary']['primary_action_code'] is None
    assert item['work_summary']['primary_action_target_ref'] is None
    assert item['incident']['family'] == 'motor'
    assert item['work_summary']['missing_information']
    assert 'pending_evidence' not in item


def test_staff_workbench_queue_uses_bounded_cursor_pagination(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    for index in range(3):
        created = client.post(
            '/api/v1/claims',
            headers={**auth_headers, 'Idempotency-Key': f'workbench-page-{index}'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201

    first = client.get(
        '/api/v1/workbench/claims?limit=2',
        headers=staff_auth_headers,
    )
    assert first.status_code == 200
    first_page = first.json()
    assert len(first_page['items']) == 2
    assert first_page['page']['next_cursor'] is not None

    second = client.get(
        f'/api/v1/workbench/claims?limit=2&cursor={first_page["page"]["next_cursor"]}',
        headers=staff_auth_headers,
    )
    assert second.status_code == 200
    second_page = second.json()
    assert second_page['items']
    assert {item['claim_id'] for item in first_page['items']}.isdisjoint(
        item['claim_id'] for item in second_page['items']
    )
    assert second_page['page']['next_cursor'] is None

    invalid = client.get(
        '/api/v1/workbench/claims?limit=2&cursor=not-a-cursor',
        headers=staff_auth_headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'


def test_workbench_claim_list_rejects_claimant_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get('/api/v1/workbench/claims', headers=auth_headers)

    assert response.status_code == 403

    metadata = client.get('/api/v1/workbench/claims/filter-metadata', headers=auth_headers)
    assert metadata.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'


def test_workbench_filter_metadata_and_query_include_routine_priority(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'routine-priority-filter'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']

    metadata = client.get('/api/v1/workbench/claims/filter-metadata', headers=staff_auth_headers)
    filtered = client.get('/api/v1/workbench/claims?priority=routine', headers=staff_auth_headers)

    assert metadata.status_code == 200
    assert {'value': 'routine', 'label': 'Routine'} in metadata.json()['priorities']
    assert filtered.status_code == 200
    assert [item['claim_id'] for item in filtered.json()['items']] == [claim_id]
    assert filtered.json()['items'][0]['priority_projection']['level'] == 'routine'


def test_created_claim_route_does_not_override_workbench_queue(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository)
    stored_claim = repository.get_claim_internal(claim_id)
    assert stored_claim is not None
    # Fixture seeding: this precondition is outside the save_claim() transaction
    # boundary (pointer change or revision-neutral write), so it is stored directly.
    repository._claims[stored_claim.claim_id] = stored_claim.model_copy(
        update={
            'route': 'standard_motor_intake',
            'claim_state': stored_claim.claim_state.model_copy(
                update={'workflow_state': WorkflowState.CREATED}
            ),
        }
    )

    response = client.get(
        '/api/v1/workbench/claims?view=created_routed',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    item = next(item for item in response.json()['items'] if item['claim_id'] == claim_id)
    assert item['work_summary']['queue_key'] == 'created_routed'
    assert item['lifecycle_state'] == 'created'


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
    staff_signals = client.get(
        f'/api/v1/workbench/claims/{claim_id}/signals', headers=staff_auth_headers
    ).json()
    staff_messages = client.get(
        f'/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
        headers=staff_auth_headers,
    ).json()
    assert staff['work_summary']['risk_signals']
    assert staff_signals['items']
    assert any(message['visibility'] == 'internal_only' for message in staff_messages['items'])
    assert 'claim_state' not in claimant_claim
    assert 'route' not in claimant_claim
    assert 'signals' not in claimant_claim
    assert 'decisions' not in claimant_claim
    assert 'sessions' not in claimant_claim
    assert 'source_summary' not in claimant_claim
    assert 'work_summary' not in claimant_claim
    assert 'allowed_actions' not in claimant_claim
    assert all(
        message['message_id'] != 'msg_internal_note' for message in claimant_messages['items']
    )
    assert 'provenance' not in claimant_evidence['items'][0]


def test_staff_receives_complete_handoff_packet_while_claimant_projection_is_safe(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository)
    stored_claim = repository.get_claim_internal(claim_id)
    assert stored_claim is not None

    claimant_response = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'workbench-handoff',
            'If-Match': str(stored_claim.revision),
        },
        json={
            'reason': 'I need a person to continue this synthetic report.',
            'support_need': 'human_requested',
            'preferred_channel': 'phone',
        },
    )
    assert claimant_response.status_code == 201

    stored_handoffs = repository.list_handoffs(claim_id, stored_claim.customer_id)
    assert len(stored_handoffs) == 1
    staff_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert staff_response.status_code == 200
    staff_detail = staff_response.json()
    source_kinds = {item['kind'] for item in staff_detail['source_summary']['items']}
    assert {'handoff', 'authorised_action'} <= source_kinds
    assert not any(
        item['kind'] == 'handoff' and item['code'] in stored_handoffs[0].packet.evidence_refs
        for item in staff_detail['work_summary']['missing_information']
    )
    handoffs_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff_auth_headers
    )
    assert handoffs_response.status_code == 200
    staff_handoff = handoffs_response.json()['items'][0]
    assert staff_handoff == stored_handoffs[0].model_dump(mode='json')
    assert staff_handoff['queue'] == 'claimant_support'
    assert staff_handoff['reason_codes'] == ['HUMAN_SUPPORT_REQUESTED']
    assert staff_handoff['requested_action'].startswith('Contact the claimant')
    assert staff_handoff['packet']['pending_items'] == staff_handoff['packet']['evidence_refs']
    assert staff_handoff['packet']['evidence'] == [
        {
            'evidence_id': staff_handoff['packet']['evidence_refs'][0],
            'kind': 'police_report',
            'status': 'pending_generation',
            'file_status': 'not_available',
            'source': 'claimant',
            'visibility': 'shared',
            'original_filename': None,
            'media_type': None,
            'size_bytes': None,
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
            'claimant_note': 'The synthetic report is not available yet.',
        }
    ]
    assert staff_handoff['packet']['source_refs']
    assert staff_handoff['packet']['promised_next_step'].startswith(
        'A Northwind support request has been queued'
    )

    claimant_handoff = claimant_response.json()['handoff']
    assert set(claimant_handoff) == {
        'handoff_id',
        'status',
        'priority',
        'support_need',
        'summary',
        'created_at',
    }
    assert {
        'queue',
        'reason_codes',
        'reason',
        'requested_action',
        'applied_rule',
        'packet',
        'source_message_id',
        'assigned_to',
    }.isdisjoint(claimant_handoff)
    assert claimant_claim.status_code == 200
    assert 'handoffs' not in claimant_claim.json()


def test_workbench_detail_reads_shared_claim_creation_and_routing_results(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created_response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'workbench-routing-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    claim = created['claim']
    session = created['session']
    claim_id = claim['claim_id']
    session_id = session['session_id']
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None

    create_decision = AgentDecisionRecord(
        decision_id='dec_workbench_create',
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id='msg_workbench_create',
        action=AgentAction.CREATE_CLAIM,
        reason_codes=['CLAIM_CREATION_AUTHORISED'],
        customer_reason='A controlled fixture authorised claim creation.',
        customer_response='The controlled fixture can create the claim.',
        customer_next_step=CustomerNextStep(
            status='authorised',
            summary='The claim can be created.',
            responsible_party=ResponsibleParty.SYSTEM,
        ),
        authority=AgentAuthority(
            proposed_by='fixture_rule',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=stored.revision,
        created_at=stored.updated_at,
    )
    repository.save_agent_decision(create_decision, stored.customer_id)
    creation_response = client.post(
        '/internal/v1/claims/create',
        headers={'Authorization': 'Bearer synthetic-integration'},
        json={
            'working_claim_id': claim_id,
            'claim_revision': stored.revision,
            'authorised_decision_id': create_decision.decision_id,
            'confirmed_form': {},
            'evidence_refs': [],
            'pending_evidence': [],
            'route': 'standard_motor_intake',
        },
    )
    assert creation_response.status_code == 201
    creation = creation_response.json()

    created_claim = repository.get_claim_internal(claim_id)
    assert created_claim is not None
    consent_ref = 'cns_workbench_assessor'
    consent_time = now_utc()
    consent = ExternalServiceConsent(
        consent_ref=consent_ref,
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        permitted_fields=[
            'claim_id',
            'external_claim_id',
            'authorisation_ref',
            'claimant_consent_ref',
            'requested_action',
            'location.region',
        ],
        status=ExternalServiceConsentStatus.GRANTED,
        granted_by=ActorReference(
            actor_type=ActorType.CLAIMANT,
            actor_id=created_claim.customer_id,
        ),
        granted_at=consent_time,
    )
    consented_claim = created_claim.model_copy(
        update={
            'external_service_consents': [consent],
            'revision': created_claim.revision + 1,
            'updated_at': consent_time,
        }
    )
    repository.save_claim(consented_claim, expected_revision=created_claim.revision)
    route_decision = AgentDecisionRecord(
        decision_id='dec_workbench_assessor',
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id='msg_workbench_assessor',
        action=AgentAction.PROCEED,
        reason_codes=['ASSESSOR_RULE_AUTHORISED'],
        customer_reason='A controlled fixture authorised assessor routing.',
        customer_response='The controlled fixture can request assessor routing.',
        customer_next_step=consented_claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='fixture_rule',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=consented_claim.revision,
        created_at=consented_claim.updated_at,
    )
    repository.save_agent_decision(route_decision, consented_claim.customer_id)
    routing_response = client.post(
        '/internal/v1/assessors/route',
        headers={'Authorization': 'Bearer synthetic-integration'},
        json={
            'claim_id': claim_id,
            'external_claim_id': creation['external_claim_id'],
            'authorisation_ref': route_decision.decision_id,
            'claimant_consent_ref': consent_ref,
            'requested_action': 'vehicle_damage_assessment',
            'location': {'region': 'Auckland'},
        },
    )
    assert routing_response.status_code == 201
    routing = routing_response.json()

    response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    claimant_response = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert claimant_response.status_code == 200
    assert 'external_service_consents' not in claimant_response.json()
    detail = response.json()
    final_claim = repository.get_claim_internal(claim_id)
    assert final_claim is not None
    assert detail['revision'] == final_claim.revision
    assert detail['claim_state']['workflow_state'] == 'created'
    assert detail['integration_summary']['claim_creation_status'] == 'created'
    assert detail['integration_summary']['assessor_routing_status'] == 'assigned'
    assert detail['customer_next_step']['status'] == 'assessor_assigned'
    assert detail['customer_next_step']['expected_by'] == routing['expected_by']
    queue_response = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    queue_item = next(
        item for item in queue_response.json()['items'] if item['claim_id'] == claim_id
    )
    assert queue_item['ownership']['primary_assignee']['staff_id'] == 'stf_demo'


def test_handoff_acceptance_is_atomic_revision_safe_and_idempotent(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id, revision = _request_staff_support(client, auth_headers, repository)
    headers = {
        **staff_auth_headers,
        'Idempotency-Key': 'accept-handoff-once',
        'If-Match': str(revision),
    }

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers=headers,
        json={},
    )
    replay = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers=headers,
        json={},
    )

    assert accepted.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == accepted.json()
    claim = repository.get_claim_internal(claim_id)
    handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    assert claim is not None
    assert handoff is not None
    assert claim.assignee_id == 'stf_demo'
    assert claim.revision == revision + 1
    assert handoff.status.value == 'accepted'
    assert handoff.assigned_to == 'stf_demo'

    stale = client.post(
        f'/api/v1/workbench/claims/{claim_id}/requeue',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'stale-requeue',
            'If-Match': str(revision),
        },
        json={'reason': 'This request intentionally uses a stale revision.'},
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == claim.revision


def test_claim_conversations_list_only_sessions_held_by_current_staff(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    other_id, other_headers = _provision_staff(
        app,
        client,
        email='conversation-owner@example.invalid',
        display_name='Conversation Owner',
    )
    owned_claim, owned_handoff, owned_revision = _request_staff_support(
        client, auth_headers, repository, key_suffix='-conversation-owned'
    )
    owned = client.post(
        f'/api/v1/workbench/claims/{owned_claim}/handoffs/{owned_handoff}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'conversation-demo-owner',
            'If-Match': str(owned_revision),
        },
        json={},
    )
    assert owned.status_code == 200

    other_claim, other_handoff, other_revision = _request_staff_support(
        client, auth_headers, repository, key_suffix='-conversation-other'
    )
    other = client.post(
        f'/api/v1/workbench/claims/{other_claim}/handoffs/{other_handoff}/accept',
        headers={
            **other_headers,
            'Idempotency-Key': 'conversation-other-owner',
            'If-Match': str(other_revision),
        },
        json={},
    )
    assert other.status_code == 200
    other_stored = repository.get_claim_internal(other_claim)
    assert other_stored is not None
    assert other_stored.assignee_id == other_id

    listing = client.get('/api/v1/workbench/conversations', headers=staff_auth_headers)

    assert listing.status_code == 200
    assert listing.json()['page'] == {'next_cursor': None}
    assert {item['claim_id'] for item in listing.json()['items']} == {owned_claim}
    assert all(item['kind'] == 'claim' for item in listing.json()['items'])
    assert all(item['conversation_id'].startswith('claim:ses_') for item in listing.json()['items'])


def test_non_owner_cowork_request_owner_approval_and_coworker_message(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    coworker_id, coworker_headers = _provision_staff(
        app,
        client,
        email='coworker@example.invalid',
        display_name='Cowork Claims Professional',
    )
    claim_id, handoff_id, revision = _request_staff_support(client, auth_headers, repository)
    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'cowork-owner-accept',
            'If-Match': str(revision),
        },
        json={},
    )
    assert accepted.status_code == 200

    owner_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers
    ).json()
    owner_actions = {action['action_code']: action for action in owner_detail['allowed_actions']}
    assert [item['field_code'] for item in owner_actions['ownership.invite_cowork']['inputs']] == [
        'staff_id',
        'reason',
    ]
    assert [
        item['field_code'] for item in owner_actions['ownership.request_transfer']['inputs']
    ] == ['target_staff_id', 'reason']
    assert [item['field_code'] for item in owner_actions['ownership.requeue']['inputs']] == [
        'reason'
    ]

    coworker_detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}', headers=coworker_headers
    ).json()
    cowork_request_action = next(
        action
        for action in coworker_detail['allowed_actions']
        if action['action_code'] == 'ownership.request_cowork'
    )
    assert [item['field_code'] for item in cowork_request_action['inputs']] == ['reason']
    unprojected_target = client.post(
        f'/api/v1/workbench/claims/{claim_id}/cowork-requests',
        headers={
            **coworker_headers,
            'Idempotency-Key': 'cowork-unprojected-target',
            'If-Match': str(accepted.json()['revision']),
        },
        json={
            'staff_id': coworker_id,
            'reason': 'I can help with the claimant conversation.',
        },
    )
    assert unprojected_target.status_code == 422
    assert unprojected_target.json()['error']['code'] == 'VALIDATION_ERROR'

    requested = client.post(
        f'/api/v1/workbench/claims/{claim_id}/cowork-requests',
        headers={
            **coworker_headers,
            'Idempotency-Key': 'cowork-request',
            'If-Match': str(accepted.json()['revision']),
        },
        json={'reason': 'I can help with the claimant conversation.'},
    )
    assert requested.status_code == 201
    request_body = requested.json()
    assert request_body['request']['requested_by'] == coworker_id
    assert request_body['request']['target_staff_id'] == coworker_id
    assert request_body['request']['primary_owner_id'] == 'stf_demo'

    approved = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/collaboration-requests/'
        f'{request_body["request"]["request_id"]}',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'cowork-approve',
            'If-Match': str(request_body['revision']),
        },
        json={'decision': 'accepted'},
    )
    assert approved.status_code == 200
    assert approved.json()['coworker']['staff_id'] == coworker_id

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=coworker_headers)
    assert detail.status_code == 200
    assert detail.json()['ownership']['current_staff_access'] == 'coworker'
    assert detail.json()['ownership']['pending_cowork_requests'] == 0
    assert any(
        action['action_code'] == 'conversation.send_claimant_message'
        for action in detail.json()['allowed_actions']
    )

    sent = client.post(
        f'/api/v1/workbench/claims/{claim_id}/messages',
        headers={
            **coworker_headers,
            'Idempotency-Key': 'cowork-message',
            'If-Match': str(approved.json()['revision']),
        },
        json={'content': {'type': 'text', 'text': 'I am helping with your Claim now.'}},
    )
    assert sent.status_code == 200, sent.json()
    assert sent.json()['message']['actor'] == 'staff'
    assert sent.json()['message']['visibility'] == 'shared'


def test_transfer_acceptance_updates_handoff_and_revokes_existing_coworkers(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    coworker_id, coworker_headers = _provision_staff(
        app,
        client,
        email='existing-coworker@example.invalid',
        display_name='Existing Coworker',
    )
    target_id, target_headers = _provision_staff(
        app,
        client,
        email='transfer-target@example.invalid',
        display_name='Transfer Target',
    )
    claim_id, handoff_id, revision = _request_staff_support(client, auth_headers, repository)
    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'transfer-owner-accept',
            'If-Match': str(revision),
        },
        json={},
    ).json()
    invited = client.post(
        f'/api/v1/workbench/claims/{claim_id}/cowork-requests',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'owner-invites-coworker',
            'If-Match': str(accepted['revision']),
        },
        json={
            'staff_id': coworker_id,
            'reason': 'Help review the active claimant conversation.',
        },
    ).json()
    cowork_accepted = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/collaboration-requests/'
        f'{invited["request"]["request_id"]}',
        headers={
            **coworker_headers,
            'Idempotency-Key': 'coworker-accepts-invite',
            'If-Match': str(invited['revision']),
        },
        json={'decision': 'accepted'},
    ).json()

    transfer = client.post(
        f'/api/v1/workbench/claims/{claim_id}/transfer-requests',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'owner-transfer-request',
            'If-Match': str(cowork_accepted['revision']),
        },
        json={
            'target_staff_id': target_id,
            'reason': 'The target staff member will continue this Claim.',
        },
    )
    assert transfer.status_code == 201
    transfer_body = transfer.json()

    transfer_accepted = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/collaboration-requests/'
        f'{transfer_body["request"]["request_id"]}',
        headers={
            **target_headers,
            'Idempotency-Key': 'target-accepts-transfer',
            'If-Match': str(transfer_body['revision']),
        },
        json={'decision': 'accepted'},
    )
    assert transfer_accepted.status_code == 200

    claim = repository.get_claim_internal(claim_id)
    handoff = repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    coworkers = [item for item in repository._claim_coworkers.values() if item.claim_id == claim_id]
    assert claim is not None
    assert handoff is not None
    assert claim.assignee_id == target_id
    assert handoff.assigned_to == target_id
    assert coworkers
    assert all(not item.active and item.revoked_at is not None for item in coworkers)
    former_coworker = client.get(
        f'/api/v1/workbench/claims/{claim_id}', headers=coworker_headers
    ).json()
    target = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=target_headers).json()
    assert former_coworker['ownership']['current_staff_access'] == 'read_only'
    assert target['ownership']['current_staff_access'] == 'primary'


def test_requeue_refuses_while_protected_staff_work_is_active(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id, revision = _request_staff_support(client, auth_headers, repository)
    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'protected-owner-accept',
            'If-Match': str(revision),
        },
        json={},
    ).json()
    action = client.post(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'protected-action',
            'If-Match': str(accepted['revision']),
        },
        json={'action_type': 'claimant_support'},
    )
    assert action.status_code == 201
    action_body = action.json()
    in_progress = client.patch(
        f'/api/v1/workbench/claims/{claim_id}/staff-actions/{action_body["action"]["action_id"]}',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'start-protected-action',
            'If-Match': str(action_body['revision']),
        },
        json={'status': 'in_progress'},
    )
    assert in_progress.status_code == 200

    requeue = client.post(
        f'/api/v1/workbench/claims/{claim_id}/requeue',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'blocked-requeue',
            'If-Match': str(in_progress.json()['revision']),
        },
        json={'reason': 'Return this Claim for another professional.'},
    )
    assert requeue.status_code == 403
    assert requeue.json()['error']['code'] == 'ACCESS_DENIED'
    assert requeue.json()['error']['details'] == [
        {'field': 'action_code', 'reason': 'ownership.requeue'},
        {'field': 'target_ref', 'reason': claim_id},
    ]


def test_owner_can_requeue_claim_and_clear_active_handoff(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, handoff_id, revision = _request_staff_support(
        client, auth_headers, repository, key_suffix='requeue-success'
    )
    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'requeue-success-accept',
            'If-Match': str(revision),
        },
        json={},
    )
    assert accepted.status_code == 200
    requeue = client.post(
        f'/api/v1/workbench/claims/{claim_id}/requeue',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'requeue-success',
            'If-Match': str(accepted.json()['revision']),
        },
        json={'reason': 'Return this Claim to the shared queue.'},
    )
    assert requeue.status_code == 200
    assert requeue.json()['revision'] == accepted.json()['revision'] + 1
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    assert claim.assignee_id is None


def test_workbench_exposes_external_request_and_activity_event_pages(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository, key_suffix='events')

    external = client.get(
        f'/api/v1/workbench/claims/{claim_id}/external-requests',
        headers=staff_auth_headers,
    )
    events = client.get(
        f'/api/v1/workbench/claims/{claim_id}/events',
        headers=staff_auth_headers,
    )

    assert external.status_code == 200
    assert external.json()['items'] == []
    assert external.json()['status'] == 'available'
    assert events.status_code == 200
    assert events.json()['items']
    assert any(item['event_type'] == 'claim.created' for item in events.json()['items'])


def test_workbench_marks_external_requests_unavailable_when_store_fails(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_id, _ = _create_claim_with_context(
        client, auth_headers, repository, key_suffix='external-down'
    )

    def unavailable(_: str) -> list[ExternalTaskRecord]:
        raise RuntimeError('external store unavailable')

    monkeypatch.setattr(repository, 'list_external_tasks_internal', unavailable)
    response = client.get(
        f'/api/v1/workbench/claims/{claim_id}/external-requests',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'unavailable'
    assert response.json()['limitation']


def test_staff_access_projection_distinguishes_primary_and_read_only_claimants(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository, key_suffix='access')
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    owner = claim.model_copy(update={'assignee_id': 'stf_owner'})
    assert (
        claim_staff_access(repository, owner, Principal(subject='stf_owner', actor_type='staff'))
        is ClaimStaffAccess.PRIMARY
    )
    outsider = Principal(subject='stf_outsider', actor_type='staff')
    assert claim_staff_access(repository, owner, outsider) is ClaimStaffAccess.READ_ONLY
    with pytest.raises(ApiError):
        require_claim_collaborator(repository, owner, outsider)
