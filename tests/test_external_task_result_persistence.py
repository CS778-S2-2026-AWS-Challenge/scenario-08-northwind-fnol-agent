"""The returned-result persistence contract, asserted against both repositories.

`ExternalTaskResult` records what a third party actually returned, which is a
different thing from the acknowledgement that a request reached it. These tests hold
both implementations to one behaviour, because a rule enforced in the fixture and not
in MongoDB is a rule that disappears the moment the runtime profile changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest

from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskEvidenceLink,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskResult,
    ExternalTaskResultVerification,
)
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    IntegrationSource,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalSource
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository

CUSTOMER = 'cus_result_001'
CLAIM = 'clm_result_001'
TASK = 'tsk_result_001'
EVIDENCE = 'evd_result_001'
BASE = datetime(2026, 9, 8, tzinfo=UTC)


def _claim() -> WorkingClaim:
    return WorkingClaim(
        claim_id=CLAIM,
        customer_id=CUSTOMER,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_result_001',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=BASE,
        updated_at=BASE,
    )


def _session(claim: WorkingClaim) -> SessionRecord:
    return SessionRecord(
        session_id='ses_result_001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=claim.created_at,
        last_active_at=claim.created_at,
        status=SessionStatus.ACTIVE,
    )


def _task(
    *,
    task_id: str = TASK,
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.SUBMITTED,
) -> ExternalTaskRecord:
    submitted = delivery is ExternalTaskDelivery.SUBMITTED
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=CLAIM,
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        integration_source=IntegrationSource.FIXTURE,
        status=(
            ExternalTaskOperationStatus.ACCEPTED
            if submitted
            else ExternalTaskOperationStatus.PREPARED
        ),
        delivery=delivery,
        delivery_evidence='fixture acknowledgement' if submitted else None,
        provider_reference='sim_assessor_abc123' if submitted else None,
        created_at=BASE,
        updated_at=BASE,
    )


def _evidence() -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=EVIDENCE,
        claim_id=CLAIM,
        kind='assessment_report',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.EXTERNAL_SYSTEM,
        created_at=BASE,
        updated_at=BASE,
    )


def _link(task_id: str = TASK, evidence_id: str = EVIDENCE) -> ExternalTaskEvidenceLink:
    return ExternalTaskEvidenceLink(
        task_id=task_id,
        evidence_id=evidence_id,
        claim_id=CLAIM,
        linked_at=BASE,
    )


def _result(**overrides: Any) -> ExternalTaskResult:
    values: dict[str, Any] = {
        'result_id': 'res_result_001',
        'task_id': TASK,
        'claim_id': CLAIM,
        'source': RetrievalSource(
            system='controlled_assessment_fixture',
            reference='report/assessment-001',
            retrieved_at=BASE,
        ),
        'summary': 'The assessor reported the vehicle repairable with a revised parts list.',
        'received_at': BASE,
    }
    values.update(overrides)
    return ExternalTaskResult(**values)


def _seed(repository: PersistenceRepository) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    repository.save_external_task(_task(), CUSTOMER)
    repository.save_evidence(_evidence(), CUSTOMER)
    repository.save_external_task_evidence_link(_link(), CUSTOMER)


@pytest.fixture(params=['fixture', 'mongodb'])
def repository(request: pytest.FixtureRequest) -> Iterator[PersistenceRepository]:
    """Yield each implementation of the shared persistence contract in turn."""

    if request.param == 'fixture':
        yield FixtureRepository()
        return
    store = MongoDBRepository(mongomock.MongoClient(), 'northwind_result_test')
    store._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    yield store


def test_a_returned_result_is_ingested_and_read_back(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    result = _result(evidence_ids=[EVIDENCE])

    repository.save_external_task_result(result, CUSTOMER)

    stored = repository.list_external_task_results_internal(CLAIM)
    assert [item.result_id for item in stored] == ['res_result_001']
    assert stored[0].verification is ExternalTaskResultVerification.UNVERIFIED
    assert stored[0].verified_at is None
    assert stored[0].evidence_ids == [EVIDENCE]
    assert stored[0].source.reference == 'report/assessment-001'


def test_ingestion_is_idempotent_for_an_identical_write(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    result = _result(evidence_ids=[EVIDENCE])

    repository.save_external_task_result(result, CUSTOMER)
    repository.save_external_task_result(result, CUSTOMER)

    assert len(repository.list_external_task_results_internal(CLAIM)) == 1


def test_a_task_that_never_reached_the_provider_carries_no_result(
    repository: PersistenceRepository,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    repository.save_external_task(
        _task(task_id='tsk_unsent', delivery=ExternalTaskDelivery.NOT_SUBMITTED),
        CUSTOMER,
    )

    with pytest.raises(KeyError):
        repository.save_external_task_result(_result(task_id='tsk_unsent'), CUSTOMER)

    assert repository.list_external_task_results_internal(CLAIM) == []


def test_a_result_cannot_name_evidence_belonging_to_another_task(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task(_task(task_id='tsk_other'), CUSTOMER)
    other_evidence = _evidence().model_copy(update={'evidence_id': 'evd_other'})
    repository.save_evidence(other_evidence, CUSTOMER)
    repository.save_external_task_evidence_link(_link('tsk_other', 'evd_other'), CUSTOMER)

    with pytest.raises(KeyError):
        repository.save_external_task_result(_result(evidence_ids=['evd_other']), CUSTOMER)

    assert repository.list_external_task_results_internal(CLAIM) == []


def test_a_result_cannot_name_evidence_that_does_not_exist(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)

    with pytest.raises(KeyError):
        repository.save_external_task_result(_result(evidence_ids=['evd_absent']), CUSTOMER)


def test_a_second_result_cannot_be_added_to_one_task(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_result(_result(result_id='res_second'), CUSTOMER)

    assert [item.result_id for item in repository.list_external_task_results_internal(CLAIM)] == [
        'res_result_001'
    ]


@pytest.mark.parametrize(
    'change',
    [
        {'summary': 'A different account of what the provider said.'},
        {'received_at': BASE + timedelta(hours=1)},
        {
            'source': RetrievalSource(
                system='controlled_assessment_fixture',
                reference='report/assessment-002',
                retrieved_at=BASE,
            )
        },
    ],
)
def test_an_ingestion_fact_cannot_be_rewritten(
    repository: PersistenceRepository,
    change: dict[str, Any],
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_result(_result(**change), CUSTOMER)

    stored = repository.list_external_task_results_internal(CLAIM)
    assert stored[0].summary.startswith('The assessor reported')
    assert stored[0].received_at == BASE


def test_verification_advances_once_from_unverified(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)

    checked = _result(
        verification=ExternalTaskResultVerification.CONSISTENT,
        verified_at=BASE + timedelta(minutes=5),
        verified_against_revision=1,
    )
    repository.save_external_task_result(checked, CUSTOMER)

    stored = repository.list_external_task_results_internal(CLAIM)
    assert stored[0].verification is ExternalTaskResultVerification.CONSISTENT
    assert stored[0].verified_against_revision == 1


def test_a_recorded_verification_cannot_be_contradicted(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)
    repository.save_external_task_result(
        _result(
            verification=ExternalTaskResultVerification.CONSISTENT,
            verified_at=BASE + timedelta(minutes=5),
            verified_against_revision=1,
        ),
        CUSTOMER,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_result(
            _result(
                verification=ExternalTaskResultVerification.INCONSISTENT,
                verified_at=BASE + timedelta(minutes=9),
                verified_against_revision=1,
            ),
            CUSTOMER,
        )

    stored = repository.list_external_task_results_internal(CLAIM)
    assert stored[0].verification is ExternalTaskResultVerification.CONSISTENT


def test_a_verified_result_cannot_be_returned_to_unverified(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)
    repository.save_external_task_result(
        _result(
            verification=ExternalTaskResultVerification.REVIEW_REQUIRED,
            verified_at=BASE + timedelta(minutes=5),
            verified_against_revision=1,
        ),
        CUSTOMER,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_result(_result(), CUSTOMER)

    stored = repository.list_external_task_results_internal(CLAIM)
    assert stored[0].verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_a_result_needs_a_claim_the_customer_owns(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)

    with pytest.raises(KeyError):
        repository.save_external_task_result(_result(), 'cus_someone_else')


def test_results_read_back_in_a_stable_order(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task(_task(task_id='tsk_second'), CUSTOMER)
    repository.save_external_task_result(
        _result(result_id='res_late', task_id='tsk_second', received_at=BASE + timedelta(hours=2)),
        CUSTOMER,
    )
    repository.save_external_task_result(_result(), CUSTOMER)

    stored = repository.list_external_task_results_internal(CLAIM)
    assert [item.result_id for item in stored] == ['res_result_001', 'res_late']


def test_the_same_verification_cannot_be_restated_with_a_different_check(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)
    repository.save_external_task_result(_result(), CUSTOMER)
    checked = _result(
        verification=ExternalTaskResultVerification.CONSISTENT,
        verified_at=BASE + timedelta(minutes=5),
        verified_against_revision=1,
    )
    repository.save_external_task_result(checked, CUSTOMER)

    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_result(
            checked.model_copy(update={'verified_at': BASE + timedelta(minutes=30)}),
            CUSTOMER,
        )

    stored = repository.list_external_task_results_internal(CLAIM)
    assert stored[0].verified_at == BASE + timedelta(minutes=5)


def test_a_result_cannot_name_a_task_that_is_not_on_this_claim(
    repository: PersistenceRepository,
) -> None:
    _seed(repository)

    with pytest.raises(KeyError):
        repository.save_external_task_result(_result(task_id='tsk_absent'), CUSTOMER)

    assert repository.list_external_task_results_internal(CLAIM) == []
