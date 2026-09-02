import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Lock
from typing import Any, ClassVar

import mongomock
import pytest
from pymongo.errors import ConfigurationError, ServerSelectionTimeoutError

from backend.adapters.claims_service import MockAssessorServiceAdapter
from backend.core.errors import ApiError
from backend.core.runtime_profiles import RuntimeCapabilityStatus
from backend.domain.external_services import (
    ASSESSOR_CONSENT_FIELDS,
    ASSESSOR_REQUESTED_ACTION,
    ASSESSOR_SERVICE_IDENTITY,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AssessorLocation,
    AssessorRoutingFailureCode,
    AssessorRoutingOperation,
    AssessorRoutingOperationStatus,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    AuthorityOutcome,
    Channel,
    ClaimCreationStatus,
    ClaimState,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ExternalClaimResult,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    RouteAssessorRequest,
    SessionRecord,
    SessionStatus,
    StaffActionRecord,
    StaffActionStatus,
    WorkingClaim,
)
from backend.domain.retrieval import (
    PolicyFacts,
    PolicyRetrievalRecord,
    RetrievalSource,
    ReviewSignalRecord,
)
from backend.repositories.mongodb import (
    MongoDBConfigurationError,
    MongoDBConnectionConfig,
    MongoDBRepository,
    connect_mongodb_repository,
    probe_mongodb_connectivity,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.external_service_entry import resolve_external_service_entry
from backend.services.integrations import assessor_operation_id, route_assessor


def _assert_persistence_contract(repository: MongoDBRepository) -> PersistenceRepository:
    return repository


def _claim(revision: int = 1) -> WorkingClaim:
    timestamp = datetime(2026, 8, 21, tzinfo=UTC)
    return WorkingClaim(
        claim_id='clm_mongo_001',
        customer_id='cus_mongo_001',
        revision=revision,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_mongo_001',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _session(claim: WorkingClaim) -> SessionRecord:
    timestamp = claim.created_at
    return SessionRecord(
        session_id='ses_mongo_001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )


def _message(claim: WorkingClaim, session: SessionRecord) -> MessageRecord:
    return MessageRecord(
        message_id='msg_mongo_001',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id='client-mongo-001',
        actor='claimant',
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'A synthetic incident.'},
        created_at=claim.created_at,
    )


def _decision(
    claim: WorkingClaim,
    session: SessionRecord,
    message: MessageRecord,
) -> AgentDecisionRecord:
    return AgentDecisionRecord(
        decision_id='dec_mongo_001',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        trigger_message_id=message.message_id,
        action=AgentAction.CONFIRM,
        reason_codes=['MATERIAL_FACTS_PROPOSED'],
        customer_reason='Please confirm the proposed detail.',
        customer_response='Please confirm the proposed detail.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=claim.revision,
        created_at=claim.created_at,
    )


def _evidence(claim: WorkingClaim) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id='evd_mongo_001',
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _retrieval(claim: WorkingClaim) -> PolicyRetrievalRecord:
    return PolicyRetrievalRecord(
        retrieval_id='ret_mongo_001',
        claim_id=claim.claim_id,
        source=RetrievalSource(
            system='synthetic-policy',
            reference='POL-MONGO-001',
            retrieved_at=claim.created_at,
        ),
        facts=PolicyFacts(
            policy_reference='POL-MONGO-001',
            status='active',
            excess_amount=500,
            currency='NZD',
        ),
    )


@pytest.fixture
def repository() -> MongoDBRepository:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def test_mongodb_connection_config_requires_uri_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_MONGODB_URI', raising=False)
    monkeypatch.delenv('NORTHWIND_MONGODB_DATABASE', raising=False)

    with pytest.raises(MongoDBConfigurationError, match='NORTHWIND_MONGODB_URI'):
        MongoDBConnectionConfig.from_environment()


def test_mongodb_connection_config_reads_bounded_non_secret_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://localhost:27017')
    monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', 'northwind_test')
    monkeypatch.setenv('NORTHWIND_MONGODB_COLLECTION', 'claim_records')
    monkeypatch.setenv('NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS', '750')

    config = MongoDBConnectionConfig.from_environment()

    assert config.database_name == 'northwind_test'
    assert config.collection_name == 'claim_records'
    assert config.server_selection_timeout_ms == 750


def test_mongodb_connection_config_representation_redacts_secret_uri() -> None:
    config = MongoDBConnectionConfig(
        'mongodb+srv://private-user:private-secret@example.invalid',
        'northwind_test',
    )

    representation = repr(config)

    assert 'private-user' not in representation
    assert 'private-secret' not in representation
    assert 'mongodb+srv' not in representation
    assert "database_name='northwind_test'" in representation


@pytest.mark.parametrize('timeout', ['not-a-number', '99', '60001'])
def test_mongodb_connection_config_rejects_invalid_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: str,
) -> None:
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://localhost:27017')
    monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', 'northwind_test')
    monkeypatch.setenv('NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS', timeout)

    with pytest.raises(MongoDBConfigurationError, match='TIMEOUT'):
        MongoDBConnectionConfig.from_environment()


@pytest.mark.parametrize(
    ('variable', 'value', 'message'),
    [
        ('NORTHWIND_MONGODB_DATABASE', 'invalid/database', 'DATABASE is invalid'),
        ('NORTHWIND_MONGODB_COLLECTION', 'system.secrets', 'COLLECTION is invalid'),
    ],
)
def test_mongodb_connection_config_rejects_invalid_names(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv('NORTHWIND_MONGODB_URI', 'mongodb://localhost:27017')
    monkeypatch.setenv('NORTHWIND_MONGODB_DATABASE', 'northwind_test')
    monkeypatch.setenv('NORTHWIND_MONGODB_COLLECTION', 'claim_records')
    monkeypatch.setenv(variable, value)

    with pytest.raises(MongoDBConfigurationError, match=message):
        MongoDBConnectionConfig.from_environment()


def test_connected_mongodb_repository_reports_verified_and_can_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client: Any = mongomock.MongoClient()
    monkeypatch.setattr('backend.repositories.mongodb.MongoClient', lambda *args, **kwargs: client)
    repository = connect_mongodb_repository(
        MongoDBConnectionConfig('mongodb://unused', 'northwind_test')
    )

    assert repository.connection_status() == 'verified'
    repository.close()


def test_mongodb_connectivity_probe_pings_and_closes_without_repository_initialisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProbeAdmin:
        calls: ClassVar[list[str]] = []

        @classmethod
        def command(cls, name: str) -> None:
            cls.calls.append(name)

    class ProbeClient:
        admin = ProbeAdmin()

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = ProbeClient()
    monkeypatch.setattr('backend.repositories.mongodb.MongoClient', lambda *args, **kwargs: client)

    status = probe_mongodb_connectivity(
        MongoDBConnectionConfig('mongodb://unused', 'northwind_test')
    )

    assert status == 'verified'
    assert client.admin.calls == ['ping']
    assert client.closed is True


def test_assessor_routing_persistence_is_provider_backed_and_idempotent(
    repository: MongoDBRepository,
) -> None:
    claim = _claim().model_copy(
        update={
            'external_claim': ExternalClaimResult(
                external_claim_id='ext_mongo_001',
                claim_number='NW-001',
                creation_status=ClaimCreationStatus.CREATED,
                route='motor',
                next_step='assessor',
                source=IntegrationSource.FIXTURE,
                created_at=_claim().created_at,
            )
        }
    )
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session)
    decision = _decision(claim, session, message).model_copy(
        update={
            'decision_id': 'dec_assessor_001',
            'reason_codes': ['ASSESSOR_RULE_AUTHORISED'],
            'resulting_revision': claim.revision,
        }
    )
    operation = AssessorRoutingOperation(
        operation_id='aro_mongo_001',
        claim_id=claim.claim_id,
        external_claim_id='ext_mongo_001',
        authorisation_ref=decision.decision_id,
        claimant_consent_ref='consent_mongo_001',
        requested_action='route_to_assessor',
        authorised_revision=claim.revision,
        request_fingerprint='fingerprint_mongo_001',
        status=AssessorRoutingOperationStatus.PREPARED,
        created_at=claim.created_at,
        updated_at=claim.created_at,
    )

    repository.save_assessor_routing_preparation(operation, decision, claim.customer_id)
    assert repository.get_assessor_routing_operation(operation.operation_id) == operation
    assert repository.get_agent_decision_internal(claim.claim_id, decision.decision_id) == decision
    stored_operation = repository._collection.find_one(
        {'_id': repository._record_id('assessor_routing_operation', operation.operation_id)}
    )
    assert stored_operation is not None
    assert stored_operation['claim_id'] == claim.claim_id

    repository.save_assessor_routing_preparation(operation, decision, claim.customer_id)
    accepted = operation.model_copy(
        update={
            'status': AssessorRoutingOperationStatus.ACCEPTED,
            'result': AssessorRoutingResult(
                routing_status=AssessorRoutingStatus.ASSIGNED,
                assessor_reference='asr_mongo_001',
                next_step='await_assessor',
            ),
            'updated_at': operation.created_at,
        }
    )
    repository.save_assessor_routing_operation(accepted)
    assert repository.get_assessor_routing_operation(operation.operation_id) == accepted
    repository.save_assessor_routing_operation(accepted)

    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            accepted.model_copy(update={'request_fingerprint': 'different'})
        )
    assert accepted.result is not None
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_operation(
            accepted.model_copy(
                update={
                    'result': accepted.result.model_copy(
                        update={'assessor_reference': 'asr_mongo_changed'}
                    )
                }
            )
        )


