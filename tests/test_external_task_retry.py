from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    DuplicateExternalRequestError,
    ExternalRequestTaskMismatchError,
    ExternalTaskAttempt,
    ExternalTaskAuthorisation,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRequest,
    RetryNotPermittedError,
    assert_retry_is_permitted,
)

PREPARED_AT = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
SENT_AT = PREPARED_AT + timedelta(minutes=1)
OPERATION = 'ext_op_1'


def _request(
    *,
    sent_at: datetime | None = SENT_AT,
    operation_id: str | None = OPERATION,
) -> ExternalTaskRequest:
    return ExternalTaskRequest(
        request_id='ext_req_1',
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        purpose='Request an assessor for the recorded vehicle damage.',
        disclosed_fields=['claim_id', 'location.region'],
        authorisation=ExternalTaskAuthorisation(
            northwind_authority_ref='nw_authority_1',
            claimant_consent_ref='consent_1',
            authorised_revision=3,
        ),
        prepared_at=PREPARED_AT,
        sent_at=sent_at,
        operation_id=operation_id,
    )


def _attempt(
    *,
    attempt_id: str = 'ext_att_1',
    attempt_number: int = 1,
    operation_id: str = OPERATION,
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    outcome: ExternalTaskOperationStatus = ExternalTaskOperationStatus.RETRYABLE_FAILURE,
    failure_code: ExternalTaskFailureCode | None = ExternalTaskFailureCode.UNAVAILABLE,
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.NOT_SUBMITTED,
) -> ExternalTaskAttempt:
    return ExternalTaskAttempt(
        attempt_id=attempt_id,
        task_id=task_id,
        claim_id=claim_id,
        operation_id=operation_id,
        attempt_number=attempt_number,
        claim_revision=3,
        started_at=SENT_AT,
        outcome=outcome,
        failure_code=failure_code,
        delivery=delivery,
        delivery_evidence=(
            'transport-receipt-1' if delivery is ExternalTaskDelivery.SUBMITTED else None
        ),
    )


def test_an_attempt_keeps_the_context_a_failure_would_otherwise_lose() -> None:
    """A failure that leaves nothing behind cannot explain why the claim is waiting."""

    attempt = _attempt()

    assert attempt.claim_id == 'clm_1'
    assert attempt.claim_revision == 3
    assert attempt.attempt_number == 1
    assert attempt.started_at == SENT_AT
    assert attempt.failure_code is ExternalTaskFailureCode.UNAVAILABLE
    assert attempt.operation_id == OPERATION


def test_an_attempt_that_ran_cannot_record_the_prepared_state() -> None:
    with pytest.raises(ValueError, match='cannot record the prepared state'):
        _attempt(outcome=ExternalTaskOperationStatus.PREPARED, failure_code=None)


def test_an_accepted_attempt_carries_no_failure_code() -> None:
    accepted = _attempt(
        outcome=ExternalTaskOperationStatus.ACCEPTED,
        failure_code=None,
        delivery=ExternalTaskDelivery.SUBMITTED,
    )
    assert accepted.failure_code is None

    with pytest.raises(ValueError, match='cannot record a failure code'):
        _attempt(
            outcome=ExternalTaskOperationStatus.ACCEPTED,
            delivery=ExternalTaskDelivery.SUBMITTED,
        )


def test_a_failed_attempt_must_record_a_failure_code() -> None:
    with pytest.raises(ValueError, match='must record a failure code'):
        _attempt(failure_code=None)


def test_the_attempt_outcome_must_match_the_shared_classification() -> None:
    """An attempt cannot record a submitted timeout as an ordinary retryable failure."""

    with pytest.raises(ValueError, match='is unknown_outcome, not retryable_failure'):
        _attempt(
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            delivery=ExternalTaskDelivery.SUBMITTED,
        )


def test_a_retryable_failure_permits_another_attempt() -> None:
    assert_retry_is_permitted(_request(), [_attempt()])


def test_an_unsent_request_has_nothing_to_retry() -> None:
    with pytest.raises(DuplicateExternalRequestError, match='has not been sent'):
        assert_retry_is_permitted(_request(sent_at=None, operation_id=None), [])


def test_an_attempt_under_another_operation_identity_is_a_second_request() -> None:
    """A new identity is what turns a retry into a duplicate at the provider."""

    with pytest.raises(DuplicateExternalRequestError, match='would send a second request'):
        assert_retry_is_permitted(_request(), [_attempt(operation_id='ext_op_other')])


