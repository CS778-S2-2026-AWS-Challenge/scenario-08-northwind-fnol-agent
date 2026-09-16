from typing import Any

from fastapi.testclient import TestClient

from backend.domain.models import FormStatus
from backend.repositories.fixture import FixtureRepository

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
ASSESSMENT_REQUEST = (
    "My car was rear-ended on Symonds Street. It's 8 o'clock in the morning now and "
    'the traffic is very heavy. Could you help me get a damage assessment for the repairs?'
)


def _start_motor_claim(client: TestClient, key: str) -> tuple[str, str]:
    response = client.post(
        '/api/v1/claims',
        headers={**AUTH, 'Idempotency-Key': f'claim-{key}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    body = response.json()
    return str(body['claim']['claim_id']), str(body['session']['session_id'])


def _send(
    client: TestClient,
    claim_id: str,
    session_id: str,
    text: str,
    key: str,
    revision: int = 1,
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **AUTH,
            'Idempotency-Key': f'message-{key}',
            'If-Match': str(revision),
        },
        json={
            'client_message_id': f'client-{key}',
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_assessment_request_keeps_safety_question_and_binds_offer_to_message(
    client: TestClient,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'assessment')

    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, 'assessment')

    assert 'is anyone injured' in turn['agent_message']['content']['text'].lower()
    assert turn['primary_action']['execution_boundary'] == 'conversation'
    assert turn['primary_action']['action_code'] != 'external.submit_request'
    actions = turn['agent_message']['message_actions']
    assert len(actions) == 1
    assert actions[0]['service_identity'] == 'vehicle_damage_assessment_routing'
    assert actions[0]['status'] == 'consent_required'
    assert actions[0]['agent_message_id'] == turn['agent_message']['message_id']

    history = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers=AUTH,
    )
    assert history.status_code == 200
    restored = next(
        item
        for item in history.json()['items']
        if item['message_id'] == turn['agent_message']['message_id']
    )
    assert restored['message_actions'] == actions


def test_offer_decision_is_idempotent_and_withdrawable_before_dispatch(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'decision')
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, 'decision')
    offer = turn['agent_message']['message_actions'][0]
    route = f"/api/v1/claims/{claim_id}/external-service-offers/{offer['offer_id']}/decision"
    headers = {
        **AUTH,
        'Idempotency-Key': 'grant-decision',
        'If-Match': str(turn['claim_revision']),
    }

    granted = client.post(route, headers=headers, json={'decision': 'grant'})
    replay = client.post(route, headers=headers, json={'decision': 'grant'})

    assert granted.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == granted.json()
    assert granted.json()['action']['status'] == 'pending_input'
    assert granted.json()['action']['can_withdraw'] is True
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_service_consents[-1].offer_ref == offer['offer_id']
    assert stored.external_service_consents[-1].disclosure_fingerprint == offer[
        'disclosure_fingerprint'
    ]

    withdrawn = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'withdraw-decision',
            'If-Match': str(granted.json()['revision']),
        },
        json={'decision': 'withdraw'},
    )
    assert withdrawn.status_code == 201
    assert withdrawn.json()['action']['status'] == 'consent_withdrawn'
    assert repository.list_external_tasks_internal(claim_id) == []


def test_manual_contact_consent_never_creates_an_external_task(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'manual')
    turn = _send(
        client,
        claim_id,
        session_id,
        'Can you help me contact Police 105 to report the crash?',
        'manual',
    )
    offer = next(
        action
        for action in turn['agent_message']['message_actions']
        if action['service_identity'] == 'police_105_reporting_guidance'
    )

    decided = client.post(
        f"/api/v1/claims/{claim_id}/external-service-offers/{offer['offer_id']}/decision",
        headers={
            **AUTH,
            'Idempotency-Key': 'grant-manual',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert decided.status_code == 201
    assert decided.json()['action']['status'] == 'manual_available'
    assert decided.json()['action']['official_phone'] == '105'
    assert repository.list_external_tasks_internal(claim_id) == []


def test_ready_assessment_offer_dispatches_once_from_the_same_consent(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'ready-assessment')
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, 'ready-assessment')
    offer = turn['agent_message']['message_actions'][0]
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    location = stored.form['incident.location'].model_copy(
        update={'status': FormStatus.CONFIRMED}
    )
    repository._claims[claim_id] = stored.model_copy(
        update={'form': {**stored.form, 'incident.location': location}}
    )

    route = f"/api/v1/claims/{claim_id}/external-service-offers/{offer['offer_id']}/decision"
    granted = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'grant-ready-assessment',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert granted.status_code == 201
    assert granted.json()['action']['status'] in {'assigned', 'queued'}
    requests = repository.list_external_task_requests_internal(claim_id)
    assert len(requests) == 1
    assert requests[0].requested_action == 'vehicle_damage_assessment'

    replay = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'grant-ready-assessment',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )
    assert replay.status_code == 200
    assert len(repository.list_external_task_requests_internal(claim_id)) == 1


def test_ready_registered_task_service_uses_the_shared_dispatcher(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'repair-booking')
    turn = _send(
        client,
        claim_id,
        session_id,
        (
            'My car was rear-ended on Symonds Street and the rear bumper is damaged. '
            'Can you book a repair for me?'
        ),
        'repair-booking',
    )
    offer = next(
        action
        for action in turn['agent_message']['message_actions']
        if action['service_identity'] == 'vehicle_repairer_booking'
    )
    assert offer['requested_action'] == 'book_vehicle_repair'
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    confirmed_form = {
        **stored.form,
        'incident.location': stored.form['incident.location'].model_copy(
            update={'status': FormStatus.CONFIRMED}
        ),
        'vehicle.damage_description': stored.form['vehicle.damage_description'].model_copy(
            update={'status': FormStatus.CONFIRMED}
        ),
    }
    repository._claims[claim_id] = stored.model_copy(update={'form': confirmed_form})

    decided = client.post(
        f"/api/v1/claims/{claim_id}/external-service-offers/{offer['offer_id']}/decision",
        headers={
            **AUTH,
            'Idempotency-Key': 'grant-repair-booking',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert decided.status_code == 201
    assert decided.json()['action']['status'] == 'queued'
    tasks = repository.list_external_tasks_internal(claim_id)
    requests = repository.list_external_task_requests_internal(claim_id)
    assert len(tasks) == len(requests) == 1
    assert tasks[0].service_identity == 'vehicle_repairer_booking'
    assert tasks[0].requested_action == 'book_vehicle_repair'
    assert requests[0].disclosed_fields == [
        'vehicle.damage_description',
        'incident.location',
    ]
