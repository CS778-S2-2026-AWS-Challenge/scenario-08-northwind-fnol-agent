from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from backend.domain.external_service_registry import (
    ExternalLifecycleStatus,
    ExternalServiceLifecycleProjection,
    ExternalTaskResultVerification,
)
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskResult,
)
from backend.domain.models import AssessorRoutingResult, AssessorRoutingStatus, IntegrationSource
from backend.domain.retrieval import RetrievalSource
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent_external_lifecycle import (
    MAX_EXTERNAL_LIFECYCLE_PROJECTIONS,
    ExternalLifecycleContextError,
    ExternalLifecycleContextUnavailable,
    build_agent_external_lifecycle_context,
)

CLAIM_ID = 'clm_lifecycle_context'
CREATED_AT = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


class _Repository:
    def __init__(self, tasks: list[ExternalTaskRecord], results: list[ExternalTaskResult]):
        self.tasks = tasks
        self.results = results

    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        return [task for task in self.tasks if task.claim_id == claim_id]

    def list_external_task_results_internal(self, claim_id: str) -> list[ExternalTaskResult]:
        return [result for result in self.results if result.claim_id == claim_id]


class _UnavailableRepository(_Repository):
    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        raise RuntimeError('synthetic persistence outage')


def _task(
    task_id: str = 'task-1',
    *,
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.ACCEPTED,
    service_identity: str = 'vehicle_damage_assessment_routing',
    integration_source: IntegrationSource = IntegrationSource.FIXTURE,
) -> ExternalTaskRecord:
    timestamp = CREATED_AT + timedelta(minutes=int(task_id.split('-')[-1]))
    values: dict[str, object] = {}
    if status is ExternalTaskOperationStatus.ACCEPTED:
        values.update(
            delivery=ExternalTaskDelivery.SUBMITTED,
            delivery_evidence='fixture acknowledgement',
            provider_reference=f'provider-{task_id}',
        )
    elif status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        values.update(
            delivery=ExternalTaskDelivery.SUBMITTED,
            delivery_evidence='fixture timeout after send',
            failure_code=ExternalTaskFailureCode.TIMEOUT,
        )
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=CLAIM_ID,
        service_identity=service_identity,
        requested_action='vehicle_damage_assessment',
        integration_source=integration_source,
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        **values,
    )


def _result(
    task_id: str = 'task-1',
    *,
    result_id: str = 'result-1',
    verification: ExternalTaskResultVerification = ExternalTaskResultVerification.UNVERIFIED,
    received_at: datetime = CREATED_AT + timedelta(minutes=10),
) -> ExternalTaskResult:
    verified = verification is not ExternalTaskResultVerification.UNVERIFIED
    return ExternalTaskResult(
        result_id=result_id,
        task_id=task_id,
        claim_id=CLAIM_ID,
        source=RetrievalSource(
            system='fixture', reference='provider-result', retrieved_at=received_at
        ),
        summary='Assessment result received.',
        verification=verification,
        verified_at=received_at + timedelta(minutes=1) if verified else None,
        verified_against_revision=1 if verified else None,
        received_at=received_at,
    )


def _context(
    tasks: list[ExternalTaskRecord],
    results: list[ExternalTaskResult],
    assessor_routing: AssessorRoutingResult | None = None,
) -> tuple[ExternalServiceLifecycleProjection, ...]:
    return build_agent_external_lifecycle_context(
        cast(PersistenceRepository, _Repository(tasks, results)),
        CLAIM_ID,
        assessor_routing,
    )


def test_empty_claim_has_no_external_context() -> None:
    assert _context([], []) == ()


def test_projection_keeps_operation_and_result_status_separate() -> None:
    task = _task(status=ExternalTaskOperationStatus.ACCEPTED)
    projection = _context([task], [_result()])[0]

    assert projection.operation_status is ExternalLifecycleStatus.ACCEPTED
    assert projection.result_status is ExternalLifecycleStatus.RESULT_RECEIVED
    assert projection.provenance.value == 'simulated'
    assert projection.registry_version == 'external-service-lifecycle.v1'


def test_verified_result_is_not_claim_completion() -> None:
    task = _task()
    projection = _context(
        [task], [_result(verification=ExternalTaskResultVerification.CONSISTENT)]
    )[0]

    assert projection.result_status is ExternalLifecycleStatus.RESULT_VERIFIED
    assert projection.operation_status is ExternalLifecycleStatus.ACCEPTED
    assert projection.operation_status.value != ExternalLifecycleStatus.WRITTEN_BACK.value
    assert projection.status_label == 'Result checked'
    assert projection.pending_owner == 'claims_professional'


