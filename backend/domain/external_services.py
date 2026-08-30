from enum import Enum

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

    This is the discriminator the recovery rules turn on: a failure that never
    left Northwind can be retried, while a failure after submission leaves the
    provider's state unknown and must be reconciled first.
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


_REVIEW_REQUIRED_CODES = frozenset(
    {
        ExternalTaskFailureCode.ACCESS_DENIED,
        ExternalTaskFailureCode.MALFORMED,
        ExternalTaskFailureCode.CONFLICTING,
    }
)

_DELIVERY_SENSITIVE_CODES = frozenset(
    {
        ExternalTaskFailureCode.TIMEOUT,
        ExternalTaskFailureCode.UNAVAILABLE,
    }
)


def classify_external_task_failure(
    *,
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
) -> ExternalTaskFailureClassification:
    """Derive the operation status and recovery path for one external task failure.

    `docs/claim-creation-boundary.md` states the timeout case explicitly: a
    timeout after submission may be an unknown outcome rather than an ordinary
    failure, and must be reconciled through the operation identity, idempotency
    key, or provider reference before another attempt. This function applies the
    same escalation to `UNAVAILABLE`, because a request that has already been
    submitted leaves the provider's state equally unknown; the widening is the
    safe direction and is called out here so a reviewer can challenge it.

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
        submitted and failure_code in _DELIVERY_SENSITIVE_CODES
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