def test_assessor_routing_service_executes_with_mongodb_repository(
    repository: MongoDBRepository,
) -> None:
    timestamp = _claim().created_at
    consent = ExternalServiceConsent(
        consent_ref='consent_service_001',
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        permitted_fields=sorted(ASSESSOR_CONSENT_FIELDS),
        status=ExternalServiceConsentStatus.GRANTED,
        granted_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_mongo_001'),
        granted_at=timestamp,
    )
    claim = _claim().model_copy(
        update={
            'external_claim': ExternalClaimResult(
                external_claim_id='ext_service_001',
                claim_number='NW-SERVICE',
                creation_status=ClaimCreationStatus.CREATED,
                route='motor',
                next_step='assessor',
                source=IntegrationSource.FIXTURE,
                created_at=timestamp,
            ),
            'external_service_consents': [consent],
        }
    )
    session = _session(claim)
    repository.create_claim(claim, session)
    decision = _decision(claim, session, _message(claim, session)).model_copy(
        update={
            'decision_id': 'dec_service_001',
            'reason_codes': ['ASSESSOR_RULE_AUTHORISED'],
        }
    )
    payload = RouteAssessorRequest(
        claim_id=claim.claim_id,
        external_claim_id='ext_service_001',
        authorisation_ref=decision.decision_id,
        claimant_consent_ref=consent.consent_ref,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        location=AssessorLocation(region='Auckland'),
    )

    with pytest.raises(ApiError) as unavailable:
        route_assessor(
            repository,
            MockAssessorServiceAdapter(),
            resolve_external_service_entry(
                capability_status=RuntimeCapabilityStatus.PENDING_CONFIRMATION,
                allow_test_fixture=False,
            ),
            payload,
            authorisation_decision=decision,
        )
    assert unavailable.value.status_code == 503
    assert repository.get_assessor_routing_operation(assessor_operation_id(payload)) is None
    assert repository.list_external_tasks_internal(claim.claim_id) == []
    assert repository.list_external_task_requests_internal(claim.claim_id) == []

    result, replayed = route_assessor(
        repository,
        MockAssessorServiceAdapter(),
        resolve_external_service_entry(
            capability_status=RuntimeCapabilityStatus.USING_FIXTURE,
            allow_test_fixture=True,
        ),
        payload,
        authorisation_decision=decision,
    )

    assert replayed is False
    assert result.routing_status is AssessorRoutingStatus.ASSIGNED
    operation = repository.get_assessor_routing_operation(assessor_operation_id(payload))
    assert operation is not None
    assert operation.status is AssessorRoutingOperationStatus.ACCEPTED
    assert operation.result == result
    tasks = repository.list_external_tasks_internal(claim.claim_id)
    requests = repository.list_external_task_requests_internal(claim.claim_id)
    assert len(tasks) == len(requests) == 1
    assert tasks[0].status.value == 'accepted'
    assert tasks[0].integration_source is IntegrationSource.FIXTURE
    assert requests[0].task_id == tasks[0].task_id
    assert requests[0].operation_id == operation.operation_id
    assert requests[0].sent_at is not None
    repository.save_external_task_request(requests[0], claim.customer_id)
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_request(
            requests[0].model_copy(update={'purpose': 'Changed after the send.'}),
            claim.customer_id,
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_request(
            requests[0].model_copy(update={'request_id': 'erq_second_request'}),
            claim.customer_id,
        )
    with pytest.raises(KeyError):
        repository.save_external_task_request(requests[0], 'cus_another_customer')
    stored_claim = repository.get_claim_internal(claim.claim_id)
    assert stored_claim is not None
    assert stored_claim.assessor_routing == result


@pytest.mark.parametrize(
    ('status', 'failure_code'),
    [
        (
            AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            AssessorRoutingFailureCode.TIMEOUT,
        ),
        (
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            AssessorRoutingFailureCode.ACCESS_DENIED,
        ),
    ],
)
def test_assessor_routing_mongodb_persists_failure_transitions_and_terminal_immutability(
    repository: MongoDBRepository,
    status: AssessorRoutingOperationStatus,
    failure_code: AssessorRoutingFailureCode,
) -> None:
    claim = _claim().model_copy(
        update={
            'external_claim': ExternalClaimResult(
                external_claim_id='ext_failure_001',
                claim_number='NW-FAILURE',
                creation_status=ClaimCreationStatus.CREATED,
                route='motor',
                next_step='assessor',
                source=IntegrationSource.FIXTURE,
                created_at=_claim().created_at,
            )
        }
    )
    repository.create_claim(claim, _session(claim))
    operation = AssessorRoutingOperation(
        operation_id=f'aro_{status.value}',
        claim_id=claim.claim_id,
        external_claim_id='ext_failure_001',
        authorisation_ref='dec_failure_001',
        claimant_consent_ref='consent_failure_001',
        requested_action='route_to_assessor',
        authorised_revision=claim.revision,
        request_fingerprint=f'fingerprint_{status.value}',
        status=AssessorRoutingOperationStatus.PREPARED,
        created_at=claim.created_at,
        updated_at=claim.created_at,
    )
    repository.save_assessor_routing_operation(operation)
    failed = operation.model_copy(
        update={
            'status': status,
            'failure_code': failure_code,
            'updated_at': operation.created_at,
        }
    )
    repository.save_assessor_routing_operation(failed)
    assert repository.get_assessor_routing_operation(operation.operation_id) == failed
    if status is AssessorRoutingOperationStatus.RETRYABLE_FAILURE:
        accepted = failed.model_copy(
            update={
                'status': AssessorRoutingOperationStatus.ACCEPTED,
                'failure_code': None,
                'result': AssessorRoutingResult(
                    routing_status=AssessorRoutingStatus.ASSIGNED,
                    assessor_reference='asr_retryable_001',
                    next_step='await_assessor',
                ),
            }
        )
        repository.save_assessor_routing_operation(accepted)
        assert repository.get_assessor_routing_operation(operation.operation_id) == accepted
    if status is AssessorRoutingOperationStatus.TERMINAL_FAILURE:
        with pytest.raises(IdempotencyConflict):
            repository.save_assessor_routing_operation(
                failed.model_copy(
                    update={
                        'failure_code': AssessorRoutingFailureCode.MALFORMED,
                        'updated_at': failed.updated_at,
                    }
                )
            )


def test_assessor_routing_mongodb_preparation_is_atomic_on_conflicting_decision(
    repository: MongoDBRepository,
) -> None:
    claim = _claim().model_copy(
        update={
            'external_claim': ExternalClaimResult(
                external_claim_id='ext_atomic_001',
                claim_number='NW-ATOMIC',
                creation_status=ClaimCreationStatus.CREATED,
                route='motor',
                next_step='assessor',
                source=IntegrationSource.FIXTURE,
                created_at=_claim().created_at,
            )
        }
    )
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session)
    decision = _decision(claim, session, message).model_copy(
        update={
            'decision_id': 'dec_atomic_001',
            'reason_codes': ['ASSESSOR_RULE_AUTHORISED'],
        }
    )
    conflicting_decision = decision.model_copy(update={'customer_response': 'conflicting decision'})
    repository.save_agent_decision(conflicting_decision, claim.customer_id)
    operation = AssessorRoutingOperation(
        operation_id='aro_atomic_001',
        claim_id=claim.claim_id,
        external_claim_id='ext_atomic_001',
        authorisation_ref=decision.decision_id,
        claimant_consent_ref='consent_atomic_001',
        requested_action='route_to_assessor',
        authorised_revision=claim.revision,
        request_fingerprint='fingerprint_atomic_001',
        status=AssessorRoutingOperationStatus.PREPARED,
        created_at=claim.created_at,
        updated_at=claim.created_at,
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_assessor_routing_preparation(operation, decision, claim.customer_id)
    assert repository.get_assessor_routing_operation(operation.operation_id) is None
    assert (
        repository.get_agent_decision_internal(claim.claim_id, decision.decision_id)
        == conflicting_decision
    )


def test_mongodb_connectivity_probe_bounds_failure_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdmin:
        @staticmethod
        def command(_name: str) -> None:
            raise ServerSelectionTimeoutError(
                'provider rejected mongodb+srv://probe-user:probe-secret@example.invalid'
            )

    class FailingClient:
        admin = FailingAdmin()

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = FailingClient()
    monkeypatch.setattr('backend.repositories.mongodb.MongoClient', lambda *args, **kwargs: client)

    status = probe_mongodb_connectivity(
        MongoDBConnectionConfig(
            'mongodb+srv://configured-user:configured-secret@example.invalid',
            'northwind_test',
        )
    )

    assert status == 'unavailable'
    assert client.closed is True


def test_mongodb_connection_failure_closes_client_without_exposing_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdmin:
        @staticmethod
        def command(name: str) -> None:
            assert name == 'ping'
            raise ServerSelectionTimeoutError(
                'provider rejected mongodb+srv://ping-user:ping-secret@example.invalid'
            )

    class FailingClient:
        admin = FailingAdmin()

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client: FailingClient = FailingClient()
    monkeypatch.setattr('backend.repositories.mongodb.MongoClient', lambda *args, **kwargs: client)
    secret_uri = 'mongodb+srv://user:secret@example.invalid'

    with pytest.raises(MongoDBConfigurationError) as error:
        connect_mongodb_repository(MongoDBConnectionConfig(secret_uri, 'northwind_test'))

    assert client.closed
    formatted = ''.join(traceback.format_exception(error.value))
    assert secret_uri not in formatted
    assert 'ping-user' not in formatted
    assert 'ping-secret' not in formatted
    assert 'provider rejected' not in formatted


@pytest.mark.parametrize('provider_error', [ValueError, ConfigurationError])
def test_mongodb_constructor_failure_is_bounded_without_exposing_uri(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: type[Exception],
) -> None:
    secret_uri = 'mongodb+srv://constructor-user:constructor-secret@example.invalid'

    def fail_constructor(*args: object, **kwargs: object) -> None:
        raise provider_error(f'invalid provider URI: {secret_uri}')

    monkeypatch.setattr('backend.repositories.mongodb.MongoClient', fail_constructor)

    with pytest.raises(MongoDBConfigurationError) as error:
        connect_mongodb_repository(MongoDBConnectionConfig(secret_uri, 'northwind_test'))

    formatted = ''.join(traceback.format_exception(error.value))
    assert secret_uri not in formatted
    assert 'constructor-user' not in formatted
    assert 'constructor-secret' not in formatted
    assert 'invalid provider URI' not in formatted


def test_mongodb_connection_status_bounds_local_configuration_failure(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_ping(_name: str) -> None:
        raise ValueError('invalid local client configuration')

    monkeypatch.setattr(repository._client.admin, 'command', fail_ping)

    assert repository.connection_status() == 'unavailable'


def test_claim_and_session_round_trip_enforces_customer_ownership(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.get_claim(claim.claim_id, 'another-customer') is None
    assert repository.get_session(claim.claim_id, session.session_id, claim.customer_id) == session
    assert repository.list_claims_for_customer(claim.customer_id) == [claim]
    assert repository.list_sessions_for_claim(claim.claim_id, claim.customer_id) == [session]


def test_claim_save_uses_optimistic_revision(repository: MongoDBRepository) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    updated = claim.model_copy(update={'revision': 2})

    repository.save_claim(updated, expected_revision=1)
    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated

    with pytest.raises(RevisionConflict) as error:
        repository.save_claim(updated.model_copy(update={'revision': 3}), expected_revision=1)
    assert error.value.current_revision == 2


def test_claim_mutation_persists_revision_and_idempotency_together(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    updated = claim.model_copy(update={'revision': 2})
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/api/v1/claims/clm_mongo_001/consent',
        key='claim-mutation-key',
        request_fingerprint='claim-mutation-fingerprint',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )

    repository.save_claim_mutation(updated, 1, idempotency)

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        == idempotency
    )
    with pytest.raises(KeyError):
        repository.save_claim_mutation(
            updated.model_copy(update={'revision': 3}),
            2,
            IdempotencyRecord(**{**idempotency.__dict__, 'actor_id': 'another-customer'}),
        )


def test_idempotency_rejects_changed_replay(repository: MongoDBRepository) -> None:
    from backend.repositories.protocols import IdempotencyRecord

    record = IdempotencyRecord(
        actor_id='cus_mongo_001',
        route='/api/v1/claims',
        key='same-key',
        request_fingerprint='fingerprint-a',
        claim_id='clm_mongo_001',
        session_id='ses_mongo_001',
    )
    repository.save_idempotency(record)
    assert repository.find_idempotency(record.actor_id, record.route, record.key) == record

    repository.save_idempotency(record)
    with pytest.raises(IdempotencyConflict):
        repository.save_idempotency(
            record.__class__(**{**record.__dict__, 'request_fingerprint': 'fingerprint-b'})
        )


def test_session_mutation_rejects_cross_record_relationships_before_transaction(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    session = _session(claim).model_copy(update={'customer_id': 'another-customer'})
    from backend.repositories.protocols import IdempotencyRecord

    with pytest.raises(KeyError):
        repository.save_session_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            session=session,
            idempotency=IdempotencyRecord(
                actor_id=claim.customer_id,
                route='/sessions',
                key='session-key',
                request_fingerprint='fingerprint',
                claim_id=claim.claim_id,
                session_id=session.session_id,
            ),
        )


def test_session_identity_cannot_be_overwritten_by_another_claim(
    repository: MongoDBRepository,
) -> None:
    first_claim = _claim()
    repository.create_claim(first_claim, _session(first_claim))
    assert first_claim.active_session_id is not None
    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'active_session_id': first_claim.active_session_id,
        }
    )
    second_session = _session(second_claim)

    with pytest.raises(IdempotencyConflict):
        repository.create_claim(second_claim, second_session)

    stored = repository._collection.find_one(
        {'_id': repository._record_id('session', first_claim.active_session_id)}
    )
    assert stored is not None
    assert stored['claim_id'] == first_claim.claim_id
    assert stored['customer_id'] == first_claim.customer_id


