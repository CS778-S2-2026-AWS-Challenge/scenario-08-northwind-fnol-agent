from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    ContentsItem,
    ContentsLossType,
    ContentsOwnership,
    FormSource,
    FormStatus,
    NeededFor,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict, RevisionConflict
from backend.services.external_capability_dispatcher import ExternalCapabilityDispatcher
from backend.services.external_service_offers import (
    _source_value,
    build_offer_metadata,
    detected_service_intents,
    message_external_actions,
)

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
    return cast(dict[str, Any], response.json())


def _offer_route(claim_id: str, offer_id: str) -> str:
    return f'/api/v1/claims/{claim_id}/external-service-offers/{offer_id}/decision'


def _tamper_offer(
    repository: FixtureRepository,
    claim_id: str,
    offer_id: str,
    update: dict[str, Any],
) -> None:
    for turn_id, records in repository._runtime_turns.items():
        if records.turn_plan.claim_id != claim_id:
            continue
        items = []
        for item in records.work_items:
            offer = item.external_offer
            if offer is not None and offer.offer_id == offer_id:
                item = item.model_copy(update={'external_offer': offer.model_copy(update=update)})
            items.append(item)
        repository._runtime_turns[turn_id] = records.model_copy(update={'work_items': items})


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


def test_detected_service_intents_enforces_registry_family_deduplication_and_limit() -> None:
    intents = detected_service_intents(
        None,
        [
            {'service_identity': 'unknown_service', 'requested_action': 'submit_request'},
            {
                'service_identity': 'home_emergency_repair_request',
                'requested_action': 'submit_request',
            },
            {'service_identity': 'vehicle_recovery_request', 'requested_action': 'inspect'},
            {'service_identity': 'vehicle_recovery_request'},
            {'service_identity': 'vehicle_recovery_request'},
            {'service_identity': 'vehicle_repairer_booking'},
            {'service_identity': 'repairer_information_or_link'},
            {'service_identity': 'police_105_reporting_guidance'},
        ],
        product_family='motor',
    )

    assert [item['service_identity'] for item in intents] == [
        'vehicle_recovery_request',
        'vehicle_repairer_booking',
        'repairer_information_or_link',
    ]


def test_contents_disclosure_includes_only_confirmed_items(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, _session_id = _start_motor_claim(client, 'contents-disclosure')
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    timestamp = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)

    def item(item_id: str, status: FormStatus) -> ContentsItem:
        return ContentsItem(
            item_id=item_id,
            description=f'Laptop {item_id}',
            category='electronics',
            quantity=1,
            loss_type=ContentsLossType.DAMAGED,
            ownership=ContentsOwnership.OWNED,
            source=FormSource.CLAIMANT,
            source_refs=['msg_contents'],
            status=status,
            needed_for=NeededFor.CURRENT_ACTION,
            confidence=1.0,
            updated_at=timestamp,
            updated_by=ActorReference(
                actor_type=ActorType.CLAIMANT,
                actor_id='cus_demo',
            ),
        )

    confirmed = item('itm_confirmed', FormStatus.CONFIRMED)
    proposed = item('itm_proposed', FormStatus.PROPOSED)
    with_items = claim.model_copy(update={'contents_items': [confirmed, proposed]})

    assert _source_value(with_items, 'contents.items') == [
        {
            'item_id': 'itm_confirmed',
            'description': 'Laptop itm_confirmed',
            'category': 'electronics',
            'quantity': 1,
            'loss_type': 'damaged',
        }
    ]
    assert (
        _source_value(claim.model_copy(update={'contents_items': [proposed]}), 'contents.items')
        is None
    )
    assert _source_value(claim, 'unregistered.field') is None


