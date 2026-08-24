from datetime import timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorRoutingOutcome,
    ClaimCreationOutcome,
    ClaimsServiceAdapter,
    MockAssessorServiceAdapter,
    MockClaimsServiceAdapter,
)
from backend.app import create_app
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AssessorRoutingFailureCode,
    AssessorRoutingOperation,
    AssessorRoutingOperationStatus,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    AuthorityOutcome,
    ClaimCreationStatus,
    CreateExternalClaimRequest,
    CustomerNextStep,
    ExternalClaimResult,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
    ResponsibleParty,
    RouteAssessorRequest,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict
from backend.services.support import now_utc

INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
ASSESSOR_CONSENT_FIELDS = [
    'claim_id',
    'external_claim_id',
    'authorisation_ref',
    'claimant_consent_ref',
    'requested_action',
    'location.region',
]


class CountingAssessorAdapter(MockAssessorServiceAdapter):
    def __init__(
        self,
        *,
        failure_sequence: tuple[AssessorFixtureFailure, ...] = (),
        routing_status: AssessorRoutingStatus = AssessorRoutingStatus.ASSIGNED,
    ) -> None:
        super().__init__(
            failure_sequence=failure_sequence,
            routing_status=routing_status,
        )
        self.invocations = 0

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        self.invocations += 1
        return super().route_assessor(command, request_fingerprint)


class AssessorCASConflictRepository(FixtureRepository):
    def __init__(self) -> None:
        super().__init__()
        self.conflict_injected = False

    def save_claim(self, claim: WorkingClaim, expected_revision: int) -> None:
        if claim.assessor_routing is not None and not self.conflict_injected:
            current = self.get_claim_internal(claim.claim_id)
            assert current is not None
            self.conflict_injected = True
            super().save_claim(
                current.model_copy(
                    update={
                        'revision': current.revision + 1,
                        'updated_at': now_utc(),
                    }
                ),
                expected_revision,
            )
        super().save_claim(claim, expected_revision)


def create_working_claim(client: TestClient, key: str = 'working-claim') -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': key,
        },
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def save_authorisation(
    repository: FixtureRepository,
    *,
    claim_id: str,
    customer_id: str,
    session_id: str,
    decision_id: str,
    revision: int,
    action: AgentAction,
    reason_code: str,
    outcome: AuthorityOutcome = AuthorityOutcome.AUTHORISED,
) -> None:
    timestamp = now_utc()
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id=decision_id,
            claim_id=claim_id,
            session_id=session_id,
            trigger_message_id=f'msg_{decision_id}',
            action=action,
            reason_codes=[reason_code],
            customer_reason='A deterministic rule authorised this fixture action.',
            customer_response='The authorised integration action can continue.',
            customer_next_step=CustomerNextStep(
                status='authorised',
                summary='The authorised integration action can continue.',
                responsible_party=ResponsibleParty.NORTHWIND,
            ),
            authority=AgentAuthority(
                proposed_by='fixture_rule',
                validated_by='deterministic_rule_engine',
                outcome=outcome,
            ),
            resulting_revision=revision,
            created_at=timestamp,
        ),
        customer_id,
    )


