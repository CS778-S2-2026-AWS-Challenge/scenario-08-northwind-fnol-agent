import json
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from tests.issue_928_support import _session_headers, prepare_claim_submission

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding='utf-8')))


def _complete_motor_requirements(
    client: TestClient,
    auth_headers: dict[str, str],
    claim_id: str,
    revision: int,
    *,
    key: str,
) -> dict[str, Any]:
    response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={
            **auth_headers,
            'Idempotency-Key': key,
            'If-Match': str(revision),
        },
        json={'updates': [{'field_code': 'vehicle.drivable', 'value': True}]},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_at01_natural_intake_confirms_then_creates_mock_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'at01-working-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = created.json()
    claim = working['claim']
    claim_id = claim['claim_id']
    session_id = working['session']['session_id']

    before_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-create-too-early',
            'If-Match': str(claim['revision']),
        },
    )
    assert before_confirmation.status_code == 409
    assert before_confirmation.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-description-turn',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'at01-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200
    turn_body = turn.json()
    proposed = {item['field_code'] for item in turn_body['form_changes']}
    assert proposed == {*journey['expected_proposed_fields'], 'incident.type'}
    assert turn_body['decision']['action'] == 'CONFIRM'

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-confirm-all',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': sorted(proposed)},
    )
    assert confirmed.status_code == 200
    confirmed_body = _complete_motor_requirements(
        client,
        auth_headers,
        claim_id,
        confirmed.json()['revision'],
        key='at01-complete-vp-requirements',
    )
    assert confirmed_body['customer_next_step']['status'] == 'ready_to_create'
    ready_claim = repository.get_claim(claim_id, 'cus_demo')
    assert ready_claim is not None
    assert ready_claim.claim_state.workflow_state.value == 'ready_for_next'

    submission_revision = prepare_claim_submission(
        client,
        auth_headers,
        claim_id,
        confirmed_body['revision'],
        key='at01-submit',
    )
    creation_headers = {
        **auth_headers,
        'Idempotency-Key': 'at01-controlled-creation',
        'If-Match': str(submission_revision),
    }
    created_external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    assert created_external.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == created_external.json()

    repository._idempotency.pop(
        (
            'cus_demo',
            f'/api/v1/claims/{claim_id}/creation',
            'at01-controlled-creation',
        )
    )
    recovered = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers=creation_headers,
    )
    assert recovered.status_code == 201
    assert recovered.json() == created_external.json()

    conflicting_reuse = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-controlled-creation',
            'If-Match': str(submission_revision + 1),
        },
    )
    assert conflicting_reuse.status_code == 409
    assert conflicting_reuse.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    duplicate_operation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'at01-create-again',
            'If-Match': str(created_external.json()['revision']),
        },
    )
    assert duplicate_operation.status_code == 409
    assert duplicate_operation.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    result = created_external.json()
    assert result['decision']['action'] == 'CREATE_CLAIM'
    assert result['decision']['reason_codes'] == ['CLAIM_CREATION_AUTHORISED']
    assert result['external_claim']['creation_status'] == journey['expected_creation_status']
    assert result['external_claim']['route'] == journey['expected_route']
    assert result['external_claim']['source'] == journey['expected_source']
    assert result['external_claim']['claim_number']
    assert result['external_claim']['next_step']
    assert result['external_claim']['expected_by']
    assert result['customer_next_step']['status'] == 'claim_created'
    creation_decision = repository.get_agent_decision(
        claim_id,
        result['decision']['decision_id'],
        'cus_demo',
    )
    assert creation_decision is not None
    assert creation_decision.action_code == 'claim.create'
    assert creation_decision.required_tools == [{'tool': 'claims_service.create_claim'}]
    creation_idempotency = repository.find_idempotency(
        'cus_demo',
        f'/api/v1/claims/{claim_id}/creation',
        'at01-controlled-creation',
    )
    assert creation_idempotency is not None
    assert creation_idempotency.action_code == 'claim.create'
    assert creation_idempotency.target_ref == claim_id

    claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_view.status_code == 200
    projection = claimant_view.json()
    assert projection['workflow_state'] == 'created'
    assert projection['external_claim'] == result['external_claim']