def test_save_session_rejects_existing_session_for_another_customer(
    repository: MongoDBRepository,
) -> None:
    first_claim = _claim()
    repository.create_claim(first_claim, _session(first_claim))
    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'active_session_id': 'ses_mongo_002',
            'customer_id': 'another-customer',
        }
    )
    second_session = _session(second_claim).model_copy(update={'session_id': 'ses_mongo_002'})
    repository.create_claim(second_claim, second_session)
    conflicting = second_session.model_copy(update={'session_id': first_claim.active_session_id})

    with pytest.raises(IdempotencyConflict):
        repository.save_session(conflicting)


def test_child_record_identity_cannot_cross_claims(repository: MongoDBRepository) -> None:
    first_claim = _claim()
    first_session = _session(first_claim)
    repository.create_claim(first_claim, first_session)
    repository.save_evidence(_evidence(first_claim), first_claim.customer_id)
    repository.save_message(_message(first_claim, first_session), first_claim.customer_id)

    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'customer_id': 'cus_mongo_002',
            'active_session_id': 'ses_mongo_002',
        }
    )
    second_session = first_session.model_copy(
        update={
            'session_id': 'ses_mongo_002',
            'claim_id': second_claim.claim_id,
            'customer_id': second_claim.customer_id,
        }
    )
    repository.create_claim(second_claim, second_session)

    with pytest.raises(IdempotencyConflict):
        repository.save_evidence(_evidence(second_claim), second_claim.customer_id)
    with pytest.raises(IdempotencyConflict):
        repository.save_message(_message(second_claim, second_session), second_claim.customer_id)

    assert repository.get_evidence(
        first_claim.claim_id, 'evd_mongo_001', first_claim.customer_id
    ) == _evidence(first_claim)
    assert repository.get_message(
        first_claim.claim_id,
        first_session.session_id,
        'msg_mongo_001',
        first_claim.customer_id,
    ) == _message(first_claim, first_session)