def test_a_request_with_no_recorded_attempt_cannot_be_retried() -> None:
    with pytest.raises(RetryNotPermittedError, match='no attempt has been recorded'):
        assert_retry_is_permitted(_request(), [])


def test_an_accepted_request_cannot_be_retried() -> None:
    with pytest.raises(RetryNotPermittedError, match='would be a second request'):
        assert_retry_is_permitted(
            _request(),
            [
                _attempt(
                    outcome=ExternalTaskOperationStatus.ACCEPTED,
                    failure_code=None,
                    delivery=ExternalTaskDelivery.SUBMITTED,
                )
            ],
        )


@pytest.mark.parametrize(
    ('failure_code', 'delivery', 'outcome', 'recovery'),
    [
        (
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            'reconcile_before_retry',
        ),
        (
            ExternalTaskFailureCode.PARTIAL,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            'reconcile_before_retry',
        ),
        (
            ExternalTaskFailureCode.ACCESS_DENIED,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskOperationStatus.TERMINAL_FAILURE,
            'review_required',
        ),
        (
            ExternalTaskFailureCode.CONFLICTING,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskOperationStatus.TERMINAL_FAILURE,
            'review_required',
        ),
    ],
)
def test_an_outcome_needing_reconciliation_or_review_refuses_a_retry(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
    outcome: ExternalTaskOperationStatus,
    recovery: str,
) -> None:
    """Retrying past an unknown outcome is how a side effect gets repeated."""

    with pytest.raises(RetryNotPermittedError, match=recovery):
        assert_retry_is_permitted(
            _request(),
            [_attempt(outcome=outcome, failure_code=failure_code, delivery=delivery)],
        )


def test_the_latest_attempt_decides_regardless_of_list_order() -> None:
    """An earlier retryable failure must not authorise a retry after a terminal one."""

    first = _attempt(attempt_id='ext_att_1', attempt_number=1)
    second = _attempt(
        attempt_id='ext_att_2',
        attempt_number=2,
        outcome=ExternalTaskOperationStatus.TERMINAL_FAILURE,
        failure_code=ExternalTaskFailureCode.MALFORMED,
    )

    for attempts in ([first, second], [second, first]):
        with pytest.raises(RetryNotPermittedError, match='review_required'):
            assert_retry_is_permitted(_request(), attempts)


def test_an_accepted_attempt_must_have_reached_the_provider() -> None:
    """Otherwise an attempt could record a provider acceptance for an unsent request."""

    with pytest.raises(ValueError, match='must have reached the provider'):
        _attempt(outcome=ExternalTaskOperationStatus.ACCEPTED, failure_code=None)


def test_a_submitted_attempt_must_name_its_delivery_evidence() -> None:
    with pytest.raises(ValueError, match='must name the evidence'):
        ExternalTaskAttempt(
            attempt_id='ext_att_1',
            task_id='ext_task_1',
            claim_id='clm_1',
            operation_id=OPERATION,
            attempt_number=1,
            claim_revision=3,
            started_at=SENT_AT,
            outcome=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            failure_code=ExternalTaskFailureCode.UNAVAILABLE,
            delivery=ExternalTaskDelivery.SUBMITTED,
            delivery_evidence=None,
        )


def test_an_attempt_from_another_task_says_nothing_about_this_request() -> None:
    with pytest.raises(ExternalRequestTaskMismatchError, match='belongs to task'):
        assert_retry_is_permitted(_request(), [_attempt(task_id='ext_task_other')])


def test_an_attempt_from_another_claim_says_nothing_about_this_request() -> None:
    """Deciding claim A's retry from claim B's history spends one claim's authority."""

    with pytest.raises(ExternalRequestTaskMismatchError, match='belongs to claim'):
        assert_retry_is_permitted(_request(), [_attempt(claim_id='clm_other')])


def test_a_duplicate_attempt_number_fails_closed_in_either_order() -> None:
    """Which attempt is latest must not be decided by list position."""

    retryable = _attempt(attempt_id='ext_att_a', attempt_number=2)
    terminal = _attempt(
        attempt_id='ext_att_b',
        attempt_number=2,
        outcome=ExternalTaskOperationStatus.TERMINAL_FAILURE,
        failure_code=ExternalTaskFailureCode.MALFORMED,
    )

    for attempts in ([retryable, terminal], [terminal, retryable]):
        with pytest.raises(RetryNotPermittedError, match='appear more than once'):
            assert_retry_is_permitted(_request(), attempts)
