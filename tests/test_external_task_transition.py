from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    TaskIdentityChangedError,
    TaskTransitionNotPermittedError,
    assert_task_transition_is_permitted,
)
from backend.domain.models import IntegrationSource

CREATED_AT = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
LATER = CREATED_AT + timedelta(minutes=5)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
EVIDENCE = 'transport-receipt-1'


def _task(
    *,
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.PREPARED,
    delivery: ExternalTaskDelivery | None = None,
    delivery_evidence: str | None = None,
    failure_code: ExternalTaskFailureCode | None = None,
    provider_reference: str | None = None,
    updated_at: datetime = CREATED_AT,
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    service_identity: str = SERVICE,
    requested_action: str = ACTION,
    integration_source: IntegrationSource = IntegrationSource.FIXTURE,
    created_at: datetime = CREATED_AT,
) -> ExternalTaskRecord:
    """Build a record the model itself accepts, so only the transition is under test."""

    submitted = status in {
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
    }
    resolved_delivery = (
        delivery
        if delivery is not None
        else (ExternalTaskDelivery.SUBMITTED if submitted else ExternalTaskDelivery.NOT_SUBMITTED)
    )
    resolved_evidence = delivery_evidence
    if resolved_evidence is None and resolved_delivery is ExternalTaskDelivery.SUBMITTED:
        resolved_evidence = EVIDENCE
    resolved_failure = failure_code
    if resolved_failure is None and status not in {
        ExternalTaskOperationStatus.PREPARED,
        ExternalTaskOperationStatus.ACCEPTED,
    }:
        resolved_failure = {
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME: ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskOperationStatus.RETRYABLE_FAILURE: ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskOperationStatus.TERMINAL_FAILURE: ExternalTaskFailureCode.MALFORMED,
        }[status]
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity=service_identity,
        requested_action=requested_action,
        integration_source=integration_source,
        status=status,
        delivery=resolved_delivery,
        delivery_evidence=resolved_evidence,
        failure_code=resolved_failure,
        provider_reference=provider_reference,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_a_prepared_task_may_be_accepted() -> None:
    current = _task()
    proposed = _task(status=ExternalTaskOperationStatus.ACCEPTED, updated_at=LATER)

    assert_task_transition_is_permitted(current, proposed)


def test_a_prepared_task_may_fail_retryably() -> None:
    current = _task()
    proposed = _task(status=ExternalTaskOperationStatus.RETRYABLE_FAILURE, updated_at=LATER)

    assert_task_transition_is_permitted(current, proposed)


@pytest.mark.parametrize(
    ('field', 'proposed'),
    [
        ('task_id', _task(task_id='ext_task_2', updated_at=LATER)),
        ('claim_id', _task(claim_id='clm_2', updated_at=LATER)),
        ('service_identity', _task(service_identity='other_service', updated_at=LATER)),
        ('requested_action', _task(requested_action='other_action', updated_at=LATER)),
        (
            'integration_source',
            _task(integration_source=IntegrationSource.CONFIGURED_SERVICE, updated_at=LATER),
        ),
        (
            'created_at',
            _task(created_at=CREATED_AT - timedelta(minutes=1), updated_at=LATER),
        ),
    ],
)
def test_a_changed_identity_field_is_not_a_later_state(
    field: str,
    proposed: ExternalTaskRecord,
) -> None:
    """A later state of a task must still be that task, source class included."""

    with pytest.raises(TaskIdentityChangedError, match=field):
        assert_task_transition_is_permitted(_task(), proposed)


def test_a_transition_cannot_be_dated_before_the_state_it_replaces() -> None:
    current = _task(updated_at=LATER)
    proposed = _task(status=ExternalTaskOperationStatus.ACCEPTED, updated_at=CREATED_AT)

    with pytest.raises(TaskTransitionNotPermittedError, match='before the state it would replace'):
        assert_task_transition_is_permitted(current, proposed)


def test_delivery_cannot_regress_once_the_provider_was_reached() -> None:
    """Lowering delivery would make a submitted timeout look retryable."""

    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)
    proposed = _task(
        status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        delivery=ExternalTaskDelivery.NOT_SUBMITTED,
        failure_code=ExternalTaskFailureCode.UNAVAILABLE,
        updated_at=LATER,
    )

    with pytest.raises(TaskTransitionNotPermittedError, match='lowering delivery'):
        assert_task_transition_is_permitted(current, proposed)