def test_child_record_identity_is_atomic_under_competing_writers(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_claim = _claim()
    repository.create_claim(first_claim, _session(first_claim))
    second_claim = first_claim.model_copy(
        update={
            'claim_id': 'clm_mongo_002',
            'customer_id': 'cus_mongo_002',
            'active_session_id': 'ses_mongo_002',
        }
    )
    repository.create_claim(
        second_claim,
        _session(second_claim).model_copy(update={'session_id': 'ses_mongo_002'}),
    )

    original_find_one = repository._collection.find_one
    ownership_reads = Barrier(2)
    ownership_lock = Lock()
    ownership_waits_remaining = 2

    def coordinated_find_one(*args: object, **kwargs: object) -> object:
        query = args[0] if args else kwargs.get('filter')
        should_wait = False
        nonlocal ownership_waits_remaining
        if isinstance(query, dict) and query.get('_id') == repository._record_id(
            'evidence', 'evd_mongo_001'
        ):
            with ownership_lock:
                if ownership_waits_remaining:
                    ownership_waits_remaining -= 1
                    should_wait = True
        if should_wait:
            ownership_reads.wait(timeout=5)
        return original_find_one(*args, **kwargs)

    monkeypatch.setattr(repository._collection, 'find_one', coordinated_find_one)

    def save_for(claim: WorkingClaim) -> str:
        try:
            repository.save_evidence(_evidence(claim), claim.customer_id)
        except IdempotencyConflict:
            return 'conflict'
        return 'saved'

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save_for, (first_claim, second_claim)))

    assert sorted(results) == ['conflict', 'saved']
    stored = repository._collection.find_one(
        {'_id': repository._record_id('evidence', 'evd_mongo_001')}
    )
    assert stored is not None
    assert stored['claim_id'] in {first_claim.claim_id, second_claim.claim_id}
    winning_claim = first_claim if stored['claim_id'] == first_claim.claim_id else second_claim
    losing_claim = second_claim if winning_claim is first_claim else first_claim
    assert repository.get_evidence(
        winning_claim.claim_id,
        'evd_mongo_001',
        winning_claim.customer_id,
    ) == _evidence(winning_claim)
    assert (
        repository.get_evidence(
            losing_claim.claim_id,
            'evd_mongo_001',
            losing_claim.customer_id,
        )
        is None
    )


