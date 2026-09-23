"""The #984 durable ExternalTask attempt contract for both repositories."""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from backend.domain.external_services import (
    ASSESSOR_REQUESTED_ACTION,
    ASSESSOR_SERVICE_IDENTITY,
    ExternalTaskAttempt,
    ExternalTaskAuthorisation,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskRequest,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    Channel,
    ClaimState,
    CustomerNextStep,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.domain.runtime import ExternalServiceOfferMetadata
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository
from backend.services.external_capability_dispatcher import (
    ExternalCapabilityDispatcher,
    ExternalCapabilityResult,
)
from backend.services.external_service_offers import _dispatch_generic_offer
from backend.services.workbench import _external_requests

CUSTOMER = 'cus_attempt_001'
CLAIM = 'clm_attempt_001'
TASK = 'tsk_attempt_001'
REQUEST = 'erq_attempt_001'
OPERATION = 'op_attempt_001'
BASE = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _claim() -> WorkingClaim:
    consent = ExternalServiceConsent(
        consent_ref='consent_attempt_001',
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        permitted_fields=['claim_id', 'location.region'],
        status=ExternalServiceConsentStatus.GRANTED,
        granted_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=CUSTOMER),
        granted_at=BASE,
    )
    return WorkingClaim(
        claim_id=CLAIM,
        customer_id=CUSTOMER,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_attempt_001',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        external_service_consents=[consent],
        created_at=BASE,
        updated_at=BASE,
    )


def _session(claim: WorkingClaim) -> SessionRecord:
    return SessionRecord(
        session_id=claim.active_session_id or 'ses_attempt_001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=BASE,
        last_active_at=BASE,
        status=SessionStatus.ACTIVE,
    )


def _decision(claim: WorkingClaim) -> AgentDecisionRecord:
    return AgentDecisionRecord(
        decision_id='dec_attempt_001',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or 'ses_attempt_001',
        trigger_message_id='msg_attempt_001',
        action=AgentAction.PROCEED,
        reason_codes=['EXTERNAL_SERVICE_OFFER_AUTHORISED'],
        customer_reason='The claimant authorised the registered service.',
        customer_response='The request is ready.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='agent',
            validated_by='rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=claim.revision,
        created_at=BASE,
    )


def _task(
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.ACCEPTED,
) -> ExternalTaskRecord:
    submitted = status is ExternalTaskOperationStatus.ACCEPTED
    return ExternalTaskRecord(
        task_id=TASK,
        claim_id=CLAIM,
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        delivery=ExternalTaskDelivery.SUBMITTED
        if submitted
        else ExternalTaskDelivery.NOT_SUBMITTED,
        delivery_evidence='fixture-delivery-001' if submitted else None,
        provider_reference='provider-attempt-001' if submitted else None,
        created_at=BASE,
        updated_at=BASE + timedelta(seconds=1),
    )


def _request() -> ExternalTaskRequest:
    return ExternalTaskRequest(
        request_id=REQUEST,
        task_id=TASK,
        claim_id=CLAIM,
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        purpose='Request a vehicle damage assessment.',
        disclosed_fields=['claim_id', 'location.region'],
        authorisation=ExternalTaskAuthorisation(
            northwind_authority_ref='dec_attempt_001',
            claimant_consent_ref='consent_attempt_001',
            authorised_revision=1,
        ),
        prepared_at=BASE,
        sent_at=BASE + timedelta(seconds=2),
        operation_id=OPERATION,
    )


def _attempt(
    *,
    attempt_id: str = 'att_attempt_001',
    attempt_number: int = 1,
    outcome: ExternalTaskOperationStatus = ExternalTaskOperationStatus.ACCEPTED,
    failure_code: ExternalTaskFailureCode | None = None,
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.SUBMITTED,
) -> ExternalTaskAttempt:
    return ExternalTaskAttempt(
        attempt_id=attempt_id,
        task_id=TASK,
        claim_id=CLAIM,
        operation_id=OPERATION,
        attempt_number=attempt_number,
        claim_revision=1,
        started_at=BASE + timedelta(seconds=2),
        outcome=outcome,
        failure_code=failure_code,
        delivery=delivery,
        delivery_evidence='fixture-delivery-001'
        if delivery is ExternalTaskDelivery.SUBMITTED
        else None,
    )


def _seed(repository: PersistenceRepository) -> None:
    claim = _claim()
    session = _session(claim)
    repository.create_claim(claim, session)
    repository.save_message(
        MessageRecord(
            message_id='msg_attempt_001',
            claim_id=CLAIM,
            session_id=session.session_id,
            client_message_id='client-attempt-001',
            actor=ActorType.CLAIMANT,
            visibility=MessageVisibility.CLAIMANT_VISIBLE,
            content={'type': 'text', 'text': 'Please request the assessment.'},
            created_at=BASE,
        ),
        CUSTOMER,
    )
    repository.save_agent_decision(_decision(claim), CUSTOMER)
    repository.save_external_task(_task(), CUSTOMER)
    repository.save_external_task_request(_request(), CUSTOMER)


