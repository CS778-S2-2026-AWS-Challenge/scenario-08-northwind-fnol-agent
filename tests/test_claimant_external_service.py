from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import AssessorFixtureFailure, MockAssessorServiceAdapter
from backend.app import create_app
from backend.domain.models import (
    ActorReference,
    ActorType,
    AssessorRoutingOperationStatus,
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
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord, RevisionConflict
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
    changed_replay = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'consent-contract',
            'If-Match': str(revision + 1),
        },
        json={'consent': True},
    )
    additional_key = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'consent-contract-additional-key',
            'If-Match': str(revision + 1),
        },
        json={'consent': True},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert changed_replay.status_code == 409
    assert changed_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert additional_key.status_code == 200
    assert additional_key.json()['revision'] == revision + 1
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


def test_claimant_consent_failure_leaves_claim_and_retry_state_unchanged() -> None:
    class FailingConsentRepository(FixtureRepository):
        def save_claim_mutation(
            self,
            claim: Any,
            expected_revision: int,
            idempotency: IdempotencyRecord,
        ) -> None:
            raise RuntimeError('injected consent transaction failure')

    repository = FailingConsentRepository()
    with TestClient(create_app(repository=repository), raise_server_exceptions=False) as client:
        claim_id, revision = _start_created_motor_claim(
            client,
            repository,
            key='consent-atomic-failure',
        )
        before = repository.get_claim_internal(claim_id)
        response = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing/consent',
            headers={
                **AUTH,
                'Idempotency-Key': 'consent-atomic-failure',
                'If-Match': str(revision),
            },
            json={'consent': True},
        )

    assert response.status_code == 500
    assert repository.get_claim_internal(claim_id) == before
    assert (
        repository.find_idempotency(
            'cus_demo',
            f'/api/v1/claims/{claim_id}/assessor-routing/consent',
            'consent-atomic-failure',
        )
        is None
    )


@pytest.mark.parametrize(
    ('failure', 'expected_code'),
    [
        (RevisionConflict(9), 'REVISION_CONFLICT'),
        (IdempotencyConflict('consent-conflict'), 'IDEMPOTENCY_CONFLICT'),
    ],
)
def test_claimant_consent_maps_atomic_repository_conflicts(
    failure: Exception,
    expected_code: str,
) -> None:
    class ConflictingConsentRepository(FixtureRepository):
        def save_claim_mutation(
            self,
            claim: Any,
            expected_revision: int,
            idempotency: IdempotencyRecord,
        ) -> None:
            raise failure

    repository = ConflictingConsentRepository()
    with TestClient(create_app(repository=repository)) as client:
        claim_id, revision = _start_created_motor_claim(
            client,
            repository,
            key=f'consent-{expected_code.lower()}',
        )
        response = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing/consent',
            headers={
                **AUTH,
                'Idempotency-Key': f'consent-{expected_code.lower()}',
                'If-Match': str(revision),
            },
            json={'consent': True},
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == expected_code


def test_claimant_assessor_request_creates_current_authority_and_safe_success(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    claim_id, revision = _start_created_motor_claim(client, repository, key='route-success')
    stored_before_consent = repository.get_claim_internal(claim_id)
    assert stored_before_consent is not None
    location = stored_before_consent.form['incident.location'].model_copy(
        update={'value': {'city': 'Auckland'}}
    )
    repository.save_claim(
        stored_before_consent.model_copy(
            update={'form': {**stored_before_consent.form, 'incident.location': location}}
        ),
        expected_revision=revision,
    )
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
    changed_replay = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'route-success',
            'If-Match': str(consent['revision'] + 1),
        },
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert changed_replay.status_code == 409
    assert changed_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
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
    stale_route = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'stale-route',
            'If-Match': str(revision - 1),
        },
    )
    missing_claim = client.post(
        '/api/v1/claims/clm_missing/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': 'missing-consent',
            'If-Match': '1',
        },
        json={'consent': True},
    )
    missing_route = client.post(
        '/api/v1/claims/clm_missing/assessor-routing',
        headers={
            **AUTH,
            'Idempotency-Key': 'missing-route',
            'If-Match': '1',
        },
    )

    assert without_consent.status_code == 409
    assert without_consent.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert stale_consent.status_code == 409
    assert stale_consent.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale_route.status_code == 409
    assert stale_route.json()['error']['code'] == 'REVISION_CONFLICT'
    assert missing_claim.status_code == 404
    assert missing_route.status_code == 404
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == revision
    assert stored.external_service_consents == []
    assert stored.assessor_routing is None