def test_client_message_id_is_unique_within_claim(repository: MongoDBRepository) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    first = _message(claim, session)
    repository.save_message(first, claim.customer_id)

    duplicate = first.model_copy(update={'message_id': 'msg_mongo_duplicate'})
    with pytest.raises(IdempotencyConflict):
        repository.save_message(duplicate, claim.customer_id)
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == [
        first
    ]


def test_client_message_id_conflict_is_prechecked_before_mutation(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    first = _message(claim, session)
    repository.save_message(first, claim.customer_id)
    duplicate = first.model_copy(update={'message_id': 'msg_mongo_duplicate_mutation'})
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})

    from backend.repositories.protocols import IdempotencyRecord

    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))
    with pytest.raises(IdempotencyConflict):
        repository.save_message_mutation(
            updated_claim,
            1,
            updated_session,
            duplicate,
            IdempotencyRecord(
                actor_id=claim.customer_id,
                route='/messages',
                key='duplicate-client-key',
                request_fingerprint='fingerprint',
                claim_id=claim.claim_id,
                session_id=session.session_id,
                message_id=duplicate.message_id,
            ),
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.find_idempotency(claim.customer_id, '/messages', 'duplicate-client-key') is None
    )


def test_session_mutation_checks_identity_inside_mutation_boundary(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    original_session = _session(claim)
    repository.create_claim(claim, original_session)
    replacement_claim = claim.model_copy(
        update={'revision': 2, 'active_session_id': 'ses_mongo_replacement'}
    )
    replacement_session = original_session.model_copy(
        update={'session_id': 'ses_mongo_replacement', 'context_revision': 1}
    )
    repository._collection.update_one(
        {'_id': repository._record_id('claim', claim.claim_id)},
        {'$set': {'active_session_id': replacement_session.session_id}},
    )
    repository._collection.insert_one(
        {
            **replacement_session.model_dump(mode='json'),
            '_id': repository._record_id('session', replacement_session.session_id),
            'record_type': 'session',
            'claim_id': claim.claim_id,
            'customer_id': claim.customer_id,
        }
    )
    existing_session = repository._collection.find_one(
        {'_id': repository._record_id('session', replacement_session.session_id)}
    )
    from backend.repositories.protocols import IdempotencyRecord

    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))
    with pytest.raises(IdempotencyConflict):
        repository.save_session_mutation(
            replacement_claim,
            expected_revision=1,
            session=replacement_session,
            idempotency=IdempotencyRecord(
                actor_id=claim.customer_id,
                route='/sessions',
                key='mutation-key',
                request_fingerprint='fingerprint',
                claim_id=claim.claim_id,
                session_id=replacement_session.session_id,
            ),
        )
    assert (
        repository._collection.find_one(
            {'_id': repository._record_id('session', replacement_session.session_id)}
        )
        == existing_session
    )
    assert repository.get_claim(claim.claim_id, claim.customer_id) is not None
    assert repository.find_idempotency(claim.customer_id, '/sessions', 'mutation-key') is None