def grant_assessor_consent(
    repository: FixtureRepository,
    claim_id: str,
    *,
    consent_ref: str = 'cns_vehicle_assessment',
    status: ExternalServiceConsentStatus = ExternalServiceConsentStatus.GRANTED,
    permitted_fields: list[str] | None = None,
    requested_action: str = 'vehicle_damage_assessment',
    granted_by: ActorReference | None = None,
) -> int:
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    timestamp = now_utc()
    consent = ExternalServiceConsent(
        consent_ref=consent_ref,
        service_identity='vehicle_damage_assessment_routing',
        requested_action=requested_action,
        permitted_fields=permitted_fields or ASSESSOR_CONSENT_FIELDS,
        status=status,
        granted_by=granted_by
        or ActorReference(actor_type=ActorType.CLAIMANT, actor_id=claim.customer_id),
        granted_at=timestamp,
        withdrawn_at=(timestamp if status is ExternalServiceConsentStatus.WITHDRAWN else None),
    )
    updated = claim.model_copy(
        update={
            'external_service_consents': [*claim.external_service_consents, consent],
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    repository.save_claim(updated, expected_revision=claim.revision)
    return updated.revision


def creation_payload(
    claim_id: str,
    revision: int,
    decision_id: str,
    *,
    route: str = 'standard_motor_intake',
) -> dict[str, object]:
    return {
        'working_claim_id': claim_id,
        'claim_revision': revision,
        'authorised_decision_id': decision_id,
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': route,
    }


def prepare_assessor_request(
    client: TestClient,
    repository: FixtureRepository,
    *,
    key: str,
    grant_consent: bool = True,
    consent_status: ExternalServiceConsentStatus = ExternalServiceConsentStatus.GRANTED,
    permitted_fields: list[str] | None = None,
    consent_granted_by: ActorReference | None = None,
) -> tuple[dict[str, object], int]:
    created = create_working_claim(client, key)
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    create_decision = f'dec_create_{key}'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=create_decision,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    creation_response = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 1, create_decision),
    )
    assert creation_response.status_code == 201
    consent_ref = f'cns_{key}'
    revision = 2
    if grant_consent:
        revision = grant_assessor_consent(
            repository,
            claim_id,
            consent_ref=consent_ref,
            status=consent_status,
            permitted_fields=permitted_fields,
            granted_by=consent_granted_by,
        )
    route_decision = f'dec_route_{key}'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=route_decision,
        revision=revision,
        action=AgentAction.PROCEED,
        reason_code='ASSESSOR_RULE_AUTHORISED',
    )
    return (
        {
            'claim_id': claim_id,
            'external_claim_id': creation_response.json()['external_claim_id'],
            'authorisation_ref': route_decision,
            'claimant_consent_ref': consent_ref,
            'requested_action': 'vehicle_damage_assessment',
            'location': {'region': 'Auckland'},
        },
        revision,
    )


def assessor_operation(
    *,
    claim_id: str = 'clm_operation',
    external_claim_id: str = 'ext_operation',
    operation_id: str = 'asr_op_fixture',
    authorised_revision: int = 3,
) -> AssessorRoutingOperation:
    timestamp = now_utc()
    return AssessorRoutingOperation(
        operation_id=operation_id,
        claim_id=claim_id,
        external_claim_id=external_claim_id,
        authorisation_ref='dec_operation',
        claimant_consent_ref='cns_operation',
        requested_action='vehicle_damage_assessment',
        authorised_revision=authorised_revision,
        request_fingerprint='fingerprint-a',
        status=AssessorRoutingOperationStatus.PREPARED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def assessor_result(*, reference: str = 'asr_fixture_operation') -> AssessorRoutingResult:
    return AssessorRoutingResult(
        routing_status=AssessorRoutingStatus.ASSIGNED,
        assessor_reference=reference,
        queue_reference='QUE-AUC-OPERATION',
        next_step='An assessor will review the confirmed claim information.',
    )


def test_assessor_operation_model_requires_a_consistent_state_outcome() -> None:
    prepared = assessor_operation()
    accepted_result = assessor_result()

    with pytest.raises(ValidationError, match='cannot precede creation'):
        AssessorRoutingOperation.model_validate(
            {
                **prepared.model_dump(),
                'updated_at': prepared.created_at - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match='Accepted assessor operation'):
        AssessorRoutingOperation.model_validate(
            {
                **prepared.model_dump(),
                'status': AssessorRoutingOperationStatus.ACCEPTED,
            }
        )
    accepted = AssessorRoutingOperation.model_validate(
        {
            **prepared.model_dump(),
            'status': AssessorRoutingOperationStatus.ACCEPTED,
            'result': accepted_result.model_dump(),
        }
    )
    assert accepted.result == accepted_result

    with pytest.raises(ValidationError, match='Failed assessor operation'):
        AssessorRoutingOperation.model_validate(
            {
                **prepared.model_dump(),
                'status': AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            }
        )
    failed = AssessorRoutingOperation.model_validate(
        {
            **prepared.model_dump(),
            'status': AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            'failure_code': AssessorRoutingFailureCode.ACCESS_DENIED,
        }
    )
    assert failed.failure_code is AssessorRoutingFailureCode.ACCESS_DENIED

    with pytest.raises(ValidationError, match='Prepared assessor operation'):
        AssessorRoutingOperation.model_validate(
            {
                **prepared.model_dump(),
                'failure_code': AssessorRoutingFailureCode.TIMEOUT,
            }
        )


def test_fixture_repository_enforces_assessor_operation_transitions() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='operation-transitions',
        )

    operation = assessor_operation(
        claim_id=str(payload['claim_id']),
        external_claim_id=str(payload['external_claim_id']),
        authorised_revision=revision,
    )
    assert repository.get_assessor_routing_operation(operation.operation_id) is None

    with pytest.raises(KeyError):
        repository.save_assessor_routing_operation(
            operation.model_copy(update={'claim_id': 'clm_missing'})
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            operation.model_copy(
                update={
                    'operation_id': 'asr_op_without_intent',
                    'status': AssessorRoutingOperationStatus.ACCEPTED,
                    'result': assessor_result(),
                }
            )
        )

    repository.save_assessor_routing_operation(operation)
    assert repository.get_assessor_routing_operation(operation.operation_id) == operation
    repository.save_assessor_routing_operation(operation)

    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            operation.model_copy(update={'requested_action': 'changed_action'})
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            operation.model_copy(update={'updated_at': operation.updated_at - timedelta(seconds=1)})
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            operation.model_copy(update={'updated_at': operation.updated_at + timedelta(seconds=1)})
        )

    accepted = operation.model_copy(
        update={
            'status': AssessorRoutingOperationStatus.ACCEPTED,
            'result': assessor_result(),
            'updated_at': operation.updated_at + timedelta(seconds=1),
        }
    )
    repository.save_assessor_routing_operation(accepted)
    repository.save_assessor_routing_operation(accepted)
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            accepted.model_copy(
                update={
                    'result': assessor_result(reference='asr_fixture_changed'),
                    'updated_at': accepted.updated_at + timedelta(seconds=1),
                }
            )
        )


