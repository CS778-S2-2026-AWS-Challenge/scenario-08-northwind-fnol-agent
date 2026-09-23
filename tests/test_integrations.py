import json
from datetime import datetime, timedelta
from typing import Any, cast

import mongomock
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorResultOutcome,
    AssessorResultRequest,
    AssessorRoutingOutcome,
    ClaimCreationAdapterFailure,
    ClaimCreationOutcome,
    ClaimsServiceAdapter,
    MockAssessorServiceAdapter,
    MockClaimsServiceAdapter,
)
from backend.adapters.evidence_storage import (
    EvidenceStorageUnavailable,
    MockEvidenceStorage,
)
from backend.app import create_app
from backend.domain.claim_creation import (
    ClaimCreationDelivery,
    ClaimCreationFailureCode,
    ClaimCreationOperationRecord,
    ClaimCreationOperationStatus,
    ClaimCreationRecovery,
    assert_claim_creation_operation_transition,
    claim_creation_operation_id,
    classify_claim_creation_failure,
    evidence_snapshot_fingerprint,
)
from backend.domain.external_services import ExternalTaskResultVerification
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
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ExternalClaimResult,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
    ResponsibleParty,
    RouteAssessorRequest,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository
from backend.services.support import now_utc, request_fingerprint

INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
ASSESSOR_CONSENT_FIELDS = [
    'claim_id',
    'external_claim_id',
    'authorisation_ref',
    'claimant_consent_ref',
    'requested_action',
    'location.region',
]


def _result_auth(
    revision: int,
    key: str = 'receive-assessment-result',
) -> dict[str, str]:
    return {
        **INTEGRATION_AUTH,
        'Idempotency-Key': key,
        'If-Match': str(revision),
    }


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