def test_offer_metadata_rejects_capability_from_another_product_family(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, _session_id = _start_motor_claim(client, 'wrong-family')
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None

    with pytest.raises(ValueError, match='unavailable for this Claim family'):
        build_offer_metadata(
            claim=claim,
            agent_message_id='msg_agent',
            trigger_message_id='msg_claimant',
            intent={
                'service_identity': 'home_emergency_repair_request',
                'requested_action': 'submit_request',
            },
        )


def test_offer_decision_rejects_missing_stale_invalid_and_corrupt_replays(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    missing = client.post(
        _offer_route('clm_missing', 'off_missing'),
        headers={**AUTH, 'Idempotency-Key': 'missing-claim', 'If-Match': '1'},
        json={'decision': 'grant'},
    )
    assert missing.status_code == 404

    claim_id, session_id = _start_motor_claim(client, 'decision-guards')
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, 'decision-guards')
    offer = turn['agent_message']['message_actions'][0]
    route = _offer_route(claim_id, offer['offer_id'])

    stale = client.post(
        route,
        headers={**AUTH, 'Idempotency-Key': 'stale-offer', 'If-Match': '999'},
        json={'decision': 'grant'},
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'

    unknown = client.post(
        _offer_route(claim_id, 'off_missing'),
        headers={
            **AUTH,
            'Idempotency-Key': 'missing-offer',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )
    assert unknown.status_code == 404

    invalid_withdrawal = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'invalid-withdrawal',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'withdraw'},
    )
    assert invalid_withdrawal.status_code == 409

    declined = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'decline-offer',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'decline'},
    )
    assert declined.status_code == 201
    assert declined.json()['action']['status'] == 'consent_declined'

    idempotency_lookup = ('cus_demo', route, 'decline-offer')
    saved = repository._idempotency[idempotency_lookup]
    repository._idempotency[idempotency_lookup] = replace(saved, response_payload=None)
    corrupt_replay = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'decline-offer',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'decline'},
    )
    assert corrupt_replay.status_code == 500

    conflicting_replay = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'decline-offer',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    repeated_decision = client.post(
        route,
        headers={
            **AUTH,
            'Idempotency-Key': 'repeat-offer',
            'If-Match': str(declined.json()['revision']),
        },
        json={'decision': 'grant'},
    )
    assert repeated_decision.status_code == 409
    assert repeated_decision.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


@pytest.mark.parametrize(
    ('update', 'expected_message'),
    [
        ({'registry_version': 'external-service-lifecycle.v0'}, 'offer has changed'),
        ({'disclosure_fingerprint': 'invalid-fingerprint'}, 'disclosure is no longer valid'),
    ],
)
def test_offer_decision_rejects_persisted_scope_drift(
    client: TestClient,
    repository: FixtureRepository,
    update: dict[str, Any],
    expected_message: str,
) -> None:
    claim_id, session_id = _start_motor_claim(client, expected_message)
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, expected_message)
    offer = turn['agent_message']['message_actions'][0]
    _tamper_offer(repository, claim_id, offer['offer_id'], update)

    response = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **AUTH,
            'Idempotency-Key': f'drift-{expected_message}',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert response.status_code == 409
    assert expected_message in response.json()['error']['message'].lower()


@pytest.mark.parametrize(
    ('conflict', 'expected_code'),
    [
        (RevisionConflict(41), 'REVISION_CONFLICT'),
        (IdempotencyConflict('offer-write'), 'IDEMPOTENCY_CONFLICT'),
    ],
)
def test_offer_decision_maps_atomic_persistence_conflicts(
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    conflict: Exception,
    expected_code: str,
) -> None:
    claim_id, session_id = _start_motor_claim(client, expected_code)
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, expected_code)
    offer = turn['agent_message']['message_actions'][0]

    def fail_save(*args: object, **kwargs: object) -> None:
        raise conflict

    monkeypatch.setattr(repository, 'save_claim_mutation_with_audit', fail_save)
    response = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **AUTH,
            'Idempotency-Key': f'conflict-{expected_code}',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == expected_code


def test_offer_decision_is_idempotent_and_withdrawable_before_dispatch(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'decision')
    turn = _send(client, claim_id, session_id, ASSESSMENT_REQUEST, 'decision')
    offer = turn['agent_message']['message_actions'][0]
    route = f'/api/v1/claims/{claim_id}/external-service-offers/{offer["offer_id"]}/decision'
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
    assert (
        stored.external_service_consents[-1].disclosure_fingerprint
        == offer['disclosure_fingerprint']
    )

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
        f'/api/v1/claims/{claim_id}/external-service-offers/{offer["offer_id"]}/decision',
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
    location = stored.form['incident.location'].model_copy(update={'status': FormStatus.CONFIRMED})
    repository._claims[claim_id] = stored.model_copy(
        update={'form': {**stored.form, 'incident.location': location}}
    )

    route = f'/api/v1/claims/{claim_id}/external-service-offers/{offer["offer_id"]}/decision'
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_time = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
    monkeypatch.setattr(
        'backend.services.external_service_offers.now_utc',
        lambda: fixed_time,
    )
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
        f'/api/v1/claims/{claim_id}/external-service-offers/{offer["offer_id"]}/decision',
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
    assert tasks[0].updated_at == fixed_time + timedelta(microseconds=1)
    assert requests[0].disclosed_fields == [
        'vehicle.damage_description',
        'incident.location',
    ]

    withdrawal = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **AUTH,
            'Idempotency-Key': 'withdraw-sent-repair-booking',
            'If-Match': str(decided.json()['revision']),
        },
        json={'decision': 'withdraw'},
    )
    assert withdrawal.status_code == 409
    assert withdrawal.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


