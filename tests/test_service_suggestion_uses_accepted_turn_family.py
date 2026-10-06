"""INV-15: same-turn accepted facts determine service eligibility after model output."""

import json
import logging
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.models import FormSource, FormStatus
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_agent_external_lifecycle import _task
from tests.test_claim_api import submit_message
from tests.test_external_service_offers import _offer_route

RECOVERY = 'vehicle_recovery_request'
MOTOR_MESSAGE = "My car was rear-ended, it's not drivable. Please arrange a tow."


def _new_claim(client: TestClient) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': 'inv15-new'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created['claim']['incident_type'] is None
    return (
        created['claim']['claim_id'],
        created['session']['session_id'],
        created['claim']['revision'],
    )


def _prompt_services(provider: V8JourneyProvider, turn: int = 0) -> list[dict[str, Any]]:
    request = provider.gateway.requests[turn]
    message = next(item for item in request.messages if item.role.value == 'user')
    assert message.content is not None
    # The planner omits an empty section, as it does when the lifecycle lookup fails.
    return cast(
        list[dict[str, Any]],
        json.loads(message.content)['claim.current'].get('eligible_services', []),
    )


@pytest.mark.parametrize(
    ('message', 'family', 'quotation', 'accepted'),
    [
        (MOTOR_MESSAGE, 'motor', 'My car was rear-ended', True),
        ('My home ceiling is leaking. Please arrange a tow.', 'home', 'My home ceiling', False),
        (MOTOR_MESSAGE, 'motor', 'The claimant explicitly selected motor insurance', False),
    ],
)
def test_first_turn_toolbox_is_visible_but_only_accepted_family_unlocks_service(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
    message: str,
    family: str,
    quotation: str,
    accepted: bool,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.services.turn_proposal_validation')
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[fact('claim.product_family', family, quotation)],
                services=[RECOVERY],
                requested={RECOVERY: 'Please arrange a tow'},
            )
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    claim_id, session_id, revision = _new_claim(client)
    response = submit_message(
        client, CLAIMANT, claim_id, session_id, revision=revision, key='inv15-turn', text=message
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['agent_message'] is not None, response.text
    assert result['recovery'] is None
    assert len(provider.gateway.requests) == 1
    services = _prompt_services(provider)
    assert 0 < len(services) <= 8
    assert RECOVERY in {item['service_identity'] for item in services}
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    saved = claim.form['claim.product_family']
    supported = quotation in message
    assert saved.status is (FormStatus.CONFIRMED if supported else FormStatus.PROPOSED)
    assert saved.source is (FormSource.CLAIMANT if supported else FormSource.INFERENCE)
    actions = result['agent_message']['message_actions']
    if accepted:
        assert claim.incident_type == 'motor'
        assert len(actions) == 1
        assert actions[0]['service_identity'] == RECOVERY
        assert actions[0]['lifecycle_status'] == 'consent_required'
    else:
        assert actions == []
        assert any(
            getattr(record, 'rejection', {}).get('reason') == 'service_not_eligible'
            for record in caplog.records
        )


def test_granted_generic_offer_does_not_become_retry_when_task_storage_is_unavailable(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact('claim.product_family', 'motor', 'My car'),
                    fact('vehicle.drivable', False, 'not drivable'),
                    fact('incident.location', 'Queen Street', 'Queen Street'),
                ],
                services=[RECOVERY],
                requested={RECOVERY: 'Please arrange a tow'},
            ),
            envelope(
                fields=[fact('vehicle.damage_description', 'Dented bumper', 'bumper is dented')]
            ),
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    claim_id, session_id, revision = _new_claim(client)
    first = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='inv15-before-outage',
        client_message_id='inv15-before-outage',
        text='My car is not drivable on Queen Street. Please arrange a tow.',
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    offer = first_body['agent_message']['message_actions'][0]
    granted = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'inv15-grant',
            'If-Match': str(first_body['current_claim_revision']),
        },
        json={'decision': 'grant'},
    )
    assert granted.status_code == 201, granted.text
    read_tasks = repository.list_external_tasks_internal
    tasks_before = read_tasks(claim_id)
    assert len(tasks_before) == 1
    assert tasks_before[0].service_identity == RECOVERY
    requests_before = repository.list_external_task_requests_internal(claim_id)
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    assert claim.external_service_consents[-1].status.value == 'granted'

    def unavailable(_claim_id: str) -> list[Any]:
        raise RuntimeError('synthetic persistence outage after granted request')

    monkeypatch.setattr(repository, 'list_external_tasks_internal', unavailable)
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=claim.revision,
        key='inv15-during-outage',
        client_message_id='inv15-during-outage',
        text='The bumper is dented.',
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['claimant_message']['content']['text'] == 'The bumper is dented.'
    assert result['agent_message'] is not None and result['recovery'] is None
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    assert claim.form['vehicle.damage_description'].value == 'Dented bumper'
    history = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages', headers=CLAIMANT
    )
    assert history.status_code == 200, history.text
    old_message = next(
        item
        for item in history.json()['items']
        if item['message_id'] == first_body['agent_message']['message_id']
    )
    assert old_message['message_actions'] == []
    assert result['agent_message']['message_actions'] == []
    assert read_tasks(claim_id) == tasks_before
    assert repository.list_external_task_requests_internal(claim_id) == requests_before
    assert any(
        getattr(record, 'component', None) == 'message_service_projection'
        for record in caplog.records
    )


