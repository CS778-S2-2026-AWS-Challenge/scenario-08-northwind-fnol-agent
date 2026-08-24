from datetime import timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.claims_service import AssessorFixtureFailure, MockAssessorServiceAdapter
from backend.app import create_app
from backend.domain.models import (
    ActorReference,
    ActorType,
    ClaimCreationStatus,
    CustomerNextStep,
    ExternalClaimResult,
    FormSource,
    FormStatus,
    IntegrationSource,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkflowState,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.support import now_utc

AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def _start_created_motor_claim(
    client: TestClient,
    repository: FixtureRepository,
    *,
    key: str,
) -> tuple[str, int]:
    created = client.post(
        '/api/v1/claims',
        headers={**AUTH, 'Idempotency-Key': f'claim-{key}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = str(created['claim']['claim_id'])
    session_id = str(created['session']['session_id'])
    message = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **AUTH,
            'Idempotency-Key': f'message-{key}',
            'If-Match': '1',
        },
        json={
            'client_message_id': f'client-{key}',
            'content': {
                'type': 'text',
                'text': 'Another vehicle hit my car in Auckland. Nobody is injured.',
            },
            'evidence_refs': [],
        },
    )
    assert message.status_code == 200

    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    timestamp = now_utc()
    location = StructuredFormField(
        value='Auckland',
        source=FormSource.CLAIMANT,
        source_refs=[str(message.json()['claimant_message']['message_id'])],
        status=FormStatus.CONFIRMED,
        needed_for=NeededFor.CURRENT_ACTION,
        confidence=1.0,
        updated_at=timestamp,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
    )
    updated = claim.model_copy(
        update={
            'form': {**claim.form, 'incident.location': location},
            'claim_state': claim.claim_state.model_copy(
                update={'workflow_state': WorkflowState.CREATED}
            ),
            'route': 'standard_motor_intake',
            'external_claim': ExternalClaimResult(
                external_claim_id=f'ext_{key}',
                claim_number=f'NWF-{key.upper()}',
                creation_status=ClaimCreationStatus.CREATED,
                route='standard_motor_intake',
                next_step='Claims intake review',
                source=IntegrationSource.FIXTURE,
                expected_by=timestamp + timedelta(days=1),
                created_at=timestamp,
            ),
            'customer_next_step': CustomerNextStep(
                status='claim_created',
                summary='Claims intake review',
                responsible_party=ResponsibleParty.NORTHWIND,
            ),
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    repository.save_claim(updated, expected_revision=claim.revision)
    return claim_id, updated.revision


def _grant_consent(
    client: TestClient,
    claim_id: str,
    revision: int,
    *,
    key: str,
) -> dict[str, Any]:
    response = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': f'consent-{key}',
            'If-Match': str(revision),
        },
        json={'consent': True},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_claimant_assessor_action_appears_only_after_a_relevant_created_motor_claim(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    started = client.post(
        '/api/v1/claims',
        headers={**AUTH, 'Idempotency-Key': 'claim-not-ready'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    draft_id = str(started['claim']['claim_id'])

    draft = client.get(f'/api/v1/claims/{draft_id}', headers=AUTH)
    created_id, _revision = _start_created_motor_claim(
        client,
        repository,
        key='action-ready',
    )
    created = client.get(f'/api/v1/claims/{created_id}', headers=AUTH)

    assert draft.status_code == 200
    assert draft.json()['external_service_action'] is None
    assert created.status_code == 200
    action = created.json()['external_service_action']
    assert action['status'] == 'consent_required'
    assert action['provider'] == 'Controlled assessment fixture'
    assert action['purpose'].endswith('This does not decide coverage or approve repairs.')
    assert len(action['shared_data_summary']) == 4
    assert action['routing'] is None


def test_claimant_consent_is_bounded_persisted_and_idempotent(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, revision = _start_created_motor_claim(
        client,
        repository,
        key='consent-contract',
    )

    first = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'consent-contract',
            'If-Match': str(revision),
        },
        json={'consent': True},
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'consent-contract',
            'If-Match': str(revision),
        },
        json={'consent': True},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()['revision'] == revision + 1
    assert first.json()['action']['status'] == 'ready_to_request'
    assert first.json()['action']['consent_status'] == 'granted'
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == revision + 1
    assert len(stored.external_service_consents) == 1
    consent = stored.external_service_consents[0]
    assert consent.granted_by.actor_type is ActorType.CLAIMANT
    assert consent.granted_by.actor_id == 'cus_demo'
    assert set(consent.permitted_fields) == {
        'claim_id',
        'external_claim_id',
        'authorisation_ref',
        'claimant_consent_ref',
        'requested_action',
        'location.region',
    }
    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH).json()
    assert 'external_service_consents' not in claimant
    assert 'consent_ref' not in str(claimant)


def test_claimant_assessor_request_creates_current_authority_and_safe_success(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, revision = _start_created_motor_claim(client, repository, key='route-success')
    consent = _grant_consent(client, claim_id, revision, key='route-success')

    first = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'route-success',
            'If-Match': str(consent['revision']),
        },
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'route-success',
            'If-Match': str(consent['revision']),
        },
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    body = first.json()
    assert body['revision'] == consent['revision'] + 1
    assert body['action']['status'] == 'assigned'
    assert body['action']['can_request'] is False
    assert body['action']['routing']['routing_status'] == 'assigned'
    assert body['action']['routing']['assessor_reference'].startswith('asr_fixture_')
    assert body['customer_next_step']['responsible_party'] == 'external_party'
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    decisions = repository.list_agent_decisions(claim_id, 'cus_demo')
    assert decisions[-1].reason_codes == ['ASSESSOR_RULE_AUTHORISED']
    assert decisions[-1].resulting_revision == consent['revision']


def test_claimant_assessor_request_requires_consent_and_current_revision(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, revision = _start_created_motor_claim(client, repository, key='route-guard')

    without_consent = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'route-guard',
            'If-Match': str(revision),
        },
    )
    stale_consent = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'stale-consent',
            'If-Match': str(revision - 1),
        },
        json={'consent': True},
    )

    assert without_consent.status_code == 409
    assert without_consent.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert stale_consent.status_code == 409
    assert stale_consent.json()['error']['code'] == 'REVISION_CONFLICT'
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == revision
    assert stored.external_service_consents == []
    assert stored.assessor_routing is None


def test_claimant_sees_retryable_failure_then_safe_success_with_the_same_request() -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(
        failure_sequence=(AssessorFixtureFailure.TIMEOUT,),
    )
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        claim_id, revision = _start_created_motor_claim(client, repository, key='route-retry')
        consent = _grant_consent(client, claim_id, revision, key='route-retry')
        route_headers = {
            **AUTH,
            'Idempotency-Key': 'route-retry',
            'If-Match': str(consent['revision']),
        }

        timed_out = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=route_headers,
        )
        after_failure = repository.get_claim_internal(claim_id)
        retried = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=route_headers,
        )

    assert timed_out.status_code == 503
    assert timed_out.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert timed_out.json()['error']['retryable'] is True
    assert after_failure is not None
    assert after_failure.revision == consent['revision']
    assert after_failure.assessor_routing is None
    assert after_failure.customer_next_step.status == 'assessor_request_ready'
    assert retried.status_code == 201
    assert retried.json()['action']['status'] == 'assigned'