def test_claim_creation_returns_complete_result_and_deduplicates_by_working_claim(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client)
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_create_authorised'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    payload = creation_payload(claim_id, 1, decision_id)

    first = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    replay = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    claimant_view = client.get(
        f'/api/v1/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-claimant'},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    body = first.json()
    assert body['claim_number'].startswith('NWF-')
    assert body['creation_status'] == 'created'
    assert body['route'] == 'standard_motor_intake'
    assert body['next_step'] == 'Claims intake review'
    assert body['expected_by'] is not None
    assert body['created_at'] is not None
    assert repository.claim_count == 1
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == 2
    assert stored.claim_state.workflow_state.value == 'created'
    assert claimant_view.status_code == 200
    assert claimant_view.json()['external_claim'] == body
    assert 'external_claim_fingerprint' not in claimant_view.json()
    assert 'assessor_routing' not in claimant_view.json()


def test_claim_creation_rejects_claimant_auth_stale_state_and_unauthorised_decision(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'guarded-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_review_only'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
        outcome=AuthorityOutcome.REVIEW_REQUIRED,
    )
    payload = creation_payload(claim_id, 1, decision_id)

    claimant_auth = client.post(
        '/internal/v1/claims/create',
        headers={'Authorization': 'Bearer synthetic-claimant'},
        json=payload,
    )
    unauthorised = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=payload,
    )
    stale = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'claim_revision': 2},
    )

    assert claimant_auth.status_code == 403
    assert claimant_auth.json()['error']['code'] == 'ACCESS_DENIED'
    assert unauthorised.status_code == 409
    assert unauthorised.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert repository.get_claim_internal(claim_id).external_claim is None  # type: ignore[union-attr]


def test_claim_creation_rejects_authorisation_from_an_older_revision(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'old-authorisation')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_old_create_authorisation'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    repository.save_claim(stored.model_copy(update={'revision': 2}), expected_revision=1)

    response = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 2, decision_id),
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    updated = repository.get_claim_internal(claim_id)
    assert updated is not None
    assert updated.external_claim is None


def test_internal_creation_requires_authentication_and_known_claim(client: TestClient) -> None:
    payload = creation_payload('clm_missing', 1, 'dec_missing')

    missing_auth = client.post('/internal/v1/claims/create', json=payload)
    unknown_claim = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=payload,
    )

    assert missing_auth.status_code == 401
    assert unknown_claim.status_code == 404


