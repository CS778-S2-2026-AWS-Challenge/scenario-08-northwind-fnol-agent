import pytest

from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecovery,
    classify_external_task_failure,
)


@pytest.mark.parametrize(
    'failure_code',
    [ExternalTaskFailureCode.TIMEOUT, ExternalTaskFailureCode.UNAVAILABLE],
)
def test_unsubmitted_transport_failure_is_retryable(
    failure_code: ExternalTaskFailureCode,
) -> None:
    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=ExternalTaskDelivery.NOT_SUBMITTED,
    )

    assert classification.operation_status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert classification.recovery is ExternalTaskRecovery.RETRY_SAME_OPERATION
    assert classification.retryable is True


@pytest.mark.parametrize(
    'failure_code',
    [ExternalTaskFailureCode.TIMEOUT, ExternalTaskFailureCode.UNAVAILABLE],
)
def test_submitted_transport_failure_becomes_unknown_outcome(
    failure_code: ExternalTaskFailureCode,
) -> None:
    """A lost acknowledgement must never be reported as an ordinary failure."""

    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=ExternalTaskDelivery.SUBMITTED,
    )

    assert classification.operation_status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    assert classification.recovery is ExternalTaskRecovery.RECONCILE_BEFORE_RETRY
    assert classification.retryable is False


@pytest.mark.parametrize(
    'failure_code',
    [
        ExternalTaskFailureCode.ACCESS_DENIED,
        ExternalTaskFailureCode.MALFORMED,
        ExternalTaskFailureCode.CONFLICTING,
    ],
)
@pytest.mark.parametrize('delivery', list(ExternalTaskDelivery))
def test_authority_and_contract_failures_require_review(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> None:
    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=delivery,
    )

    assert classification.operation_status is ExternalTaskOperationStatus.TERMINAL_FAILURE
    assert classification.recovery is ExternalTaskRecovery.REVIEW_REQUIRED
    assert classification.retryable is False


@pytest.mark.parametrize('delivery', list(ExternalTaskDelivery))
def test_partial_failure_is_always_an_unknown_outcome(delivery: ExternalTaskDelivery) -> None:
    """A partial side effect exists however the request was delivered."""

    classification = classify_external_task_failure(
        failure_code=ExternalTaskFailureCode.PARTIAL,
        delivery=delivery,
    )

    assert classification.operation_status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    assert classification.recovery is ExternalTaskRecovery.RECONCILE_BEFORE_RETRY
    assert classification.retryable is False


@pytest.mark.parametrize('failure_code', list(ExternalTaskFailureCode))
@pytest.mark.parametrize('delivery', list(ExternalTaskDelivery))
def test_no_failure_is_ever_classified_as_accepted_or_prepared(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> None:
    """A failure must not be able to reach a status that reads as success."""

    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=delivery,
    )

    assert classification.operation_status not in {
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.PREPARED,
    }


@pytest.mark.parametrize('failure_code', list(ExternalTaskFailureCode))
@pytest.mark.parametrize('delivery', list(ExternalTaskDelivery))
def test_only_retry_same_operation_is_marked_retryable(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> None:
    """`retryable` and the recovery path must never disagree."""

    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=delivery,
    )

    expected = classification.recovery is ExternalTaskRecovery.RETRY_SAME_OPERATION
    assert classification.retryable is expected
