from enum import Enum

from pydantic import model_validator

from backend.domain.models import ContractModel

ASSESSOR_SERVICE_IDENTITY = 'vehicle_damage_assessment_routing'
ASSESSOR_REQUESTED_ACTION = 'vehicle_damage_assessment'
ASSESSOR_CONSENT_FIELDS = frozenset(
    {
        'claim_id',
        'external_claim_id',
        'authorisation_ref',
        'claimant_consent_ref',
        'requested_action',
        'location.region',
    }
)

ASSESSOR_SHARED_DATA_SUMMARY = (
    'Your Northwind claim and external claim references',
    'Northwind routing authority and your permission reference',
    'The vehicle damage assessment request',
    'Your confirmed incident region',
)


class ExternalTaskDelivery(str, Enum):
    """Whether one external task request reached the provider before it failed.

    Delivery is one input to recovery classification. Only failures whose
    canonical contract treats post-submission state as ambiguous become an
    unknown outcome.
    """

    NOT_SUBMITTED = 'not_submitted'
    SUBMITTED = 'submitted'


class ExternalTaskFailureCode(str, Enum):
    """Provider-neutral failure reasons for one external task invocation.

    The six values are the failure classes named in the Failure Behaviour
    section of `docs/claim-creation-boundary.md`.
    """

    TIMEOUT = 'timeout'
    UNAVAILABLE = 'unavailable'
    ACCESS_DENIED = 'access_denied'
    MALFORMED = 'malformed'
    PARTIAL = 'partial'
    CONFLICTING = 'conflicting'


class ExternalTaskOperationStatus(str, Enum):
    """Lifecycle of one external task operation, held separately from Claim State.

    `UNKNOWN_OUTCOME` is deliberately not a failure: the request may have been
    accepted, so the operation must be reconciled rather than reported as either
    a success or a loss.
    """

    PREPARED = 'prepared'
    ACCEPTED = 'accepted'
    RETRYABLE_FAILURE = 'retryable_failure'
    TERMINAL_FAILURE = 'terminal_failure'
    UNKNOWN_OUTCOME = 'unknown_outcome'


class ExternalTaskRecovery(str, Enum):
    """What Northwind may do next after an external task failure.

    No value authorises an automatic retry; automatic retry counts remain
    unapproved in `docs/claim-creation-boundary.md`.
    """

    RETRY_SAME_OPERATION = 'retry_same_operation'
    RECONCILE_BEFORE_RETRY = 'reconcile_before_retry'
    REVIEW_REQUIRED = 'review_required'


class ExternalTaskFailureClassification(ContractModel):
    """The derived handling of one external task failure."""

    operation_status: ExternalTaskOperationStatus
    recovery: ExternalTaskRecovery
    retryable: bool

    @model_validator(mode='after')
    def validate_recovery_contract(self) -> 'ExternalTaskFailureClassification':
        expected = {
            ExternalTaskRecovery.RETRY_SAME_OPERATION: (
                ExternalTaskOperationStatus.RETRYABLE_FAILURE,
                True,
            ),
            ExternalTaskRecovery.RECONCILE_BEFORE_RETRY: (
                ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
                False,
            ),
            ExternalTaskRecovery.REVIEW_REQUIRED: (
                ExternalTaskOperationStatus.TERMINAL_FAILURE,
                False,
            ),
        }
        expected_status, expected_retryable = expected[self.recovery]
        if self.operation_status is not expected_status or self.retryable is not expected_retryable:
            raise ValueError('External task failure status, recovery, and retryable must agree.')
        return self


_REVIEW_REQUIRED_CODES = frozenset(
    {
        ExternalTaskFailureCode.ACCESS_DENIED,
        ExternalTaskFailureCode.MALFORMED,
        ExternalTaskFailureCode.CONFLICTING,
    }
)

_UNKNOWN_AFTER_SUBMISSION_CODES = frozenset({ExternalTaskFailureCode.TIMEOUT})


def classify_external_task_failure(
    *,
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> ExternalTaskFailureClassification:
    """Derive the operation status and recovery path for one external task failure.

    `docs/claim-creation-boundary.md` states the timeout case explicitly: a
    timeout after submission may be an unknown outcome rather than an ordinary
    failure, and must be reconciled through the operation identity, idempotency
    key, or provider reference before another attempt. `UNAVAILABLE` retains the
    current assessor contract: it is retryable with the same operation identity
    even when the failed invocation reached the provider.

    `PARTIAL` is always an unknown outcome: a partial side effect exists
    regardless of how the request was delivered.

    Args:
        failure_code: The provider-neutral failure class reported by the adapter.
        delivery: Whether the request reached the provider before it failed.

    Returns:
        The operation status to record, the permitted recovery path, and whether
        the caller may retry the same operation identity without reconciling
        first.
    """

    if failure_code in _REVIEW_REQUIRED_CODES:
        return ExternalTaskFailureClassification(
            operation_status=ExternalTaskOperationStatus.TERMINAL_FAILURE,
            recovery=ExternalTaskRecovery.REVIEW_REQUIRED,
            retryable=False,
        )

    submitted = delivery is ExternalTaskDelivery.SUBMITTED
    unknown = failure_code is ExternalTaskFailureCode.PARTIAL or (
        submitted and failure_code in _UNKNOWN_AFTER_SUBMISSION_CODES
    )
    if unknown:
        return ExternalTaskFailureClassification(
            operation_status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            recovery=ExternalTaskRecovery.RECONCILE_BEFORE_RETRY,
            retryable=False,
        )

    return ExternalTaskFailureClassification(
        operation_status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        recovery=ExternalTaskRecovery.RETRY_SAME_OPERATION,
        retryable=True,
    )