def test_existing_open_handoff_silences_new_messages_without_a_second_model_call(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """A new claimant message while a handoff is open is recorded, never processed.

    An earlier design let the toolbox stay visible but suppressed same-turn
    service proposals while a handoff was open; per the full-silence
    contract, the model is never invoked for a new message during an open
    handoff at all, so there is no second turn to inspect.
    """

    provider = V8JourneyProvider([envelope()])
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    claim_id, session_id, revision = _new_claim(client)
    first = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='inv15-support',
        client_message_id='inv15-support',
        text='I want to speak to a person.',
    )
    assert first.status_code == 200, first.text
    assert first.json()['handoff'] is not None
    assert len(repository.list_handoffs(claim_id, 'cus_8f41a2c90d7e463b')) == 1
    second = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=first.json()['current_claim_revision'],
        key='inv15-followup',
        client_message_id='inv15-followup',
        text=MOTOR_MESSAGE,
    )
    assert second.status_code == 200, second.text
    assert second.json()['agent_message'] is None
    assert second.json()['decision'] is None
    assert len(provider.gateway.requests) == 1
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None and claim.incident_type is None
    assert len(repository.list_handoffs(claim_id, 'cus_8f41a2c90d7e463b')) == 1


def test_conflicting_family_assertion_cannot_unlock_services_for_the_disputed_family(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.services.turn_proposal_validation')
    provider = V8JourneyProvider(
        [
            envelope(fields=[fact('claim.product_family', 'home', 'My home ceiling is leaking')]),
            envelope(
                fields=[fact('claim.product_family', 'motor', 'My car was rear-ended')],
                services=[RECOVERY],
                requested={RECOVERY: 'Please arrange a tow'},
            ),
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    claim_id, session_id, revision = _new_claim(client)
    first = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='inv15-home',
        client_message_id='inv15-home',
        text='My home ceiling is leaking.',
    )
    assert first.status_code == 200, first.text
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    assert claim.incident_type == 'home'
    assert claim.form['claim.product_family'].status is FormStatus.CONFIRMED
    second = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=first.json()['current_claim_revision'],
        key='inv15-conflict',
        client_message_id='inv15-conflict',
        text=MOTOR_MESSAGE,
    )
    assert second.status_code == 200, second.text
    assert second.json()['agent_message'] is not None
    assert second.json()['agent_message']['message_actions'] == []
    assert RECOVERY in {item['service_identity'] for item in _prompt_services(provider, 1)}
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    assert claim.incident_type == 'home'
    assert claim.form['claim.product_family'].status is FormStatus.DISPUTED
    assert any(
        getattr(record, 'rejection', {}).get('reason') == 'service_not_eligible'
        for record in caplog.records
    )


@pytest.mark.parametrize('task_state', ['unavailable', 'already_active'])
def test_external_task_lookup_cannot_break_chat_or_duplicate_existing_work(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    task_state: str,
) -> None:
    caplog.set_level(logging.INFO)
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[fact('claim.product_family', 'motor', 'My car was rear-ended')],
                services=[RECOVERY],
                requested={RECOVERY: 'Please arrange a tow'},
            )
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    claim_id, session_id, revision = _new_claim(client)
    if task_state == 'unavailable':

        def unavailable(_claim_id: str) -> list[Any]:
            raise RuntimeError('synthetic persistence outage')

        monkeypatch.setattr(repository, 'list_external_tasks_internal', unavailable)
    else:
        task = _task(service_identity=RECOVERY).model_copy(update={'claim_id': claim_id})
        repository.save_external_task(task, 'cus_8f41a2c90d7e463b')
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        revision=revision,
        key='inv15-task-state',
        text=MOTOR_MESSAGE,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['agent_message'] is not None
    assert result['agent_message']['content']['text']
    assert result['recovery'] is None
    assert result['agent_message']['message_actions'] == []
    assert len(provider.gateway.requests) == 1
    assert RECOVERY not in {item['service_identity'] for item in _prompt_services(provider)}
    claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None and claim.incident_type == 'motor'
    assert claim.form['claim.product_family'].status is FormStatus.CONFIRMED
    if task_state == 'unavailable':
        components = {
            getattr(record, 'component', None)
            for record in caplog.records
            if record.message == 'external_lifecycle_context_unavailable'
        }
        assert {'model_service_toolbox', 'turn_service_eligibility'} <= components
    else:
        tasks = repository.list_external_tasks_internal(claim_id)
        assert len(tasks) == 1 and tasks[0].task_id == task.task_id
        assert any(
            getattr(record, 'rejection', {}).get('reason') == 'service_not_eligible'
            for record in caplog.records
        )
