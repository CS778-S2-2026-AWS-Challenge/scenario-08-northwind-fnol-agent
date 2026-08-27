from datetime import timedelta

from fastapi.testclient import TestClient

from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    CustomerNextStep,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    FraudSignal,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    WorkflowState,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.support import now_utc


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
    assert detail['retrievals'] == []
    assert detail['signals'][0]['code'] == 'HISTORY_INCONSISTENCY_REVIEW'
    assert any(message['message_id'] == 'msg_internal_note' for message in detail['messages'])
    assert detail['handoffs'] == []
    assert detail['staff_actions'] == []
    assert detail['customer_updates'] == []


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
    assert item['customer_reference'] == 'cus_demo'
    assert item['queue'] == 'professional_review'
    assert item['priority'] == 'standard'
    assert item['next_action'] == 'CONFIRM'
    assert item['route'] == 'professional_review'
    assert item['evidence_state'] == 'pending_generation'
    assert item['next_action_summary']
    assert item['responsible_party'] == 'claimant'
    assert item['evidence_summary']['pending'] == 1


def test_workbench_claim_list_rejects_claimant_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get('/api/v1/workbench/claims', headers=auth_headers)

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'


def test_created_claim_route_does_not_override_workbench_queue(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, _ = _create_claim_with_context(client, auth_headers, repository)
    stored_claim = repository.get_claim_internal(claim_id)
    assert stored_claim is not None
    repository.save_claim(
        stored_claim.model_copy(
            update={
                'route': 'standard_motor_intake',
                'claim_state': stored_claim.claim_state.model_copy(
                    update={'workflow_state': WorkflowState.CREATED}
                ),
            }
        ),
        expected_revision=stored_claim.revision,
    )

    response = client.get(
        '/api/v1/workbench/claims?view=created_routed',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    item = next(item for item in response.json()['items'] if item['claim_id'] == claim_id)
    assert item['queue'] == 'created_routed'


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
    staff_handoff = staff_response.json()['handoffs'][0]
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
            responsible_party=ResponsibleParty.NORTHWIND,
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
    assert detail['route'] == creation['route']
    assert detail['claim_state']['workflow_state'] == 'created'
    assert detail['external_claim'] == creation
    assert detail['external_claim']['creation_status'] == 'created'
    assert detail['external_claim']['next_step'] == 'Claims intake review'
    assert detail['external_claim']['expected_by'] is not None
    assert detail['external_service_consents'] == [consent.model_dump(mode='json')]
    assert detail['assessor_routing'] == routing
    assert detail['customer_next_step']['status'] == 'assessor_assigned'
    assert detail['customer_next_step']['expected_by'] == routing['expected_by']
    assert {decision['decision_id'] for decision in detail['decisions']} == {
        create_decision.decision_id,
        route_decision.decision_id,
    }
    assert {decision['trigger_message_id'] for decision in detail['decisions']} == {
        'msg_workbench_create',
        'msg_workbench_assessor',
    }
    assert detail['messages'] == []
    queue_response = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    queue_item = next(
        item for item in queue_response.json()['items'] if item['claim_id'] == claim_id
    )
    assert queue_item['assignee_id'] == 'stf_demo'