@pytest.mark.parametrize(
    'routing_status', [AssessorRoutingStatus.QUEUED, AssessorRoutingStatus.ASSIGNED]
)
def test_projection_includes_reference_matched_assessor_progress(
    routing_status: AssessorRoutingStatus,
) -> None:
    task = _task()
    provider_reference = task.provider_reference
    assert provider_reference is not None
    routing = AssessorRoutingResult(
        routing_status=routing_status,
        assessor_reference=(
            provider_reference if routing_status is AssessorRoutingStatus.ASSIGNED else None
        ),
        queue_reference=(
            provider_reference if routing_status is AssessorRoutingStatus.QUEUED else 'queue-1'
        ),
        next_step='Await the simulated assessment.',
    )

    projection = _context([task], [], routing)[0]

    assert projection.operation_status.value == routing_status.value


def test_non_matching_assessor_progress_leaves_acknowledgement_unchanged() -> None:
    routing = AssessorRoutingResult(
        routing_status=AssessorRoutingStatus.ASSIGNED,
        assessor_reference='another-task-reference',
        queue_reference='queue-1',
        next_step='Await the simulated assessment.',
    )

    projection = _context([_task()], [], routing)[0]

    assert projection.operation_status is ExternalLifecycleStatus.ACCEPTED


@pytest.mark.parametrize(
    'verification',
    [
        ExternalTaskResultVerification.CONSISTENT,
        ExternalTaskResultVerification.INCONSISTENT,
        ExternalTaskResultVerification.REVIEW_REQUIRED,
    ],
)
def test_checked_result_preserves_its_verification_outcome(
    verification: ExternalTaskResultVerification,
) -> None:
    projection = _context([_task()], [_result(verification=verification)])[0]

    assert projection.result_status is ExternalLifecycleStatus.RESULT_VERIFIED
    assert projection.result_verification is verification


def test_unknown_outcome_requires_reconciliation() -> None:
    projection = _context([_task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)], [])[0]

    assert projection.operation_status is ExternalLifecycleStatus.UNKNOWN_OUTCOME
    assert projection.requires_reconciliation is True


def test_unregistered_service_fails_closed() -> None:
    with pytest.raises(ExternalLifecycleContextError, match='no canonical registry entry'):
        _context([_task(service_identity='unregistered-provider')], [])


def test_task_source_must_match_registered_capability_provenance() -> None:
    with pytest.raises(ExternalLifecycleContextError, match='registry provenance'):
        _context([_task(integration_source=IntegrationSource.CONFIGURED_SERVICE)], [])


def test_result_for_another_task_fails_closed() -> None:
    with pytest.raises(ExternalLifecycleContextError, match='not linked to a task'):
        _context([_task()], [_result(task_id='task-2')])


def test_result_on_task_that_cannot_have_one_fails_closed() -> None:
    with pytest.raises(ExternalLifecycleContextError, match='cannot carry a result'):
        _context(
            [_task(status=ExternalTaskOperationStatus.PREPARED)],
            [_result()],
        )


def test_duplicate_result_for_one_task_fails_closed() -> None:
    with pytest.raises(ExternalLifecycleContextError, match='more than one external result'):
        _context(
            [_task()],
            [
                _result(),
                _result(result_id='result-2', received_at=CREATED_AT + timedelta(minutes=20)),
            ],
        )


def test_context_accepts_the_exact_bounded_task_limit() -> None:
    tasks = [_task(f'task-{index}') for index in range(1, 9)]
    projections = _context(tasks, [])

    assert len(projections) == MAX_EXTERNAL_LIFECYCLE_PROJECTIONS


def test_context_overflow_fails_instead_of_dropping_external_tasks() -> None:
    tasks = [_task(f'task-{index}') for index in range(1, 10)]

    with pytest.raises(ExternalLifecycleContextError, match='Agent context limit is 8'):
        _context(tasks, [])


def test_repository_read_failure_is_retryable_and_bounded() -> None:
    with pytest.raises(ExternalLifecycleContextUnavailable) as caught:
        build_agent_external_lifecycle_context(
            cast(PersistenceRepository, _UnavailableRepository([], [])),
            CLAIM_ID,
        )

    assert caught.value.retryable is True