def test_message_decision_and_evidence_round_trips_preserve_ownership(
    repository: MongoDBRepository,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session)
    decision = _decision(claim, session, message)
    evidence = _evidence(claim)

    repository.save_message(message, claim.customer_id)
    repository.save_agent_decision(decision, claim.customer_id)
    repository.save_evidence(evidence, claim.customer_id)

    assert (
        repository.get_message(
            claim.claim_id, session.session_id, message.message_id, claim.customer_id
        )
        == message
    )
    assert (
        repository.find_message_by_client_id(
            claim.claim_id, message.client_message_id or '', claim.customer_id
        )
        == message
    )
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == [
        message
    ]
    assert (
        repository.find_agent_decision_for_trigger(
            claim.claim_id, message.message_id, claim.customer_id
        )
        == decision
    )
    assert repository.list_agent_decisions(claim.claim_id, claim.customer_id) == [decision]
    assert (
        repository.get_evidence(claim.claim_id, evidence.evidence_id, claim.customer_id) == evidence
    )
    assert repository.list_evidence(claim.claim_id, claim.customer_id) == [evidence]
    assert repository.list_messages(claim.claim_id, session.session_id, 'other-customer') == []
    assert repository.list_agent_decisions(claim.claim_id, 'other-customer') == []
    assert repository.list_evidence(claim.claim_id, 'other-customer') == []