@pytest.fixture(params=['fixture', 'mongodb'])
def repository(request: pytest.FixtureRequest) -> Iterator[PersistenceRepository]:
    if request.param == 'fixture':
        yield FixtureRepository()
        return
    store = MongoDBRepository(mongomock.MongoClient(), 'northwind_attempt_test')
    store._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    yield store


def test_attempts_are_append_only_idempotent_and_contiguous(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    first = _attempt()
    repository.save_external_task_attempt(first, CUSTOMER)
    repository.save_external_task_attempt(first, CUSTOMER)
    assert repository.list_external_task_attempts_internal(CLAIM) == [first]

    second = _attempt(
        attempt_id='att_attempt_002',
        attempt_number=2,
        outcome=ExternalTaskOperationStatus.TERMINAL_FAILURE,
        failure_code=ExternalTaskFailureCode.MALFORMED,
        delivery=ExternalTaskDelivery.NOT_SUBMITTED,
    )
    repository.save_external_task_attempt(second, CUSTOMER)
    assert [
        item.attempt_number for item in repository.list_external_task_attempts_internal(CLAIM)
    ] == [1, 2]

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_attempt(
            second.model_copy(update={'failure_code': ExternalTaskFailureCode.ACCESS_DENIED}),
            CUSTOMER,
        )
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_attempt(
            _attempt(attempt_id='att_attempt_004', attempt_number=4), CUSTOMER
        )


def test_unknown_outcome_survives_readback_and_is_not_success(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    unknown = _attempt(
        outcome=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
        failure_code=ExternalTaskFailureCode.TIMEOUT,
    )
    repository.save_external_task_attempt(unknown, CUSTOMER)
    reloaded = repository.list_external_task_attempts_internal(CLAIM)
    assert reloaded[0].outcome is ExternalTaskOperationStatus.UNKNOWN_OUTCOME


def test_attempt_requires_claim_task_request_and_operation_identity(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    with pytest.raises(KeyError):
        repository.save_external_task_attempt(
            _attempt().model_copy(update={'claim_id': 'clm_other'}), CUSTOMER
        )
    with pytest.raises(KeyError):
        repository.save_external_task_attempt(
            _attempt().model_copy(update={'operation_id': 'op_other'}), CUSTOMER
        )


def test_fixture_rejects_missing_task_and_request_before_appending() -> None:
    repository = FixtureRepository()
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    with pytest.raises(KeyError):
        repository.save_external_task_attempt(_attempt(), CUSTOMER)

    repository.save_external_task(_task(), CUSTOMER)
    with pytest.raises(KeyError):
        repository.save_external_task_attempt(_attempt(), CUSTOMER)


def test_fixture_rejects_duplicate_attempt_number_even_with_a_new_id() -> None:
    repository = FixtureRepository()
    _seed(repository)
    repository.save_external_task_attempt(_attempt(), CUSTOMER)
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_attempt(
            _attempt(attempt_id='att_attempt_same-number'), CUSTOMER
        )


def test_mongodb_duplicate_insert_replays_the_matching_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_attempt_race')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    _seed(repository)
    attempt = _attempt()
    original = repository._collection.insert_one

    def insert_then_race(document: dict[str, Any], *, session: Any = None) -> Any:
        original(document, session=session)
        raise DuplicateKeyError('simulated concurrent winner')

    monkeypatch.setattr(repository._collection, 'insert_one', insert_then_race)
    repository.save_external_task_attempt(attempt, CUSTOMER)


def test_mongodb_duplicate_insert_rejects_a_different_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_attempt_race_conflict')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    _seed(repository)
    attempt = _attempt()
    winner = attempt.model_copy(
        update={
            'outcome': ExternalTaskOperationStatus.TERMINAL_FAILURE,
            'failure_code': ExternalTaskFailureCode.MALFORMED,
            'delivery': ExternalTaskDelivery.NOT_SUBMITTED,
            'delivery_evidence': None,
        }
    )
    original = repository._collection.insert_one

    def insert_different_winner(document: dict[str, Any], *, session: Any = None) -> Any:
        original(
            winner.model_dump(mode='json')
            | {
                '_id': repository._record_id('external_task_attempt', winner.attempt_id),
                'record_type': 'external_task_attempt',
                'customer_id': CUSTOMER,
                'claim_id': CLAIM,
            },
            session=session,
        )
        raise DuplicateKeyError('simulated concurrent winner')

    monkeypatch.setattr(repository._collection, 'insert_one', insert_different_winner)
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_attempt(attempt, CUSTOMER)


class _GenericDispatcher(ExternalCapabilityDispatcher):
    def __init__(self, status: str) -> None:
        self.status = status

    def execute(
        self,
        service_identity: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        product_family: str,
    ) -> ExternalCapabilityResult:
        del operation, payload, product_family
        return ExternalCapabilityResult(
            status=self.status,
            service_identity=service_identity,
            registry_version='external-service-lifecycle.v1',
            access_form='controlled recovery request',
            uses_external_task=True,
            payload={'provider_reference': 'provider-generic-001'}
            if self.status == 'accepted'
            else {},
            next_action='recorded',
        )


class _RaisingDispatcher(ExternalCapabilityDispatcher):
    def execute(
        self,
        service_identity: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        product_family: str,
    ) -> ExternalCapabilityResult:
        del service_identity, operation, payload, product_family
        raise RuntimeError('simulated provider outage')


def _generic_claim() -> tuple[WorkingClaim, ExternalServiceConsent, ExternalServiceOfferMetadata]:
    consent = (
        _claim()
        .external_service_consents[0]
        .model_copy(
            update={
                'service_identity': 'vehicle_recovery_request',
                'requested_action': 'request_vehicle_recovery',
                'consent_ref': 'consent_recovery_001',
                'offer_ref': 'offer_recovery_001',
                'permitted_fields': ['incident.location'],
            }
        )
    )
    claim = _claim().model_copy(update={'external_service_consents': [consent]})
    offer = ExternalServiceOfferMetadata(
        offer_id='offer_recovery_001',
        agent_message_id='msg_attempt_001',
        trigger_message_id='msg_attempt_001',
        service_identity='vehicle_recovery_request',
        registry_version='external-service-lifecycle.v1',
        requested_action='request_vehicle_recovery',
        disclosure_fields=['incident.location'],
        evidence_ids=[],
        disclosure_manifest=['Incident location'],
        disclosure_fingerprint='fingerprint',
    )
    return claim, consent, offer


@pytest.mark.parametrize(
    'status, expected',
    [
        ('unavailable', ExternalTaskOperationStatus.RETRYABLE_FAILURE),
        ('rejected', ExternalTaskOperationStatus.TERMINAL_FAILURE),
        ('accepted', ExternalTaskOperationStatus.ACCEPTED),
    ],
)
def test_generic_dispatch_persists_each_provider_outcome(
    status: str,
    expected: ExternalTaskOperationStatus,
) -> None:
    repository = FixtureRepository()
    claim, consent, offer = _generic_claim()
    repository.create_claim(claim, _session(claim))
    _dispatch_generic_offer(repository, claim, consent, offer, _GenericDispatcher(status))
    tasks = repository.list_external_tasks_internal(CLAIM)
    assert tasks[0].status is expected
    attempts = repository.list_external_task_attempts_internal(CLAIM)
    assert len(attempts) == 1
    assert attempts[0].outcome is expected


def test_generic_dispatch_exception_persists_retryable_attempt() -> None:
    repository = FixtureRepository()
    claim, consent, offer = _generic_claim()
    repository.create_claim(claim, _session(claim))
    _dispatch_generic_offer(repository, claim, consent, offer, _RaisingDispatcher())

    tasks = repository.list_external_tasks_internal(CLAIM)
    attempts = repository.list_external_task_attempts_internal(CLAIM)
    assert tasks[0].status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert len(attempts) == 1
    assert attempts[0].outcome is ExternalTaskOperationStatus.RETRYABLE_FAILURE


def test_generic_settlement_rolls_back_task_when_attempt_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    _seed(repository)
    task = _task()
    attempt = _attempt()
    original = repository.save_external_task_attempt

    def fail_once(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError('simulated attempt persistence failure')

    monkeypatch.setattr(repository, 'save_external_task_attempt', fail_once)
    with pytest.raises(RuntimeError, match='simulated attempt persistence failure'):
        repository.save_external_task_settlement(task, attempt, CUSTOMER)

    assert repository.list_external_task_attempts_internal(CLAIM) == []
    assert repository.list_external_tasks_internal(CLAIM)[0] == _task()

    monkeypatch.setattr(repository, 'save_external_task_attempt', original)
    repository.save_external_task_settlement(task, attempt, CUSTOMER)
    repository.save_external_task_settlement(task, attempt, CUSTOMER)
    assert repository.list_external_task_attempts_internal(CLAIM) == [attempt]


def test_workbench_projection_returns_attempts_in_sequence_order() -> None:
    claim = _claim()
    task = _task()
    request = _request()
    attempts = [
        _attempt(attempt_id='att_attempt_002', attempt_number=2),
        _attempt(attempt_id='att_attempt_001', attempt_number=1),
    ]
    projected = _external_requests(
        claim,
        [task],
        attempts,
        [request],
        [],
        [],
        [],
    )
    assert [item.attempt_number for item in projected[0].attempts] == [1, 2]
    assert projected[0].attempts[0].operation_id == OPERATION