class TimeoutOnceAssessorAdapter(MockAssessorServiceAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.invocations = 0

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        self.invocations += 1
        if self.invocations == 1:
            raise AssessorAdapterFailure(AssessorFixtureFailure.TIMEOUT)
        return super().route_assessor(command, request_fingerprint)


class CountingResultAdapter(MockAssessorServiceAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.result_invocations = 0

    def receive_result(
        self,
        command: AssessorResultRequest,
        request_fingerprint: str,
    ) -> AssessorResultOutcome:
        self.result_invocations += 1
        return super().receive_result(command, request_fingerprint)


class MalformedResultAdapter(MockAssessorServiceAdapter):
    def receive_result(
        self,
        command: AssessorResultRequest,
        request_fingerprint: str,
    ) -> AssessorResultOutcome:
        """Reject every result request as malformed fixture output.

        Args:
            command: Accepted task identity supplied by Runtime.
            request_fingerprint: Stable receive-operation fingerprint.

        Returns:
            No result because this test adapter always fails.

        Raises:
            AssessorAdapterFailure: Always, with the bounded malformed code.
        """

        raise AssessorAdapterFailure(AssessorFixtureFailure.MALFORMED)


class AssessorCASConflictRepository(FixtureRepository):
    def __init__(self) -> None:
        super().__init__()
        self.conflict_injected = False

    def save_claim(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        branch_evaluation: Any = None,
    ) -> None:
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
        super().save_claim(claim, expected_revision, branch_evaluation)


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
    repository: PersistenceRepository,
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
                responsible_party=ResponsibleParty.SYSTEM,
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
        'evidence_snapshot_fingerprint': evidence_snapshot_fingerprint([]),
        'confirmed_form': {},
        'evidence_refs': [],
        'pending_evidence': [],
        'route': route,
    }


def claim_creation_operation(
    *,
    status: ClaimCreationOperationStatus = ClaimCreationOperationStatus.PREPARED,
    timestamp: datetime | None = None,
) -> ClaimCreationOperationRecord:
    created_at = timestamp or now_utc()
    updates: dict[str, object] = {}
    if status in {
        ClaimCreationOperationStatus.SETTLEMENT_PENDING,
        ClaimCreationOperationStatus.ACCEPTED,
    }:
        updates = {
            'delivery': ClaimCreationDelivery.SUBMITTED,
            'recovery': (
                ClaimCreationRecovery.SETTLE_RECORDED_RESULT
                if status is ClaimCreationOperationStatus.SETTLEMENT_PENDING
                else None
            ),
            'result': ExternalClaimResult(
                external_claim_id='ext_operation',
                claim_number='NWF-2026-OPERATION',
                creation_status=ClaimCreationStatus.CREATED,
                route='standard_motor_intake',
                next_step='Claims intake review',
                source=IntegrationSource.FIXTURE,
                created_at=created_at,
            ),
        }
    elif status is not ClaimCreationOperationStatus.PREPARED:
        updates = {
            'failure_code': ClaimCreationFailureCode.TIMEOUT,
            'recovery': {
                ClaimCreationOperationStatus.RETRYABLE_FAILURE: (
                    ClaimCreationRecovery.RETRY_SAME_OPERATION
                ),
                ClaimCreationOperationStatus.TERMINAL_FAILURE: (
                    ClaimCreationRecovery.REVIEW_REQUIRED
                ),
                ClaimCreationOperationStatus.UNKNOWN_OUTCOME: (
                    ClaimCreationRecovery.RECONCILE_BEFORE_RETRY
                ),
            }[status],
            'delivery': (
                ClaimCreationDelivery.SUBMITTED
                if status is ClaimCreationOperationStatus.UNKNOWN_OUTCOME
                else ClaimCreationDelivery.NOT_SUBMITTED
            ),
        }
    return ClaimCreationOperationRecord(
        operation_id='cco_operation',
        claim_id='clm_operation',
        customer_id='cus_operation',
        authorised_decision_id='dec_operation',
        authorised_revision=1,
        request_fingerprint='a' * 64,
        evidence_snapshot_fingerprint='b' * 64,
        route='standard_motor_intake',
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        **updates,
    )


def test_claim_creation_operation_model_rejects_inconsistent_states() -> None:
    prepared = claim_creation_operation()
    with pytest.raises(ValidationError, match='time cannot move backwards'):
        ClaimCreationOperationRecord.model_validate(
            {
                **prepared.model_dump(),
                'updated_at': prepared.created_at - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match='prepared Claim creation operation'):
        ClaimCreationOperationRecord.model_validate(
            {**prepared.model_dump(), 'failure_code': ClaimCreationFailureCode.TIMEOUT}
        )
    with pytest.raises(ValidationError, match='recorded Claim creation result'):
        ClaimCreationOperationRecord.model_validate(
            {
                **prepared.model_dump(),
                'status': ClaimCreationOperationStatus.ACCEPTED,
                'delivery': ClaimCreationDelivery.SUBMITTED,
            }
        )
    with pytest.raises(ValidationError, match='classified failure'):
        ClaimCreationOperationRecord.model_validate(
            {**prepared.model_dump(), 'status': ClaimCreationOperationStatus.RETRYABLE_FAILURE}
        )
    with pytest.raises(ValidationError, match='failure code, delivery, status, and recovery'):
        ClaimCreationOperationRecord.model_validate(
            {
                **prepared.model_dump(),
                'status': ClaimCreationOperationStatus.RETRYABLE_FAILURE,
                'failure_code': ClaimCreationFailureCode.TIMEOUT,
                'recovery': ClaimCreationRecovery.REVIEW_REQUIRED,
            }
        )


@pytest.mark.parametrize(
    ('code', 'delivery', 'expected_status', 'expected_recovery'),
    [
        (
            ClaimCreationFailureCode.TIMEOUT,
            ClaimCreationDelivery.NOT_SUBMITTED,
            ClaimCreationOperationStatus.RETRYABLE_FAILURE,
            ClaimCreationRecovery.RETRY_SAME_OPERATION,
        ),
        (
            ClaimCreationFailureCode.TIMEOUT,
            ClaimCreationDelivery.SUBMITTED,
            ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
            ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
        ),
        (
            ClaimCreationFailureCode.UNAVAILABLE,
            ClaimCreationDelivery.NOT_SUBMITTED,
            ClaimCreationOperationStatus.RETRYABLE_FAILURE,
            ClaimCreationRecovery.RETRY_SAME_OPERATION,
        ),
        (
            ClaimCreationFailureCode.UNAVAILABLE,
            ClaimCreationDelivery.SUBMITTED,
            ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
            ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
        ),
        *[
            (
                ClaimCreationFailureCode.PARTIAL,
                delivery,
                ClaimCreationOperationStatus.UNKNOWN_OUTCOME,
                ClaimCreationRecovery.RECONCILE_BEFORE_RETRY,
            )
            for delivery in ClaimCreationDelivery
        ],
        *[
            (
                code,
                delivery,
                ClaimCreationOperationStatus.TERMINAL_FAILURE,
                ClaimCreationRecovery.REVIEW_REQUIRED,
            )
            for code in (
                ClaimCreationFailureCode.ACCESS_DENIED,
                ClaimCreationFailureCode.MALFORMED,
                ClaimCreationFailureCode.CONFLICTING,
            )
            for delivery in ClaimCreationDelivery
        ],
    ],
)
def test_claim_creation_failure_matrix_is_authoritative(
    code: ClaimCreationFailureCode,
    delivery: ClaimCreationDelivery,
    expected_status: ClaimCreationOperationStatus,
    expected_recovery: ClaimCreationRecovery,
) -> None:
    """Cover every code/delivery contract because each pair has distinct retry safety."""

    assert classify_claim_creation_failure(code, delivery) == (
        expected_status,
        expected_recovery,
    )
    prepared = claim_creation_operation()
    record = ClaimCreationOperationRecord.model_validate(
        {
            **prepared.model_dump(),
            'status': expected_status,
            'delivery': delivery,
            'failure_code': code,
            'recovery': expected_recovery,
        }
    )
    assert record.status is expected_status


def test_claim_creation_failure_matrix_rejects_illegal_retryable_access_denied() -> None:
    prepared = claim_creation_operation()
    with pytest.raises(
        ValidationError,
        match='failure code, delivery, status, and recovery conflict',
    ):
        ClaimCreationOperationRecord.model_validate(
            {
                **prepared.model_dump(),
                'status': ClaimCreationOperationStatus.RETRYABLE_FAILURE,
                'delivery': ClaimCreationDelivery.SUBMITTED,
                'failure_code': ClaimCreationFailureCode.ACCESS_DENIED,
                'recovery': ClaimCreationRecovery.RETRY_SAME_OPERATION,
            }
        )


def test_claim_creation_operation_transition_guards_identity_time_and_lifecycle() -> None:
    prepared = claim_creation_operation()
    assert_claim_creation_operation_transition(prepared, prepared)
    with pytest.raises(ValueError, match='identity is immutable'):
        assert_claim_creation_operation_transition(
            prepared,
            prepared.model_copy(update={'route': 'standard_home_intake'}),
        )
    with pytest.raises(ValueError, match='time cannot move backwards'):
        assert_claim_creation_operation_transition(
            prepared,
            prepared.model_copy(update={'updated_at': prepared.created_at - timedelta(seconds=1)}),
        )
    accepted = claim_creation_operation(status=ClaimCreationOperationStatus.ACCEPTED)
    with pytest.raises(ValueError, match='transition is not permitted'):
        assert_claim_creation_operation_transition(
            accepted,
            accepted.model_copy(
                update={
                    'status': ClaimCreationOperationStatus.PREPARED,
                    'delivery': ClaimCreationDelivery.NOT_SUBMITTED,
                    'result': None,
                    'updated_at': accepted.updated_at + timedelta(seconds=1),
                }
            ),
        )


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_claim_creation_repository_rejects_invalid_reservation_and_transitions(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(
            mongomock.MongoClient(),
            f'claim_creation_guards_{repository_kind}',
        )
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    app = create_app(repository=repository)
    with TestClient(app) as client:
        created = create_working_claim(client, f'operation-guards-{repository_kind}')
    claim = cast(dict[str, object], created['claim'])
    session = cast(dict[str, object], created['session'])
    claim_id = str(claim['claim_id'])
    decision_id = f'dec_operation_guards_{repository_kind}'
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
    operation = claim_creation_operation().model_copy(
        update={
            'operation_id': claim_creation_operation_id(claim_id, decision_id),
            'claim_id': claim_id,
            'customer_id': 'cus_demo',
            'authorised_decision_id': decision_id,
            'evidence_snapshot_fingerprint': evidence_snapshot_fingerprint([]),
        }
    )

    with pytest.raises(KeyError):
        repository.reserve_claim_creation_operation(
            operation.model_copy(update={'evidence_snapshot_fingerprint': 'f' * 64})
        )
    assert repository.reserve_claim_creation_operation(operation) is True
    assert repository.reserve_claim_creation_operation(operation) is False
    with pytest.raises(IdempotencyConflict):
        repository.reserve_claim_creation_operation(
            operation.model_copy(
                update={'integration_source': IntegrationSource.CONFIGURED_SERVICE}
            )
        )
    with pytest.raises(KeyError):
        repository.save_claim_creation_operation(
            operation.model_copy(update={'operation_id': 'cco_missing'})
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_claim_creation_operation(
            operation.model_copy(update={'updated_at': operation.updated_at + timedelta(seconds=1)})
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_claim_creation_operation(
            operation.model_copy(
                update={
                    'status': ClaimCreationOperationStatus.RETRYABLE_FAILURE,
                    'delivery': ClaimCreationDelivery.SUBMITTED,
                    'failure_code': ClaimCreationFailureCode.ACCESS_DENIED,
                    'recovery': ClaimCreationRecovery.RETRY_SAME_OPERATION,
                    'updated_at': operation.updated_at + timedelta(seconds=1),
                }
            )
        )


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

    with pytest.raises(ValidationError, match='returned no routing requires only a failure'):
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

    assert first.status_code == 201, first.text
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
    assert stored.assignee_id is None
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
    assert stored.customer_next_step.status == 'claim_created'
    assert stored.claim_state.workflow_state is WorkflowState.CREATED
    assert stored.assessor_routing is not None
    assert stored.assessor_routing.routing_status is AssessorRoutingStatus.ASSIGNED


def test_assessor_result_runs_through_runtime_storage_and_verification() -> None:
    repository = FixtureRepository()
    storage = MockEvidenceStorage()
    adapter = CountingResultAdapter()
    with TestClient(
        create_app(
            repository=repository,
            assessor_service_adapter=adapter,
            evidence_storage=storage,
        )
    ) as client:
        payload, _ = prepare_assessor_request(
            client,
            repository,
            key='returned-assessment-result',
        )
        routed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = repository.list_external_tasks_internal(claim_id)[0]
        before = repository.get_claim_internal(claim_id)
        assert before is not None

        received = client.post(
            f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result',
            headers=_result_auth(before.revision),
        )

        assert received.status_code == 201, received.text
        result = received.json()
        assert result['task_id'] == task.task_id
        assert result['claim_id'] == claim_id
        assert result['source']['system'] == 'controlled_assessment_fixture'
        assert result['source']['reference'].startswith('fixture-assessment/')
        assert result['verification'] == ExternalTaskResultVerification.REVIEW_REQUIRED.value
        assert result['verified_against_revision'] == before.revision + 1
        assert result['verified_at'] is not None
        assert len(result['evidence_ids']) == 1

        evidence_id = result['evidence_ids'][0]
        evidence = repository.get_evidence(claim_id, evidence_id, before.customer_id)
        assert evidence is not None
        assert evidence.status is EvidenceStatus.RECEIVED
        assert evidence.file_status is EvidenceFileStatus.READY
        assert evidence.provenance['simulation_only'] is True
        content = storage.read_upload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            storage_key=str(evidence.provenance['storage_key']),
        )
        assert content is not None
        report = json.loads(content)
        assert report['simulation_only'] is True
        assert report['task_id'] == task.task_id
        assert report['provider_reference'] == task.provider_reference

        after = repository.get_claim_internal(claim_id)
        assert after is not None
        assert after.revision == before.revision + 1
        assert after.form == before.form
        assert after.external_claim == before.external_claim
        assert after.assessor_routing == before.assessor_routing
        assert after.claim_state.workflow_state == before.claim_state.workflow_state

        claimant = client.get(
            f'/api/v1/claims/{claim_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
        assert claimant.status_code == 200
        assert claimant.json()['external_service_action']['status'] == 'assigned'
        assert 'result' not in claimant.json()['external_service_action']

        workbench = client.get(
            f'/api/v1/workbench/claims/{claim_id}/external-requests',
            headers=STAFF_AUTH,
        )
        assert workbench.status_code == 200
        lifecycle = workbench.json()['items'][0]['lifecycle']
        assert lifecycle['result'] == result['summary']
        assert lifecycle['result_source'] == result['source']
        assert lifecycle['result_verification_state'] == 'review_required'
        assert lifecycle['result_verified_against_revision'] == after.revision
        assert lifecycle['result_evidence'] == [
            {'evidence_id': evidence_id, 'status': 'received', 'file_status': 'ready'}
        ]

        downloaded = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=STAFF_AUTH,
        )
        assert downloaded.status_code == 200
        assert downloaded.content == content
        assert downloaded.headers['content-type'].startswith('application/json')

    assert adapter.result_invocations == 1


def test_assessor_result_receipt_is_idempotent_without_duplicate_claim_changes() -> None:
    repository = FixtureRepository()
    adapter = CountingResultAdapter()
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, _ = prepare_assessor_request(
            client,
            repository,
            key='returned-assessment-replay',
        )
        routed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = repository.list_external_tasks_internal(claim_id)[0]
        route = f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result'
        starting = repository.get_claim_internal(claim_id)
        assert starting is not None

        first = client.post(route, headers=_result_auth(starting.revision))
        first_claim = repository.get_claim_internal(claim_id)
        replay = client.post(route, headers=_result_auth(starting.revision))
        changed_key = client.post(
            route,
            headers=_result_auth(starting.revision, 'changed-result-receipt'),
        )
        replayed_claim = repository.get_claim_internal(claim_id)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert changed_key.status_code == 409
    assert changed_key.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert first_claim == replayed_claim
    assert adapter.result_invocations == 1
    assert len(repository.list_external_task_results_internal(claim_id)) == 1
    assert len(repository.list_evidence(claim_id, 'cus_demo')) == 1


def test_assessor_result_retry_finishes_after_an_interrupted_result_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    adapter = CountingResultAdapter()
    original = repository.save_external_task_result
    attempts = {'count': 0}

    def fail_first_result_write(result: Any, customer_id: str) -> None:
        attempts['count'] += 1
        if attempts['count'] == 1:
            raise IdempotencyConflict(result.result_id)
        original(result, customer_id)

    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, _ = prepare_assessor_request(
            client,
            repository,
            key='returned-assessment-interrupted',
        )
        routed = client.post('/internal/v1/assessors/route', headers=INTEGRATION_AUTH, json=payload)
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = repository.list_external_tasks_internal(claim_id)[0]
        route = f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result'
        starting = repository.get_claim_internal(claim_id)
        assert starting is not None
        monkeypatch.setattr(repository, 'save_external_task_result', fail_first_result_write)

        interrupted = client.post(route, headers=_result_auth(starting.revision))
        after_interruption = repository.get_claim_internal(claim_id)
        replay = client.post(route, headers=_result_auth(starting.revision))
        after_replay = repository.get_claim_internal(claim_id)

    assert interrupted.status_code == 409
    assert replay.status_code == 200
    assert replay.json()['verification'] == 'review_required'
    assert after_replay == after_interruption
    assert adapter.result_invocations == 2
    assert len(repository.list_external_task_results_internal(claim_id)) == 1


def test_assessor_result_requires_assignment_and_available_storage() -> None:
    queued_repository = FixtureRepository()
    queued_adapter = MockAssessorServiceAdapter(routing_status=AssessorRoutingStatus.QUEUED)
    with TestClient(
        create_app(repository=queued_repository, assessor_service_adapter=queued_adapter)
    ) as client:
        payload, _ = prepare_assessor_request(
            client,
            queued_repository,
            key='queued-assessment-result',
        )
        routed = client.post('/internal/v1/assessors/route', headers=INTEGRATION_AUTH, json=payload)
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = queued_repository.list_external_tasks_internal(claim_id)[0]
        queued_claim = queued_repository.get_claim_internal(claim_id)
        assert queued_claim is not None
        queued = client.post(
            f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result',
            headers=_result_auth(queued_claim.revision),
        )

    assert queued.status_code == 409
    assert queued_repository.list_external_task_results_internal(claim_id) == []

    outage_repository = FixtureRepository()
    outage_storage = MockEvidenceStorage()
    with TestClient(
        create_app(repository=outage_repository, evidence_storage=outage_storage)
    ) as client:
        payload, _ = prepare_assessor_request(
            client,
            outage_repository,
            key='assessment-result-storage-outage',
        )
        routed = client.post('/internal/v1/assessors/route', headers=INTEGRATION_AUTH, json=payload)
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = outage_repository.list_external_tasks_internal(claim_id)[0]
        before = outage_repository.get_claim_internal(claim_id)
        assert before is not None
        outage_storage.set_outage(
            EvidenceStorageUnavailable('OBJECT_STORAGE_UNAVAILABLE', 'synthetic outage')
        )
        unavailable = client.post(
            f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result',
            headers=_result_auth(before.revision),
        )

    assert unavailable.status_code == 503
    assert unavailable.json()['error']['retryable'] is True
    assert outage_repository.get_claim_internal(claim_id) == before
    assert outage_repository.list_external_task_results_internal(claim_id) == []
    evidence = outage_repository.list_evidence(claim_id, 'cus_demo')
    assert len(evidence) == 1
    assert evidence[0].status is EvidenceStatus.PENDING
    assert evidence[0].file_status is EvidenceFileStatus.NOT_AVAILABLE


def test_assessor_result_rejects_missing_authority_identity_and_malformed_output() -> None:
    repository = FixtureRepository()
    adapter = MalformedResultAdapter()
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, _ = prepare_assessor_request(
            client,
            repository,
            key='malformed-assessment-result',
        )
        routed = client.post('/internal/v1/assessors/route', headers=INTEGRATION_AUTH, json=payload)
        assert routed.status_code == 201
        claim_id = str(payload['claim_id'])
        task = repository.list_external_tasks_internal(claim_id)[0]
        route = f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/result'
        before = repository.get_claim_internal(claim_id)
        assert before is not None
        before_evidence = repository.list_evidence(claim_id, 'cus_demo')

        missing_auth = client.post(route)
        missing_claim = client.post(
            f'/internal/v1/claims/clm_missing/external-tasks/{task.task_id}/result',
            headers=_result_auth(1),
        )
        missing_task = client.post(
            f'/internal/v1/claims/{claim_id}/external-tasks/tsk_missing/result',
            headers=_result_auth(before.revision),
        )
        missing_key = client.post(
            route,
            headers={**INTEGRATION_AUTH, 'If-Match': str(before.revision)},
        )
        missing_revision = client.post(
            route,
            headers={**INTEGRATION_AUTH, 'Idempotency-Key': 'missing-revision'},
        )
        stale = client.post(
            route,
            headers=_result_auth(before.revision + 1, 'stale-result-receipt'),
        )
        malformed = client.post(route, headers=_result_auth(before.revision))

    assert missing_auth.status_code == 401
    assert missing_claim.status_code == 404
    assert missing_task.status_code == 404
    assert missing_key.status_code == 400
    assert missing_revision.status_code == 409
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == before.revision
    assert malformed.status_code == 502
    error = malformed.json()['error']
    assert error['code'] == 'DEPENDENCY_FAILED'
    assert error['message'] == 'The assessment service returned an unusable result.'
    assert error['retryable'] is False
    assert error['request_id'].startswith('req_')
    assert repository.get_claim_internal(claim_id) == before
    assert repository.list_external_task_results_internal(claim_id) == []
    assert repository.list_evidence(claim_id, 'cus_demo') == before_evidence


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


def test_retryable_assessor_operation_rejects_stale_authority_before_provider_retry() -> None:
    repository = FixtureRepository()
    adapter = TimeoutOnceAssessorAdapter()
    with TestClient(create_app(repository=repository, assessor_service_adapter=adapter)) as client:
        payload, revision = prepare_assessor_request(
            client,
            repository,
            key='retryable-stale-authority',
        )
        claim_id = str(payload['claim_id'])
        original_decision = repository.get_agent_decision_internal(
            claim_id,
            str(payload['authorisation_ref']),
        )
        assert original_decision is not None

        timed_out = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

        claim = repository.get_claim_internal(claim_id)
        assert claim is not None
        corrected_summary = 'Claim details were corrected before assessor retry.'
        repository.save_claim(
            claim.model_copy(
                update={
                    'customer_next_step': claim.customer_next_step.model_copy(
                        update={'summary': corrected_summary}
                    ),
                    'revision': revision + 1,
                    'updated_at': now_utc(),
                }
            ),
            expected_revision=revision,
        )

        stale_retry = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json=payload,
        )
        invocations_after_stale_retry = adapter.invocations
        stale_claim = repository.get_claim_internal(claim_id)
        operation_identity = {
            key: payload[key]
            for key in (
                'claim_id',
                'external_claim_id',
                'authorisation_ref',
                'claimant_consent_ref',
                'requested_action',
            )
        }
        operation_id = f'asr_op_{request_fingerprint(operation_identity)}'
        stale_operation = repository.get_assessor_routing_operation(operation_id)

        fresh_decision_id = 'dec_route_retryable_stale_authority_current'
        save_authorisation(
            repository,
            claim_id=claim_id,
            customer_id='cus_demo',
            session_id=original_decision.session_id,
            decision_id=fresh_decision_id,
            revision=revision + 1,
            action=AgentAction.PROCEED,
            reason_code='ASSESSOR_RULE_AUTHORISED',
        )
        refreshed = client.post(
            '/internal/v1/assessors/route',
            headers=INTEGRATION_AUTH,
            json={**payload, 'authorisation_ref': fresh_decision_id},
        )

    assert timed_out.status_code == 503
    assert stale_retry.status_code == 409
    assert stale_retry.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert 'current authority' in stale_retry.json()['error']['message']
    assert invocations_after_stale_retry == 1
    assert stale_claim is not None
    assert stale_claim.revision == revision + 1
    assert stale_claim.customer_next_step.summary == corrected_summary
    assert stale_claim.assessor_routing is None
    assert stale_operation is not None
    assert stale_operation.status is AssessorRoutingOperationStatus.RETRYABLE_FAILURE
    assert stale_operation.authorised_revision == revision
    assert refreshed.status_code == 201
    assert adapter.invocations == 2
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == revision + 2
    assert stored.assessor_routing is not None


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
    assert conflicted.json()['error']['code'] == 'REVISION_CONFLICT', conflicted.text
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

    assert response.status_code == 201, response.text
    assert response.json()['routing_status'] == 'queued'
    assert response.json()['assessor_reference'] is None
    stored = repository.get_claim_internal(str(payload['claim_id']))
    assert stored is not None
    assert stored.revision == revision + 1
    assert stored.customer_next_step.status == 'claim_created'
    assert stored.claim_state.workflow_state is WorkflowState.CREATED
    assert stored.assessor_routing is not None
    assert stored.assessor_routing.routing_status is AssessorRoutingStatus.QUEUED


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
    integration_source = IntegrationSource.CONFIGURED_SERVICE

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        del request_fingerprint
        timestamp = now_utc()
        return ClaimCreationOutcome(
            result=ExternalClaimResult(
                creation_status=ClaimCreationStatus.PENDING,
                route=command.route,
                next_step='Wait for the claims service confirmation.',
                source=IntegrationSource.CONFIGURED_SERVICE,
                expected_by=timestamp + timedelta(hours=2),
                created_at=timestamp,
            ),
            replayed=False,
        )

    def reconcile_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome | None:
        del command, request_fingerprint
        return None


class MismatchedSourceClaimsAdapter(PendingClaimsAdapter):
    integration_source = IntegrationSource.FIXTURE


class InterruptedClaimsAdapter(MockClaimsServiceAdapter):
    """Accept once, lose the response, then expose the accepted result to reconciliation."""

    def __init__(self) -> None:
        super().__init__()
        self.create_invocations = 0
        self.reconcile_invocations = 0

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        self.create_invocations += 1
        super().create_claim(command, request_fingerprint)
        raise ClaimCreationAdapterFailure(
            ClaimCreationFailureCode.TIMEOUT,
            delivery=ClaimCreationDelivery.SUBMITTED,
        )

    def reconcile_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome | None:
        self.reconcile_invocations += 1
        return super().reconcile_claim(command, request_fingerprint)


class FailedReconciliationClaimsAdapter(InterruptedClaimsAdapter):
    def reconcile_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome | None:
        del command, request_fingerprint
        self.reconcile_invocations += 1
        raise ClaimCreationAdapterFailure(
            ClaimCreationFailureCode.UNAVAILABLE,
            delivery=ClaimCreationDelivery.NOT_SUBMITTED,
        )


class RetryableClaimsAdapter(MockClaimsServiceAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.create_invocations = 0

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        self.create_invocations += 1
        if self.create_invocations == 1:
            raise ClaimCreationAdapterFailure(ClaimCreationFailureCode.UNAVAILABLE)
        return super().create_claim(command, request_fingerprint)


class TerminalFailureClaimsAdapter(MockClaimsServiceAdapter):
    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        del command, request_fingerprint
        raise ClaimCreationAdapterFailure(ClaimCreationFailureCode.ACCESS_DENIED)


class RevisionBumpClaimsAdapter(MockClaimsServiceAdapter):
    def __init__(self, repository: PersistenceRepository) -> None:
        super().__init__()
        self.repository = repository
        self.create_invocations = 0

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        self.create_invocations += 1
        outcome = super().create_claim(command, request_fingerprint)
        claim = self.repository.get_claim_internal(command.working_claim_id)
        assert claim is not None
        self.repository.save_claim(
            claim.model_copy(
                update={
                    'revision': claim.revision + 1,
                    'updated_at': now_utc(),
                }
            ),
            expected_revision=claim.revision,
        )
        return outcome


class ReservationRaceClaimsAdapter(MockClaimsServiceAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.create_invocations = 0
        self.reconcile_invocations = 0

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        self.create_invocations += 1
        return super().create_claim(command, request_fingerprint)

    def reconcile_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome | None:
        self.reconcile_invocations += 1
        return super().reconcile_claim(command, request_fingerprint)


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


def test_claim_creation_rejects_an_adapter_result_with_a_mismatched_source() -> None:
    repository = FixtureRepository()
    app = create_app(repository=repository, claims_service_adapter=MismatchedSourceClaimsAdapter())
    with TestClient(app) as client:
        created = create_working_claim(client, 'mismatched-source-adapter')
        claim = created['claim']
        session = created['session']
        assert isinstance(claim, dict)
        assert isinstance(session, dict)
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_mismatched_source_adapter'
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

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_claim is None
    assert stored.revision == 1


def test_claim_creation_reconciles_submitted_timeout_without_duplicate_creation() -> None:
    repository = FixtureRepository()
    adapter = InterruptedClaimsAdapter()
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, 'interrupted-claim-creation')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_interrupted_claim_creation'
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

        interrupted = client.post(
            '/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload
        )
        operation_id = claim_creation_operation_id(claim_id, decision_id)
        unresolved = repository.get_claim_creation_operation(operation_id)
        stored_before_reconcile = repository.get_claim_internal(claim_id)
        recovered = client.post(
            '/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload
        )

    assert interrupted.status_code == 503
    assert unresolved is not None
    assert unresolved.status is ClaimCreationOperationStatus.UNKNOWN_OUTCOME
    assert stored_before_reconcile is not None
    assert stored_before_reconcile.external_claim is None
    assert recovered.status_code == 200, recovered.text
    assert adapter.create_invocations == 1
    assert adapter.reconcile_invocations == 1
    accepted = repository.get_claim_creation_operation(operation_id)
    assert accepted is not None
    assert accepted.status is ClaimCreationOperationStatus.ACCEPTED
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_claim == accepted.result


def test_claim_creation_reconciliation_preserves_original_submitted_delivery() -> None:
    repository = FixtureRepository()
    adapter = FailedReconciliationClaimsAdapter()
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, 'failed-claim-reconciliation')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_failed_claim_reconciliation'
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
        second = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)

    assert first.status_code == 503
    assert second.status_code == 503
    operation = repository.get_claim_creation_operation(
        claim_creation_operation_id(claim_id, decision_id)
    )
    assert operation is not None
    assert operation.status is ClaimCreationOperationStatus.UNKNOWN_OUTCOME
    assert operation.delivery is ClaimCreationDelivery.SUBMITTED
    assert operation.failure_code is ClaimCreationFailureCode.TIMEOUT
    assert operation.recovery is ClaimCreationRecovery.RECONCILE_BEFORE_RETRY
    assert adapter.create_invocations == 1
    assert adapter.reconcile_invocations == 1


def test_claim_creation_retries_same_operation_after_unsubmitted_failure() -> None:
    repository = FixtureRepository()
    adapter = RetryableClaimsAdapter()
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, 'retryable-claim-creation')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_retryable_claim_creation'
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

        unavailable = client.post(
            '/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload
        )
        operation_id = claim_creation_operation_id(claim_id, decision_id)
        failed = repository.get_claim_creation_operation(operation_id)
        retry = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)

    assert unavailable.status_code == 503
    assert failed is not None
    assert failed.status is ClaimCreationOperationStatus.RETRYABLE_FAILURE
    assert retry.status_code == 201, retry.text
    assert adapter.create_invocations == 2
    accepted = repository.get_claim_creation_operation(operation_id)
    assert accepted is not None
    assert accepted.status is ClaimCreationOperationStatus.ACCEPTED
    assert accepted.created_at == failed.created_at