def test_delivery_evidence_cannot_be_rewritten() -> None:
    current = _task(status=ExternalTaskOperationStatus.ACCEPTED)
    proposed = _task(
        status=ExternalTaskOperationStatus.ACCEPTED,
        delivery_evidence='transport-receipt-2',
        updated_at=LATER,
    )

    with pytest.raises(TaskTransitionNotPermittedError, match='delivery evidence would change'):
        assert_task_transition_is_permitted(current, proposed)


def test_a_sent_task_cannot_return_to_prepared() -> None:
    current = _task(status=ExternalTaskOperationStatus.RETRYABLE_FAILURE)
    proposed = _task(updated_at=LATER)

    with pytest.raises(TaskTransitionNotPermittedError, match='cannot return to prepared'):
        assert_task_transition_is_permitted(current, proposed)


def test_a_prepared_task_may_stay_prepared() -> None:
    current = _task()
    proposed = _task(updated_at=LATER)

    assert_task_transition_is_permitted(current, proposed)


@pytest.mark.parametrize(
    'settled',
    [
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    ],
)
@pytest.mark.parametrize(
    'target',
    [
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    ],
)
def test_a_settled_task_does_not_move_on_its_own(
    settled: ExternalTaskOperationStatus,
    target: ExternalTaskOperationStatus,
) -> None:
    """Rejection recovers through review, and an acceptance is not rewound by a retry."""

    current = _task(
        status=settled,
        delivery=ExternalTaskDelivery.SUBMITTED,
        provider_reference='prov-1' if settled.value == 'accepted' else None,
    )
    proposed = _task(
        status=target,
        delivery=ExternalTaskDelivery.SUBMITTED,
        provider_reference='prov-1' if target.value == 'accepted' else None,
        updated_at=LATER,
    )

    if target is settled:
        assert_task_transition_is_permitted(current, proposed)
        return
    with pytest.raises(TaskTransitionNotPermittedError, match='settles'):
        assert_task_transition_is_permitted(current, proposed)


def test_an_unknown_outcome_cannot_be_downgraded_to_retryable() -> None:
    """The matrix marks it not retryable; recording it as retryable would authorise a send."""

    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)
    proposed = _task(
        status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        delivery=ExternalTaskDelivery.SUBMITTED,
        failure_code=ExternalTaskFailureCode.UNAVAILABLE,
        updated_at=LATER,
    )

    with pytest.raises(TaskTransitionNotPermittedError, match='recovers through reconciliation'):
        assert_task_transition_is_permitted(current, proposed)


def test_an_unknown_outcome_cannot_be_accepted_without_reconciliation() -> None:
    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)
    proposed = _task(status=ExternalTaskOperationStatus.ACCEPTED, updated_at=LATER)

    with pytest.raises(TaskTransitionNotPermittedError, match='without a provider reference'):
        assert_task_transition_is_permitted(current, proposed)


def test_an_unknown_outcome_is_not_reconciled_by_the_reference_it_already_had() -> None:
    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME, provider_reference='prov-1')
    proposed = _task(
        status=ExternalTaskOperationStatus.ACCEPTED,
        provider_reference='prov-1',
        updated_at=LATER,
    )

    with pytest.raises(TaskTransitionNotPermittedError, match='records no reconciliation'):
        assert_task_transition_is_permitted(current, proposed)


def test_a_reconciled_unknown_outcome_may_be_accepted() -> None:
    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)
    proposed = _task(
        status=ExternalTaskOperationStatus.ACCEPTED,
        provider_reference='prov-1',
        updated_at=LATER,
    )

    assert_task_transition_is_permitted(current, proposed)


def test_an_unknown_outcome_may_be_settled_terminally_after_review() -> None:
    """Review is the documented recovery, so the outcome it reaches must stay reachable."""

    current = _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME)
    proposed = _task(
        status=ExternalTaskOperationStatus.TERMINAL_FAILURE,
        delivery=ExternalTaskDelivery.SUBMITTED,
        updated_at=LATER,
    )

    assert_task_transition_is_permitted(current, proposed)