def test_claimant_route_maps_atomic_preparation_conflict() -> None:
    class ConflictingPreparationRepository(FixtureRepository):
        def save_assessor_routing_preparation(
            self,
            operation: Any,
            decision: Any,
            customer_id: str,
        ) -> None:
            raise IdempotencyConflict('routing-preparation-conflict')

    repository = ConflictingPreparationRepository()
    with TestClient(create_app(repository=repository)) as client:
        claim_id, revision = _start_created_motor_claim(
            client,
            repository,
            key='route-preparation-conflict',
        )
        consent = _grant_consent(
            client,
            claim_id,
            revision,
            key='route-preparation-conflict',
        )
        response = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers={
                **AUTH,
                'Idempotency-Key': 'route-preparation-conflict',
                'If-Match': str(consent['revision']),
            },
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert not any(
        decision.reason_codes == ['ASSESSOR_RULE_AUTHORISED']
        for decision in repository.list_agent_decisions(claim_id, 'cus_demo')
    )


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
        decisions_after_failure = repository.list_agent_decisions(claim_id, 'cus_demo')
        routing_decision = next(
            decision
            for decision in decisions_after_failure
            if decision.reason_codes == ['ASSESSOR_RULE_AUTHORISED']
        )
        routing_operation = next(iter(repository._assessor_routing_operations.values()))
        prepared_operation = routing_operation.model_copy(
            update={
                'status': AssessorRoutingOperationStatus.PREPARED,
                'failure_code': None,
                'updated_at': routing_operation.created_at,
            }
        )
        with pytest.raises(KeyError):
            repository.save_assessor_routing_preparation(
                prepared_operation,
                routing_decision,
                'another-customer',
            )
        repository._assessor_routing_operations[prepared_operation.operation_id] = (
            prepared_operation
        )
        repository.save_assessor_routing_preparation(
            prepared_operation,
            routing_decision,
            'cus_demo',
        )
        with pytest.raises(IdempotencyConflict):
            repository.save_assessor_routing_preparation(
                prepared_operation,
                routing_decision.model_copy(update={'customer_response': 'Changed response.'}),
                'cus_demo',
            )
        repository._assessor_routing_operations[routing_operation.operation_id] = routing_operation
        retried = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=route_headers,
        )
        decisions_after_retry = repository.list_agent_decisions(claim_id, 'cus_demo')

    assert timed_out.status_code == 503
    assert timed_out.json()['error']['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert timed_out.json()['error']['retryable'] is True
    assert after_failure is not None
    assert after_failure.revision == consent['revision']
    assert after_failure.assessor_routing is None
    assert after_failure.customer_next_step.status == 'assessor_request_ready'
    assert retried.status_code == 201
    assert retried.json()['action']['status'] == 'assigned'
    routing_decisions = [
        decision
        for decision in decisions_after_failure
        if decision.reason_codes == ['ASSESSOR_RULE_AUTHORISED']
    ]
    assert len(routing_decisions) == 1
    assert decisions_after_retry == decisions_after_failure


def test_claimant_retry_restores_authoritative_success_when_response_save_fails() -> None:
    class FailingResponseRepository(FixtureRepository):
        fail_route_response = True

        def save_idempotency(self, record: IdempotencyRecord) -> None:
            if self.fail_route_response and record.route.endswith('/assessor-routing'):
                self.fail_route_response = False
                raise RuntimeError('injected response save failure')
            super().save_idempotency(record)

    repository = FailingResponseRepository()
    with TestClient(create_app(repository=repository), raise_server_exceptions=False) as client:
        claim_id, revision = _start_created_motor_claim(
            client,
            repository,
            key='route-response-recovery',
        )
        consent = _grant_consent(
            client,
            claim_id,
            revision,
            key='route-response-recovery',
        )
        headers = {
            **AUTH,
            'Idempotency-Key': 'route-response-recovery',
            'If-Match': str(consent['revision']),
        }

        failed_response = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )
        after_failure = repository.get_claim_internal(claim_id)
        decisions_after_failure = repository.list_agent_decisions(claim_id, 'cus_demo')
        restored = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )

    assert failed_response.status_code == 500
    assert after_failure is not None
    assert after_failure.revision == consent['revision'] + 1
    assert after_failure.assessor_routing is not None
    assert restored.status_code == 200
    assert restored.json()['revision'] == after_failure.revision
    assert restored.json()['action']['status'] == 'assigned'
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == decisions_after_failure