def test_claim_creation_rejects_changed_replay_and_unknown_provider_fields(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'creation-conflict')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    decision_id = 'dec_creation_conflict'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=str(session['session_id']),
        decision_id=decision_id,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    payload = creation_payload(claim_id, 1, decision_id)
    first = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)
    changed = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'route': 'different_route'},
    )
    provider_specific = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json={**payload, 'dynamodb_table': 'must-not-cross-boundary'},
    )

    assert first.status_code == 201
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert provider_specific.status_code == 422
    assert provider_specific.json()['error']['code'] == 'VALIDATION_ERROR'


def test_assessor_routing_requires_explicit_authorisation_and_is_idempotent(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'routed-claim')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    create_decision = 'dec_create_for_route'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=create_decision,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    creation = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 1, create_decision),
    ).json()
    consent_ref = 'cns_routed_claim'
    consent_revision = grant_assessor_consent(repository, claim_id, consent_ref=consent_ref)
    route_decision = 'dec_assessor_rule'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=route_decision,
        revision=consent_revision,
        action=AgentAction.PROCEED,
        reason_code='ASSESSOR_RULE_AUTHORISED',
    )
    route_payload = {
        'claim_id': claim_id,
        'external_claim_id': creation['external_claim_id'],
        'authorisation_ref': route_decision,
        'claimant_consent_ref': consent_ref,
        'requested_action': 'vehicle_damage_assessment',
        'location': {'region': 'Auckland'},
    }

    first = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json=route_payload,
    )
    replay = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json=route_payload,
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    body = first.json()
    assert body['routing_status'] == 'assigned'
    assert body['assessor_reference'].startswith('asr_fixture_')
    assert body['queue_reference'].startswith('QUE-AUC-')
    assert body['next_step']
    assert body['expected_by'] is not None
    assert body['limitations']
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == 4
    assert stored.customer_next_step.status == 'assessor_assigned'


def test_assessor_routing_requires_consent_from_the_shared_claim_context() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='missing-consent',
            grant_consent=False,
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert 'claimant consent' in response.json()['error']['message']
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None


@pytest.mark.parametrize(
    'granted_by',
    [
        ActorReference(actor_type=ActorType.STAFF, actor_id='stf_other_actor'),
        ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_other_claimant'),
    ],
)
def test_assessor_routing_rejects_consent_from_staff_or_another_claimant(
    granted_by: ActorReference,
) -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key=f'wrong-consent-actor-{granted_by.actor_type.value}',
            consent_granted_by=granted_by,
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert 'claimant consent' in response.json()['error']['message']
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None


@pytest.mark.parametrize(
    ('key', 'status', 'permitted_fields'),
    [
        ('withdrawn-consent', ExternalServiceConsentStatus.WITHDRAWN, None),
        (
            'insufficient-consent',
            ExternalServiceConsentStatus.GRANTED,
            [field for field in ASSESSOR_CONSENT_FIELDS if field != 'location.region'],
        ),
    ],
)
def test_assessor_routing_rejects_withdrawn_or_insufficient_consent(
    key: str,
    status: ExternalServiceConsentStatus,
    permitted_fields: list[str] | None,
) -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key=key,
            consent_status=status,
            permitted_fields=permitted_fields,
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 409
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None


