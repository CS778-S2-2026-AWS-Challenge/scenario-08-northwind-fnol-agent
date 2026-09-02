from datetime import UTC, datetime

import pytest

from backend.domain.external_services import (
    ExternalTaskContinuation,
    ExternalTaskContinuationOutcome,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    TaskHasNotFailedError,
    classify_external_task_failure,
    continuation_for_failed_task,
)
from backend.domain.models import IntegrationSource

AT = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
EVIDENCE = 'transport-receipt-1'


def _failed_task(
    *,
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> ExternalTaskRecord:
    """Build the failed record the shared classification derives for this pair."""

    status = classify_external_task_failure(
        failure_code=failure_code,
        delivery=delivery,
    ).operation_status
    return ExternalTaskRecord(
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity=SERVICE,
        requested_action=ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        delivery=delivery,
        delivery_evidence=(EVIDENCE if delivery is ExternalTaskDelivery.SUBMITTED else None),
        failure_code=failure_code,
        created_at=AT,
        updated_at=AT,
    )


def _live_task(status: ExternalTaskOperationStatus) -> ExternalTaskRecord:
    accepted = status is ExternalTaskOperationStatus.ACCEPTED
    return ExternalTaskRecord(
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity=SERVICE,
        requested_action=ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        delivery=(
            ExternalTaskDelivery.SUBMITTED if accepted else ExternalTaskDelivery.NOT_SUBMITTED
        ),
        delivery_evidence=(EVIDENCE if accepted else None),
        failure_code=None,
        created_at=AT,
        updated_at=AT,
    )


@pytest.mark.parametrize(
    ('failure_code', 'delivery', 'continuation', 'permits_attempt'),
    [
        (
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE,
            True,
        ),
        (
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.AWAITING_RECONCILIATION,
            False,
        ),
        (
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE,
            True,
        ),
        (
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE,
            True,
        ),
        (
            ExternalTaskFailureCode.PARTIAL,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.AWAITING_RECONCILIATION,
            False,
        ),
        (
            ExternalTaskFailureCode.ACCESS_DENIED,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.AWAITING_REVIEW,
            False,
        ),
        (
            ExternalTaskFailureCode.MALFORMED,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.AWAITING_REVIEW,
            False,
        ),
        (
            ExternalTaskFailureCode.CONFLICTING,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskContinuation.AWAITING_REVIEW,
            False,
        ),
    ],
)
def test_the_recovery_path_decides_what_the_claimant_is_told(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
    continuation: ExternalTaskContinuation,
    permits_attempt: bool,
) -> None:
    """Every row of the recovery matrix reaches the claimant as one consistent answer."""

    outcome = continuation_for_failed_task(
        _failed_task(failure_code=failure_code, delivery=delivery)
    )

    assert outcome == ExternalTaskContinuationOutcome(
        continuation=continuation,
        failure_permits_another_attempt=permits_attempt,
    )


def test_only_a_retryable_recovery_leaves_another_attempt_open() -> None:
    """One decision produces both fields, so the continuation and the flag cannot disagree."""

    permitted = {
        continuation_for_failed_task(
            _failed_task(failure_code=code, delivery=delivery)
        ).continuation
        for code, delivery in (
            (ExternalTaskFailureCode.TIMEOUT, ExternalTaskDelivery.NOT_SUBMITTED),
            (ExternalTaskFailureCode.TIMEOUT, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.UNAVAILABLE, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.PARTIAL, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.ACCESS_DENIED, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.MALFORMED, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.CONFLICTING, ExternalTaskDelivery.SUBMITTED),
        )
        if continuation_for_failed_task(
            _failed_task(failure_code=code, delivery=delivery)
        ).failure_permits_another_attempt
    }

    assert permitted == {ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE}


def test_a_submitted_timeout_does_not_leave_another_attempt_open() -> None:
    """The one case where delivery, not the failure class, decides the answer."""

    not_submitted = continuation_for_failed_task(
        _failed_task(
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
        )
    )
    submitted = continuation_for_failed_task(
        _failed_task(
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            delivery=ExternalTaskDelivery.SUBMITTED,
        )
    )

    assert not_submitted.failure_permits_another_attempt is True
    assert submitted.failure_permits_another_attempt is False


@pytest.mark.parametrize(
    'status',
    [ExternalTaskOperationStatus.PREPARED, ExternalTaskOperationStatus.ACCEPTED],
)
def test_a_task_that_has_not_failed_has_no_continuation(
    status: ExternalTaskOperationStatus,
) -> None:
    with pytest.raises(TaskHasNotFailedError):
        continuation_for_failed_task(_live_task(status))


def test_the_continuation_carries_nothing_internal() -> None:
    """A reader learns whose turn it is, not what the provider did."""

    task = _failed_task(
        failure_code=ExternalTaskFailureCode.MALFORMED,
        delivery=ExternalTaskDelivery.SUBMITTED,
    )

    continuation = continuation_for_failed_task(task)
    rendered = continuation.model_dump_json()

    assert set(ExternalTaskContinuationOutcome.model_fields) == {
        'continuation',
        'failure_permits_another_attempt',
    }
    assert task.delivery_evidence is not None
    assert task.delivery_evidence not in rendered
    assert task.failure_code is not None
    assert task.failure_code.value not in rendered
    assert task.task_id not in rendered


def test_the_outcome_makes_no_claim_level_permission_statement() -> None:
    """Permission depends on the claim as it stands, which a past failure cannot know.

    Two fields were removed for one reason. `can_request` claimed permission, and
    `responsible_party` claimed whose turn it is; both depend on the claim as it
    stands, and a failure record knows neither. `docs/claim-creation-boundary.md`
    maps a failure to an operation status, a recovery path, and retryability, and
    stops there. Eligibility and responsibility stay with `claimant_assessor_action`
    and with the card that has the live claim.
    """

    fields = set(ExternalTaskContinuationOutcome.model_fields)

    assert 'can_request' not in fields
    assert 'responsible_party' not in fields
    assert fields == {'continuation', 'failure_permits_another_attempt'}