def test_claim_creation_persists_terminal_adapter_failure_without_claim_projection() -> None:
    repository = FixtureRepository()
    app = create_app(
        repository=repository,
        claims_service_adapter=TerminalFailureClaimsAdapter(),
    )
    with TestClient(app) as client:
        created = create_working_claim(client, 'terminal-claim-creation')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_terminal_claim_creation'
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

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    operation = repository.get_claim_creation_operation(
        claim_creation_operation_id(claim_id, decision_id)
    )
    assert operation is not None
    assert operation.status is ClaimCreationOperationStatus.TERMINAL_FAILURE
    assert operation.recovery is ClaimCreationRecovery.REVIEW_REQUIRED
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_claim is None


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_claim_creation_recovers_recorded_result_after_settlement_revision_conflict(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(
            mongomock.MongoClient(),
            f'claim_creation_settlement_{repository_kind}',
        )
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    adapter = RevisionBumpClaimsAdapter(repository)
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, f'settlement-conflict-{repository_kind}')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = f'dec_settlement_conflict_{repository_kind}'
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

        conflicted = client.post(
            '/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload
        )
        operation_id = claim_creation_operation_id(claim_id, decision_id)
        pending = repository.get_claim_creation_operation(operation_id)
        recovered = client.post(
            '/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload
        )

    assert conflicted.status_code == 409
    assert conflicted.json()['error']['code'] == 'REVISION_CONFLICT'
    assert pending is not None
    assert pending.status is ClaimCreationOperationStatus.SETTLEMENT_PENDING
    assert pending.result is not None
    assert pending.recovery is ClaimCreationRecovery.SETTLE_RECORDED_RESULT
    assert recovered.status_code == 200, recovered.text
    assert adapter.create_invocations == 1
    accepted = repository.get_claim_creation_operation(operation_id)
    assert accepted is not None
    assert accepted.status is ClaimCreationOperationStatus.ACCEPTED
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_claim == accepted.result
    assert stored.revision == 3


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_claim_creation_reservation_loser_reconciles_without_duplicate_provider_call(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(
            mongomock.MongoClient(),
            f'claim_creation_reservation_race_{repository_kind}',
        )
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    adapter = ReservationRaceClaimsAdapter()
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, f'reservation-race-{repository_kind}')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = f'dec_reservation_race_{repository_kind}'
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
        command = CreateExternalClaimRequest.model_validate(payload)
        fingerprint = request_fingerprint(command.model_dump(mode='json'))
        reserve = repository.reserve_claim_creation_operation

        def lose_reservation_race(operation: ClaimCreationOperationRecord) -> bool:
            assert reserve(operation) is True
            adapter.create_claim(command, fingerprint)
            return False

        repository.reserve_claim_creation_operation = lose_reservation_race  # type: ignore[method-assign]

        response = client.post(
            '/internal/v1/claims/create',
            headers=INTEGRATION_AUTH,
            json=payload,
        )

    assert response.status_code == 200, response.text
    assert adapter.create_invocations == 1
    assert adapter.reconcile_invocations == 1
    operation = repository.get_claim_creation_operation(
        claim_creation_operation_id(claim_id, decision_id)
    )
    assert operation is not None
    assert operation.status is ClaimCreationOperationStatus.ACCEPTED
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.external_claim == operation.result