def test_assessor_routing_rejects_authority_from_an_older_claim_revision() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='stale-assessor-authority',
        )
        claim = repository.get_claim_internal(str(payload['claim_id']))
        assert claim is not None
        repository.save_claim(
            claim.model_copy(update={'revision': revision + 1}),
            expected_revision=revision,
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 1
    assert stored.assessor_routing is None


@pytest.mark.parametrize(
    ('failure', 'status_code', 'error_code', 'retryable'),
    [
        (AssessorFixtureFailure.TIMEOUT, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (AssessorFixtureFailure.UNAVAILABLE, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (AssessorFixtureFailure.ACCESS_DENIED, 502, 'DEPENDENCY_FAILED', False),
        (AssessorFixtureFailure.MALFORMED, 502, 'DEPENDENCY_FAILED', False),
    ],
)
def test_assessor_fixture_failures_preserve_claim_state_and_never_report_success(
    failure: AssessorFixtureFailure,
    status_code: int,
    error_code: str,
    retryable: bool,
) -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(failure,))
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key=f'assessor-{failure.value}',
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == status_code
    error = response.json()['error']
    assert error['code'] == error_code
    assert error['retryable'] is retryable
    assert error['details'] == [{'field': 'assessor_service', 'reason': failure.value}]
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None
    assert stored.customer_next_step.status == 'claim_created'


def test_terminal_assessor_failure_is_replayed_without_another_provider_call() -> None:
    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(
        failure_sequence=(AssessorFixtureFailure.ACCESS_DENIED,),
    )
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='terminal-failure-replay',
        )
        failed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        replay = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert failed.status_code == 502
    assert replay.status_code == 502
    first_error = failed.json()['error']
    replay_error = replay.json()['error']
    assert {key: replay_error[key] for key in ('code', 'message', 'details', 'retryable')} == {
        key: first_error[key] for key in ('code', 'message', 'details', 'retryable')
    }
    assert adapter.invocations == 1
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None


def test_assessor_routing_rejects_an_unknown_or_mismatched_claim() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(repository=repository)) as client:
        missing = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json={
                'claim_id': 'clm_missing',
                'external_claim_id': 'ext_missing',
                'authorisation_ref': 'dec_missing',
                'claimant_consent_ref': 'cns_missing',
                'requested_action': 'vehicle_damage_assessment',
                'location': {'region': 'Auckland'},
            },
        )
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='external-claim-mismatch',
        )
        mismatched = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json={**payload, 'external_claim_id': 'ext_wrong'},
        )

    assert missing.status_code == 404
    assert mismatched.status_code == 409
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision
    assert stored.assessor_routing is None


def test_timeout_retry_is_safe_and_deduplicates_after_success() -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(AssessorFixtureFailure.TIMEOUT,))
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='timeout-retry',
        )
        timed_out = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        retry = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        replay = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        changed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json={**payload, 'location': {'region': 'Wellington'}},
        )

    assert timed_out.status_code == 503
    assert retry.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == retry.json()
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 1
    assert stored.assessor_routing is not None
    assert stored.assessor_routing.routing_status is AssessorRoutingStatus.ASSIGNED


def test_changed_payload_is_rejected_after_timeout_before_any_success() -> None:
    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(
        failure_sequence=(AssessorFixtureFailure.TIMEOUT,),
    )
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='timeout-changed-before-success',
        )
        timed_out = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        changed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json={**payload, 'location': {'region': 'Wellington'}},
        )
        retry = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert timed_out.status_code == 503
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert retry.status_code == 201
    assert adapter.invocations == 2
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 1
    assert stored.assessor_routing is not None


def test_provider_success_is_recovered_after_claim_revision_race() -> None:
    repository = AssessorCASConflictRepository()
    adapter = CountingAssessorAdapter()
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='provider-success-claim-race',
        )
        conflicted = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        recovered = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        replay = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert conflicted.status_code == 409
    assert conflicted.json()['error']['code'] == 'REVISION_CONFLICT'
    assert recovered.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == recovered.json()
    assert adapter.invocations == 1
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 2
    assert stored.assessor_routing is not None
    assert stored.assessor_routing.routing_status is AssessorRoutingStatus.ASSIGNED


def test_queued_assessor_result_preserves_queue_state_without_claiming_assignment() -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(routing_status=AssessorRoutingStatus.QUEUED)
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='queued-assessor',
        )
        response = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 201
    assert response.json()['routing_status'] == 'queued'
    assert response.json()['assessor_reference'] is None
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 1
    assert stored.customer_next_step.status == 'awaiting_assessor_assignment'