@pytest.mark.parametrize(
    ('status', 'failure_code', 'delivery', 'expected_status'),
    [
        (
            ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskDelivery.NOT_SUBMITTED,
            'retryable_failure',
        ),
        (
            ExternalTaskOperationStatus.TERMINAL_FAILURE,
            ExternalTaskFailureCode.ACCESS_DENIED,
            ExternalTaskDelivery.NOT_SUBMITTED,
            'terminal_failure',
        ),
        (
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.SUBMITTED,
            'awaiting_reconciliation',
        ),
    ],
)
def test_registered_task_failure_class_is_projected_for_the_claimant(
    client: TestClient,
    repository: FixtureRepository,
    status: ExternalTaskOperationStatus,
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
    expected_status: str,
) -> None:
    claim_id, session_id = _start_motor_claim(client, expected_status)
    turn = _send(
        client,
        claim_id,
        session_id,
        (
            'My car was rear-ended on Symonds Street and the rear bumper is damaged. '
            'Can you book a repair for me?'
        ),
        expected_status,
    )
    offer = next(
        action
        for action in turn['agent_message']['message_actions']
        if action['service_identity'] == 'vehicle_repairer_booking'
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository._claims[claim_id] = claim.model_copy(
        update={
            'form': {
                **claim.form,
                'incident.location': claim.form['incident.location'].model_copy(
                    update={'status': FormStatus.CONFIRMED}
                ),
                'vehicle.damage_description': claim.form['vehicle.damage_description'].model_copy(
                    update={'status': FormStatus.CONFIRMED}
                ),
            }
        }
    )
    decided = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **AUTH,
            'Idempotency-Key': f'grant-{expected_status}',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )
    assert decided.status_code == 201

    task = repository.list_external_tasks_internal(claim_id)[0]
    failed = ExternalTaskRecord.model_validate(
        {
            **task.model_dump(),
            'status': status,
            'failure_code': failure_code,
            'delivery': delivery,
            'delivery_evidence': (
                'operation reached the controlled adapter'
                if delivery is ExternalTaskDelivery.SUBMITTED
                else None
            ),
            'provider_reference': None,
            'updated_at': task.updated_at + timedelta(microseconds=1),
        }
    )
    repository._external_tasks[task.task_id] = failed
    current = repository.get_claim_internal(claim_id)
    assert current is not None

    action = next(
        item
        for item in message_external_actions(
            repository,
            current,
            turn['agent_message']['message_id'],
        )
        if item.offer_id == offer['offer_id']
    )
    assert action.status.value == expected_status


def test_registered_task_without_adapter_releases_dispatch_without_claiming_success(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, session_id = _start_motor_claim(client, 'unavailable-adapter')
    turn = _send(
        client,
        claim_id,
        session_id,
        (
            'My car was rear-ended on Symonds Street and the rear bumper is damaged. '
            'Can you book a repair for me?'
        ),
        'unavailable-adapter',
    )
    offer = next(
        action
        for action in turn['agent_message']['message_actions']
        if action['service_identity'] == 'vehicle_repairer_booking'
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    repository._claims[claim_id] = stored.model_copy(
        update={
            'form': {
                **stored.form,
                'incident.location': stored.form['incident.location'].model_copy(
                    update={'status': FormStatus.CONFIRMED}
                ),
                'vehicle.damage_description': stored.form['vehicle.damage_description'].model_copy(
                    update={'status': FormStatus.CONFIRMED}
                ),
            }
        }
    )
    cast(Any, client.app).state.external_capability_dispatcher = ExternalCapabilityDispatcher()

    decided = client.post(
        _offer_route(claim_id, offer['offer_id']),
        headers={
            **AUTH,
            'Idempotency-Key': 'grant-without-adapter',
            'If-Match': str(turn['claim_revision']),
        },
        json={'decision': 'grant'},
    )

    assert decided.status_code == 201
    task = repository.list_external_tasks_internal(claim_id)[0]
    request = repository.list_external_task_requests_internal(claim_id)[0]
    assert task.status is ExternalTaskOperationStatus.PREPARED
    assert request.dispatch_reserved_at is None
    assert request.sent_at is None