@pytest.mark.parametrize(
    ('payload_override', 'field'),
    [
        ({'evidence_refs': ['evd_foreign']}, 'evidence_refs'),
        ({'evidence_refs': ['evd_duplicate', 'evd_duplicate']}, 'evidence_refs'),
        ({'evidence_snapshot_fingerprint': 'f' * 64}, 'evidence_snapshot_fingerprint'),
        ({'route': 'standard_home_intake'}, 'route'),
    ],
)
def test_claim_creation_rejects_context_mismatch_before_provider_invocation(
    payload_override: dict[str, object],
    field: str,
) -> None:
    repository = FixtureRepository()
    adapter = RetryableClaimsAdapter()
    app = create_app(repository=repository, claims_service_adapter=adapter)
    with TestClient(app) as client:
        created = create_working_claim(client, f'context-mismatch-{field}')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = f'dec_context_mismatch_{field}'
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
        payload = {**creation_payload(claim_id, 1, decision_id), **payload_override}

        response = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)

    assert response.status_code == 422
    assert any(item['field'] == field for item in response.json()['error']['details'])
    assert adapter.create_invocations == 0
    assert (
        repository.get_claim_creation_operation(claim_creation_operation_id(claim_id, decision_id))
        is None
    )


def test_claim_creation_accepts_complete_nonempty_evidence_snapshot() -> None:
    repository = FixtureRepository()
    app = create_app(repository=repository)
    with TestClient(app) as client:
        created = create_working_claim(client, 'complete-evidence-snapshot')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        timestamp = now_utc()
        evidence = EvidenceRecord(
            evidence_id='evd_complete_claim_creation',
            claim_id=claim_id,
            kind='incident_image',
            status=EvidenceStatus.RECEIVED,
            file_status=EvidenceFileStatus.READY,
            source=EvidenceSource.CLAIMANT,
            related_fields=['incident.description'],
            needed_for=['current_action'],
            created_at=timestamp,
            updated_at=timestamp,
        )
        repository.save_evidence(evidence, 'cus_demo')
        decision_id = 'dec_complete_evidence_snapshot'
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
        payload = {
            **creation_payload(claim_id, 1, decision_id),
            'evidence_refs': [evidence.evidence_id],
            'evidence_snapshot_fingerprint': evidence_snapshot_fingerprint([evidence]),
        }

        response = client.post('/internal/v1/claims/create', headers=INTEGRATION_AUTH, json=payload)

    assert response.status_code == 201, response.text
    operation = repository.get_claim_creation_operation(
        claim_creation_operation_id(claim_id, decision_id)
    )
    assert operation is not None
    assert operation.evidence_snapshot_fingerprint == payload['evidence_snapshot_fingerprint']
    assert operation.status is ClaimCreationOperationStatus.ACCEPTED