def test_message_mutation_is_revision_checked_before_child_writes(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session)
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})
    from backend.repositories.protocols import IdempotencyRecord

    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/messages',
        key='message-mutation',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=message.message_id,
    )
    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))
    repository.save_message_mutation(updated_claim, 1, updated_session, message, idempotency)
    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert (
        repository.get_message(
            claim.claim_id, session.session_id, message.message_id, claim.customer_id
        )
        == message
    )

    retry = message.model_copy(update={'message_id': 'msg_mongo_retry'})
    with pytest.raises(RevisionConflict):
        repository.save_message_mutation(
            updated_claim.model_copy(update={'revision': 2}),
            1,
            updated_session,
            retry,
            idempotency.__class__(
                **{**idempotency.__dict__, 'key': 'stale-key', 'message_id': retry.message_id}
            ),
        )
    assert (
        repository.get_message(
            claim.claim_id, session.session_id, retry.message_id, claim.customer_id
        )
        is None
    )


def test_evidence_mutation_rejects_stale_revision_without_partial_write(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    from backend.repositories.protocols import IdempotencyRecord

    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))
    stale_claim = claim.model_copy(update={'revision': 3})
    evidence = _evidence(claim)
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/evidence',
        key='evidence-key',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )

    with pytest.raises(RevisionConflict):
        repository.save_evidence_mutation(stale_claim, 2, evidence, idempotency)
    assert repository.get_evidence(claim.claim_id, evidence.evidence_id, claim.customer_id) is None
    assert (
        repository.find_idempotency(idempotency.actor_id, idempotency.route, idempotency.key)
        is None
    )


def test_retrieval_bundle_preserves_sources_and_rejects_conflicting_replay(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    retrieval = _retrieval(claim)
    signal = ReviewSignalRecord(
        signal_id='sig_mongo_001',
        claim_id=claim.claim_id,
        code='POLICY_REVIEW_REQUIRED',
        source_refs=[retrieval.retrieval_id],
        reason_codes=['POLICY_DETAIL_REQUIRES_STAFF'],
        summary='A staff member should review the policy detail.',
        created_at=claim.created_at,
    )
    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))

    repository.save_retrieval_bundle(retrieval, [signal], claim.customer_id)
    assert repository.list_retrieval_records(claim.claim_id, claim.customer_id) == [retrieval]
    assert repository.list_review_signals(claim.claim_id, claim.customer_id) == [signal]
    assert repository.list_retrieval_records(claim.claim_id, 'other-customer') == []

    changed = retrieval.model_copy(
        update={'facts': retrieval.facts.model_copy(update={'excess_amount': 900})}
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_retrieval_bundle(changed, [signal], claim.customer_id)
    assert repository.list_retrieval_records(claim.claim_id, claim.customer_id) == [retrieval]


def test_staff_mutation_persists_audited_record_with_claim_revision(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    action = StaffActionRecord(
        action_id='act_mongo_001',
        claim_id=claim.claim_id,
        action_type='review_claim',
        status=StaffActionStatus.OPEN,
        assigned_to='staff-001',
        requested_outcome='Review the collected FNOL information.',
        created_at=claim.created_at,
    )
    from backend.repositories.protocols import IdempotencyRecord

    idempotency = IdempotencyRecord(
        actor_id='staff-001',
        route='/staff-actions',
        key='staff-action-key',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )
    updated_claim = claim.model_copy(update={'revision': 2})
    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))

    repository.save_staff_mutation(
        updated_claim,
        1,
        idempotency,
        staff_action=action,
    )
    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert repository.get_staff_action(claim.claim_id, action.action_id) == action
    assert repository.list_staff_actions(claim.claim_id) == [action]


