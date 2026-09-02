from datetime import UTC, datetime

import pytest

from backend.domain.external_services import (
    ClaimantTaskContinuation,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    TaskHasNotFailedError,
    claimant_continuation_for_failed_task,
    classify_external_task_failure,
)
from backend.domain.models import (
    ClaimantExternalServiceStatus,
    IntegrationSource,
    ResponsibleParty,
)

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
    ('failure_code', 'delivery', 'status', 'can_request', 'responsible_party'),
    [
        (
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ClaimantExternalServiceStatus.RETRY_AVAILABLE,
            True,
            ResponsibleParty.CLAIMANT,
        ),
        (
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.AWAITING_RECONCILIATION,
            False,
            ResponsibleParty.NORTHWIND,
        ),
        (
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ClaimantExternalServiceStatus.RETRY_AVAILABLE,
            True,
            ResponsibleParty.CLAIMANT,
        ),
        (
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.RETRY_AVAILABLE,
            True,
            ResponsibleParty.CLAIMANT,
        ),
        (
            ExternalTaskFailureCode.PARTIAL,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.AWAITING_RECONCILIATION,
            False,
            ResponsibleParty.NORTHWIND,
        ),
        (
            ExternalTaskFailureCode.ACCESS_DENIED,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.UNDER_REVIEW,
            False,
            ResponsibleParty.CLAIMS_PROFESSIONAL,
        ),
        (
            ExternalTaskFailureCode.MALFORMED,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.UNDER_REVIEW,
            False,
            ResponsibleParty.CLAIMS_PROFESSIONAL,
        ),
        (
            ExternalTaskFailureCode.CONFLICTING,
            ExternalTaskDelivery.SUBMITTED,
            ClaimantExternalServiceStatus.UNDER_REVIEW,
            False,
            ResponsibleParty.CLAIMS_PROFESSIONAL,
        ),
    ],
)
def test_the_recovery_path_decides_what_the_claimant_is_told(
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
    status: ClaimantExternalServiceStatus,
    can_request: bool,
    responsible_party: ResponsibleParty,
) -> None:
    """Every row of the recovery matrix reaches the claimant as one consistent answer."""

    continuation = claimant_continuation_for_failed_task(
        _failed_task(failure_code=failure_code, delivery=delivery)
    )

    assert continuation == ClaimantTaskContinuation(
        status=status,
        can_request=can_request,
        responsible_party=responsible_party,
    )


def test_only_a_retryable_recovery_permits_another_request() -> None:
    """The status and the permission cannot disagree, because one decision produces both."""

    permitted = {
        claimant_continuation_for_failed_task(
            _failed_task(failure_code=code, delivery=delivery)
        ).status
        for code, delivery in (
            (ExternalTaskFailureCode.TIMEOUT, ExternalTaskDelivery.NOT_SUBMITTED),
            (ExternalTaskFailureCode.TIMEOUT, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.UNAVAILABLE, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.PARTIAL, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.ACCESS_DENIED, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.MALFORMED, ExternalTaskDelivery.SUBMITTED),
            (ExternalTaskFailureCode.CONFLICTING, ExternalTaskDelivery.SUBMITTED),
        )
        if claimant_continuation_for_failed_task(
            _failed_task(failure_code=code, delivery=delivery)
        ).can_request
    }

    assert permitted == {ClaimantExternalServiceStatus.RETRY_AVAILABLE}


def test_a_submitted_timeout_does_not_invite_another_request() -> None:
    """The one case where delivery, not the failure class, decides the claimant's answer."""

    not_submitted = claimant_continuation_for_failed_task(
        _failed_task(
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
        )
    )
    submitted = claimant_continuation_for_failed_task(
        _failed_task(
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            delivery=ExternalTaskDelivery.SUBMITTED,
        )
    )

    assert not_submitted.can_request is True
    assert submitted.can_request is False


@pytest.mark.parametrize(
    'status',
    [ExternalTaskOperationStatus.PREPARED, ExternalTaskOperationStatus.ACCEPTED],
)
def test_a_task_that_has_not_failed_has_no_continuation(
    status: ExternalTaskOperationStatus,
) -> None:
    with pytest.raises(TaskHasNotFailedError):
        claimant_continuation_for_failed_task(_live_task(status))


def test_the_continuation_carries_nothing_internal() -> None:
    """A claimant learns whose turn it is, not what the provider did."""

    task = _failed_task(
        failure_code=ExternalTaskFailureCode.MALFORMED,
        delivery=ExternalTaskDelivery.SUBMITTED,
    )

    continuation = claimant_continuation_for_failed_task(task)
    rendered = continuation.model_dump_json()

    assert set(ClaimantTaskContinuation.model_fields) == {
        'status',
        'can_request',
        'responsible_party',
    }
    assert task.delivery_evidence is not None
    assert task.delivery_evidence not in rendered
    assert task.failure_code is not None
    assert task.failure_code.value not in rendered
    assert task.task_id not in rendered