def test_mongodb_claim_creation_operation_survives_repository_restart() -> None:
    mongo_client: Any = mongomock.MongoClient()
    database_name = 'claim_creation_operation_restart'
    repository = MongoDBRepository(mongo_client, database_name)
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    restarted = MongoDBRepository(mongo_client, database_name)
    restarted._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    app = create_app(repository=repository)
    with TestClient(app) as api:
        created = create_working_claim(api, 'mongo-operation-restart')
        claim = cast(dict[str, object], created['claim'])
        session = cast(dict[str, object], created['session'])
        claim_id = str(claim['claim_id'])
        decision_id = 'dec_mongo_operation_restart'
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
        response = api.post(
            '/internal/v1/claims/create',
            headers=INTEGRATION_AUTH,
            json=creation_payload(claim_id, 1, decision_id),
        )

    operation = restarted.get_claim_creation_operation(
        claim_creation_operation_id(claim_id, decision_id)
    )
    stored_claim = restarted.get_claim_internal(claim_id)

    assert response.status_code == 201, response.text
    assert operation is not None
    assert operation.status is ClaimCreationOperationStatus.ACCEPTED
    assert stored_claim is not None
    assert stored_claim.external_claim == operation.result


def test_mock_adapters_reject_changed_payload_for_the_same_provider_reference() -> None:
    claim_adapter = MockClaimsServiceAdapter()
    claim_command = CreateExternalClaimRequest.model_validate(
        creation_payload('clm_fixture', 1, 'dec_fixture')
    )
    assert claim_adapter.reconcile_claim(claim_command, 'fingerprint-a') is None
    claim_adapter.create_claim(claim_command, 'fingerprint-a')

    with pytest.raises(AdapterIdempotencyConflict):
        claim_adapter.create_claim(claim_command, 'fingerprint-b')
    with pytest.raises(AdapterIdempotencyConflict):
        claim_adapter.reconcile_claim(claim_command, 'fingerprint-b')

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