def test_assessor_routing_is_not_authorised_by_severity_alone(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    created = create_working_claim(client, 'severity-only')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    create_decision = 'dec_create_severity'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=create_decision,
        revision=1,
        action=AgentAction.CREATE_CLAIM,
        reason_code='CLAIM_CREATION_AUTHORISED',
    )
    creation = client.post(
        '/internal/v1/claims/create',
        headers=INTEGRATION_AUTH,
        json=creation_payload(claim_id, 1, create_decision),
    ).json()
    consent_ref = 'cns_severity_only'
    consent_revision = grant_assessor_consent(repository, claim_id, consent_ref=consent_ref)
    severity_decision = 'dec_severity_only'
    save_authorisation(
        repository,
        claim_id=claim_id,
        customer_id='cus_demo',
        session_id=session_id,
        decision_id=severity_decision,
        revision=consent_revision,
        action=AgentAction.PROCEED,
        reason_code='COMPLEX_EVENT_REVIEW',
    )

    response = client.post(
        '/internal/v1/assessors/route',
        headers=INTEGRATION_AUTH,
        json={
            'claim_id': claim_id,
            'external_claim_id': creation['external_claim_id'],
            'authorisation_ref': severity_decision,
            'claimant_consent_ref': consent_ref,
            'requested_action': 'vehicle_damage_assessment',
            'location': {'region': 'Auckland'},
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


class PendingClaimsAdapter(ClaimsServiceAdapter):
    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        del command, request_fingerprint
        timestamp = now_utc()
        return ClaimCreationOutcome(
            result=ExternalClaimResult(
                creation_status=ClaimCreationStatus.PENDING,
                route='provider_neutral_pending',
                next_step='Wait for the claims service confirmation.',
                source=IntegrationSource.CONFIGURED_SERVICE,
                expected_by=timestamp + timedelta(hours=2),
                created_at=timestamp,
            ),
            replayed=False,
        )


def test_app_accepts_replaceable_claims_adapter_without_public_schema_changes() -> None:
    repository = FixtureRepository()
    app = create_app(repository=repository, claims_service_adapter=PendingClaimsAdapter())
    with TestClient(app) as client:
        created = create_working_claim(client, 'replaceable-adapter')
        claim = created['claim']
        session = created['session']
        assert isinstance(claim, dict)
        assert isinstance(session, dict)
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_pending_adapter'
        save_authorisation(
            repository,
            claim_id=claim_id,
            customer_id='cus_demo',
            session_id=str(session['session_id']),
            decision_id=decision_id,
            revision=1,
            action=AgentAction.CREATE_CLAIM,
            reason_code='CLAIM_CREATION_AUTHORISED',
        )
        response = client.post(
            '/internal/v1/claims/create',
            headers=INTEGRATION_AUTH,
            json=creation_payload(claim_id, 1, decision_id),
        )

    assert response.status_code == 201
    assert response.json()['creation_status'] == 'pending'
    assert response.json()['external_claim_id'] is None
    assert response.json()['claim_number'] is None
    assert response.json()['source'] == 'configured_service'


def test_mock_adapters_reject_changed_payload_for_the_same_provider_reference() -> None:
    claim_adapter = MockClaimsServiceAdapter()
    claim_command = CreateExternalClaimRequest.model_validate(
        creation_payload('clm_fixture', 1, 'dec_fixture')
    )
    claim_adapter.create_claim(claim_command, 'fingerprint-a')

    with pytest.raises(AdapterIdempotencyConflict):
        claim_adapter.create_claim(claim_command, 'fingerprint-b')

    assessor_adapter = MockAssessorServiceAdapter()
    route_command = RouteAssessorRequest(
        claim_id='clm_fixture',
        external_claim_id='ext_fixture',
        authorisation_ref='dec_route',
        claimant_consent_ref='cns_route',
        requested_action='vehicle_damage_assessment',
        location={'region': 'Auckland'},
    )
    assessor_adapter.route_assessor(route_command, 'fingerprint-a')

    with pytest.raises(AdapterIdempotencyConflict):
        assessor_adapter.route_assessor(route_command, 'fingerprint-b')


def test_mock_assessor_reserves_the_first_fingerprint_before_retryable_failure() -> None:
    assessor_adapter = MockAssessorServiceAdapter(
        failure_sequence=(AssessorFixtureFailure.TIMEOUT,),
    )
    route_command = RouteAssessorRequest(
        claim_id='clm_retry_fingerprint',
        external_claim_id='ext_retry_fingerprint',
        authorisation_ref='dec_retry_fingerprint',
        claimant_consent_ref='cns_retry_fingerprint',
        requested_action='vehicle_damage_assessment',
        location={'region': 'Auckland'},
    )
    changed_command = route_command.model_copy(
        update={'location': {'region': 'Wellington'}},
    )

    with pytest.raises(AssessorAdapterFailure):
        assessor_adapter.route_assessor(route_command, 'fingerprint-a')
    with pytest.raises(AdapterIdempotencyConflict):
        assessor_adapter.route_assessor(changed_command, 'fingerprint-b')

    accepted = assessor_adapter.route_assessor(route_command, 'fingerprint-a')
    assert accepted.replayed is False