def test_claimant_retry_recovers_accepted_provider_result_after_claim_cas_conflict() -> None:
    class AcceptedResultCASConflictRepository(FixtureRepository):
        fail_assessor_claim_write = True

        def save_claim(self, claim: Any, expected_revision: int) -> None:
            if self.fail_assessor_claim_write and claim.assessor_routing is not None:
                self.fail_assessor_claim_write = False
                current = self.get_claim_internal(claim.claim_id)
                assert current is not None
                concurrent = current.model_copy(
                    update={
                        'customer_next_step': current.customer_next_step.model_copy(
                            update={'summary': 'Claim details changed during provider response.'}
                        ),
                        'revision': current.revision + 1,
                        'updated_at': now_utc(),
                    }
                )
                super().save_claim(concurrent, expected_revision)
                raise RevisionConflict(concurrent.revision)
            super().save_claim(claim, expected_revision)

    class CountingAssessorAdapter(MockAssessorServiceAdapter):
        invocations = 0

        def route_assessor(self, command: Any, request_fingerprint: str) -> Any:
            self.invocations += 1
            return super().route_assessor(command, request_fingerprint)

    repository = AcceptedResultCASConflictRepository()
    adapter = CountingAssessorAdapter()
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        claim_id, revision = _start_created_motor_claim(
            client,
            repository,
            key='accepted-cas-recovery',
        )
        consent = _grant_consent(
            client,
            claim_id,
            revision,
            key='accepted-cas-recovery',
        )
        headers = {
            **AUTH,
            'Idempotency-Key': 'accepted-cas-recovery',
            'If-Match': str(consent['revision']),
        }

        conflicted = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )
        after_conflict = repository.get_claim_internal(claim_id)
        operations = list(repository._assessor_routing_operations.values())
        unrelated_retry = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers={
                **AUTH,
                'Idempotency-Key': 'accepted-cas-unrelated',
                'If-Match': str(consent['revision']),
            },
        )
        recovered = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )

    assert conflicted.status_code == 409
    assert conflicted.json()['error']['code'] == 'REVISION_CONFLICT'
    assert after_conflict is not None
    assert after_conflict.revision == consent['revision'] + 1
    assert after_conflict.assessor_routing is None
    assert len(operations) == 1
    assert operations[0].status is AssessorRoutingOperationStatus.ACCEPTED
    assert operations[0].result is not None
    accepted_reference = operations[0].result.assessor_reference
    assert accepted_reference is not None
    assert unrelated_retry.status_code == 409
    assert unrelated_retry.json()['error']['code'] == 'REVISION_CONFLICT'
    assert recovered.status_code == 200
    assert recovered.json()['revision'] == consent['revision'] + 2
    assert recovered.json()['action']['status'] == 'assigned'
    assert recovered.json()['action']['routing']['assessor_reference'] == accepted_reference
    assert adapter.invocations == 1
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.assessor_routing is not None
    assert stored.assessor_routing.assessor_reference == accepted_reference
    assert len(repository._assessor_routing_operations) == 1