@pytest.mark.parametrize('invalid_session', ['foreign', 'missing'])
def test_staff_message_mutation_rejects_invalid_parent_session_without_writes(
    repository: MongoDBRepository,
    invalid_session: str,
) -> None:
    from backend.repositories.protocols import IdempotencyRecord

    claim = _claim()
    own_session = _session(claim)
    repository.create_claim(claim, own_session)
    foreign_claim = claim.model_copy(
        update={
            'claim_id': 'clm_mongo_foreign',
            'customer_id': 'cus_mongo_foreign',
            'active_session_id': 'ses_mongo_foreign',
        }
    )
    foreign_session = _session(foreign_claim).model_copy(
        update={
            'session_id': 'ses_mongo_foreign',
            'claim_id': foreign_claim.claim_id,
            'customer_id': foreign_claim.customer_id,
        }
    )
    repository.create_claim(foreign_claim, foreign_session)
    referenced_session_id = (
        foreign_session.session_id if invalid_session == 'foreign' else 'ses_mongo_missing'
    )
    message = _message(claim, own_session).model_copy(
        update={
            'message_id': f'msg_staff_{invalid_session}',
            'session_id': referenced_session_id,
            'client_message_id': None,
            'actor': ActorType.STAFF,
        }
    )
    idempotency = IdempotencyRecord(
        actor_id='stf_mongo_001',
        route='/staff-messages',
        key=f'staff-message-{invalid_session}',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=message.session_id,
        message_id=message.message_id,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            1,
            idempotency,
            message=message,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(claim.claim_id, own_session.session_id, claim.customer_id)
        == own_session
    )
    assert (
        repository.get_session(
            foreign_claim.claim_id,
            foreign_session.session_id,
            foreign_claim.customer_id,
        )
        == foreign_session
    )
    assert (
        repository.get_message(
            claim.claim_id,
            message.session_id,
            message.message_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.find_idempotency(idempotency.actor_id, idempotency.route, idempotency.key)
        is None
    )


@pytest.mark.parametrize('invalid_link', ['session_id', 'message_id'])
def test_staff_message_mutation_rejects_invalid_idempotency_link_without_writes(
    repository: MongoDBRepository,
    invalid_link: str,
) -> None:
    from backend.repositories.protocols import IdempotencyRecord

    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session).model_copy(
        update={'client_message_id': None, 'actor': ActorType.STAFF}
    )
    values = {
        'session_id': session.session_id,
        'message_id': message.message_id,
    }
    values[invalid_link] = f'wrong-{invalid_link}'
    idempotency = IdempotencyRecord(
        actor_id='stf_mongo_001',
        route='/staff-messages',
        key=f'staff-message-wrong-{invalid_link}',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=values['session_id'],
        message_id=values['message_id'],
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            1,
            idempotency,
            message=message,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.get_session(claim.claim_id, session.session_id, claim.customer_id) == session
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(idempotency.actor_id, idempotency.route, idempotency.key)
        is None
    )


def test_staff_message_mutation_rejects_agent_message_alias_without_writes(
    repository: MongoDBRepository,
) -> None:
    from backend.repositories.protocols import IdempotencyRecord

    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    message = _message(claim, session).model_copy(
        update={'client_message_id': None, 'actor': ActorType.STAFF}
    )
    idempotency = IdempotencyRecord(
        actor_id='stf_mongo_001',
        route='/staff-messages',
        key='staff-message-agent-alias',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id='wrong-message',
        agent_message_id=message.message_id,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            1,
            idempotency,
            message=message,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(idempotency.actor_id, idempotency.route, idempotency.key)
        is None
    )


def test_agent_turn_persists_linked_records_as_one_mutation(
    repository: MongoDBRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})
    claimant_message = _message(claim, session)
    agent_message = claimant_message.model_copy(
        update={
            'message_id': 'msg_mongo_agent',
            'client_message_id': None,
            'actor': ActorType.AGENT,
            'content': {'type': 'text', 'text': 'Please confirm the incident.'},
            'in_reply_to': claimant_message.message_id,
        }
    )
    decision = _decision(updated_claim, updated_session, claimant_message)
    from backend.repositories.protocols import IdempotencyRecord

    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/agent-turn',
        key='agent-turn-key',
        request_fingerprint='fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )
    monkeypatch.setattr(repository, '_atomic', lambda operation: operation(None))

    repository.save_agent_turn(
        updated_claim,
        1,
        updated_session,
        claimant_message,
        agent_message,
        decision,
        idempotency,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert repository.list_messages(claim.claim_id, session.session_id, claim.customer_id) == [
        claimant_message,
        agent_message,
    ]
    assert (
        repository.get_agent_decision(claim.claim_id, decision.decision_id, claim.customer_id)
        == decision
    )