def test_assessor_offer_before_payout_does_not_block_step4_or_creation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'issue928-ordering-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = cast(dict[str, Any], created.json())
    claim = cast(dict[str, Any], working['claim'])
    claim_id = cast(str, claim['claim_id'])
    session_id = cast(str, working['session']['session_id'])

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue928-ordering-message',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'issue928-ordering-message',
            'content': {
                'type': 'text',
                'text': (
                    f"{journey['input']} "
                    'Could you help me get a damage assessment for the repairs?'
                ),
            },
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200, turn.text
    turn_body = cast(dict[str, Any], turn.json())
    offer = next(
        action
        for action in turn_body['agent_message']['message_actions']
        if action['service_identity'] == 'vehicle_damage_assessment_routing'
    )
    proposed = sorted(item['field_code'] for item in turn_body['form_changes'])

    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue928-ordering-confirm',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': proposed},
    )
    assert confirmed.status_code == 200, confirmed.text
    ready = _complete_motor_requirements(
        client,
        auth_headers,
        claim_id,
        confirmed.json()['revision'],
        key='issue928-ordering-ready',
    )
    assert ready['customer_next_step']['status'] == 'ready_to_create'

    offer_id = cast(str, offer['offer_id'])
    granted = client.post(
        f'/api/v1/claims/{claim_id}/external-service-offers/{offer_id}/decision',
        headers={
            **auth_headers,
            'Idempotency-Key': 'issue928-ordering-offer',
            'If-Match': str(ready['revision']),
        },
        json={'decision': 'grant'},
    )
    assert granted.status_code == 201, granted.text
    assert granted.json()['action']['status'] in {'assigned', 'queued'}

    projected = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert projected.status_code == 200, projected.text
    projected_body = cast(dict[str, Any], projected.json())
    assert projected_body['primary_action']['action_code'] == 'claimant.review_payout_contact'

    session_headers = _session_headers(client, auth_headers)
    destination = client.post(
        '/api/v1/account/payment-destinations',
        headers={**session_headers, 'Idempotency-Key': 'issue928-ordering-payment'},
        json={
            'account_type': 'cheque',
            'account_number': '12-3456-7654321-00',
            'bank_name': 'Northwind Test Bank',
            'account_holder_name': 'Claimant One',
        },
    )
    assert destination.status_code == 201, destination.text

    payout = client.post(
        f'/api/v1/claims/{claim_id}/payout-contact-selections',
        headers={
            **session_headers,
            'Idempotency-Key': 'issue928-ordering-payout',
            'If-Match': str(projected_body['revision']),
        },
        json={
            'payment_destination_id': destination.json()['payment_destination_id'],
            'contact_preference': 'in_app',
        },
    )
    assert payout.status_code == 201, payout.text
    payout_body = cast(dict[str, Any], payout.json())
    assert payout_body['customer_next_step']['status'] == 'agreement_required'
    assert payout_body['primary_action']['action_code'] == 'claimant.review_agreement'

    detail = client.get(f'/api/v1/claims/{claim_id}', headers=session_headers)
    assert detail.status_code == 200, detail.text
    detail_body = cast(dict[str, Any], detail.json())
    agreement = cast(dict[str, Any], detail_body['submission_agreement'])
    confirmations = {
        cast(str, item['key']): True
        for item in cast(list[dict[str, Any]], agreement['confirmations'])
        if item['required']
    }

    accepted = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **session_headers,
            'Idempotency-Key': 'issue928-ordering-agreement',
            'If-Match': str(detail_body['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': confirmations,
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = cast(dict[str, Any], accepted.json())
    assert accepted_body['primary_action']['action_code'] == 'claimant.create_claim'

    external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **session_headers,
            'Idempotency-Key': 'issue928-ordering-create',
            'If-Match': str(accepted_body['revision']),
        },
    )
    assert external.status_code == 201, external.text
    external_body = cast(dict[str, Any], external.json())
    assert external_body['external_claim']['creation_status'] == 'created'
    assert external_body['external_claim']['claim_number']
    assert external_body['customer_next_step']['status'] == 'claim_created'


def test_clear_motor_intake_classifies_missing_incident_type_before_creation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'unclassified-working-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201
    working = created.json()
    claim = working['claim']

    turn = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions/{working["session"]["session_id"]}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-description-turn',
            'If-Match': str(claim['revision']),
        },
        json={
            'client_message_id': 'unclassified-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200
    turn_body = turn.json()
    proposed = {item['field_code'] for item in turn_body['form_changes']}
    assert proposed == {
        *journey['expected_proposed_fields'],
        'claim.product_family',
        'incident.type',
    }

    confirmed = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-confirm-all',
            'If-Match': str(turn_body['claim_revision']),
        },
        json={'field_codes': sorted(proposed)},
    )
    assert confirmed.status_code == 200
    confirmed_body = _complete_motor_requirements(
        client,
        auth_headers,
        claim['claim_id'],
        confirmed.json()['revision'],
        key='unclassified-complete-vp-requirements',
    )
    assert confirmed_body['customer_next_step']['status'] == 'ready_to_create'

    claimant_view = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=auth_headers)
    assert claimant_view.status_code == 200
    assert claimant_view.json()['incident_type'] == 'motor'

    submission_revision = prepare_claim_submission(
        client,
        auth_headers,
        claim['claim_id'],
        confirmed_body['revision'],
        key='unclassified-submit',
    )
    created_external = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'unclassified-controlled-creation',
            'If-Match': str(submission_revision),
        },
    )
    assert created_external.status_code == 201


def test_claim_creation_rejects_a_stale_working_claim_revision(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'stale-creation-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()

    response = client.post(
        f'/api/v1/claims/{created["claim"]["claim_id"]}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'stale-creation-attempt',
            'If-Match': '999',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert response.json()['error']['current_revision'] == 1


def test_pending_later_evidence_does_not_block_controlled_claim_creation(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    journey = _fixture()
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'pending-creation-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-description',
            'If-Match': '1',
        },
        json={
            'client_message_id': 'pending-creation-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    ).json()
    confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-confirm',
            'If-Match': str(turn['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    ).json()
    confirmation = _complete_motor_requirements(
        client,
        auth_headers,
        claim_id,
        confirmation['revision'],
        key='pending-complete-vp-requirements',
    )
    evidence_turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-creation-evidence',
            'If-Match': str(confirmation['revision']),
        },
        json={
            'client_message_id': 'pending-creation-evidence',
            'content': {
                'type': 'text',
                'text': 'Police said the police report will be ready next week.',
            },
            'evidence_refs': [],
        },
    ).json()

    submission_revision = prepare_claim_submission(
        client,
        auth_headers,
        claim_id,
        evidence_turn['claim_revision'],
        key='pending-submit',
    )
    response = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'pending-controlled-creation',
            'If-Match': str(submission_revision),
        },
    )

    assert response.status_code == 201
    assert response.json()['external_claim']['creation_status'] == 'created'
    evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth_headers).json()[
        'items'
    ]
    assert evidence[0]['status'] == 'pending'
