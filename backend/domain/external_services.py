from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from backend.domain.models import (
    ContractModel,
    EvidenceRecord,
    EvidenceSource,
    IntegrationSource,
)

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


class ExternalTaskRecord(ContractModel):
    """One third-party task, recorded separately from Claim State.

    The record carries its own claim association, source class, status, and
    timestamps so a task can be interpreted without reading Claim State, and so
    a fixture result can never be read as a configured-service result.

    Delivery defaults to `NOT_SUBMITTED` and may only be raised to `SUBMITTED`
    by naming the evidence that the request reached the provider. No adapter in
    this repository records that evidence yet, so the default preserves the
    documented assessor behaviour, and a caller cannot escalate a timeout to an
    unknown outcome on an assumption. `docs/claim-creation-boundary.md` requires
    trustworthy delivery evidence before a timeout is classified as submitted.
    """

    task_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    service_identity: str = Field(min_length=1, max_length=100)
    requested_action: str = Field(min_length=1, max_length=100)
    integration_source: IntegrationSource
    status: ExternalTaskOperationStatus
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.NOT_SUBMITTED
    delivery_evidence: str | None = Field(default=None, min_length=1, max_length=200)
    failure_code: ExternalTaskFailureCode | None = None
    provider_reference: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_task_state(self) -> 'ExternalTaskRecord':
        if self.updated_at < self.created_at:
            raise ValueError('External task update cannot precede creation.')
        if self.delivery is ExternalTaskDelivery.SUBMITTED:
            if self.delivery_evidence is None:
                raise ValueError(
                    'A submitted external task must name the evidence that the request '
                    'reached the provider.'
                )
        elif self.delivery_evidence is not None:
            raise ValueError('An unsubmitted external task cannot hold delivery evidence.')
        if self.provider_reference is not None and self.delivery is (
            ExternalTaskDelivery.NOT_SUBMITTED
        ):
            raise ValueError('An unsubmitted external task cannot hold a provider reference.')
        if self.status is ExternalTaskOperationStatus.PREPARED:
            if self.failure_code is not None:
                raise ValueError('A prepared external task cannot hold a failure code.')
            if self.delivery is not ExternalTaskDelivery.NOT_SUBMITTED:
                raise ValueError('A prepared external task has not been submitted.')
            return self
        if self.status is ExternalTaskOperationStatus.ACCEPTED:
            if self.failure_code is not None:
                raise ValueError('An accepted external task cannot hold a failure code.')
            if self.delivery is not ExternalTaskDelivery.SUBMITTED:
                raise ValueError('An accepted external task must have been submitted.')
            return self
        if self.failure_code is None:
            raise ValueError(f'External task status {self.status.value} requires a failure code.')
        expected = classify_external_task_failure(
            failure_code=self.failure_code,
            delivery=self.delivery,
        )
        if expected.operation_status is not self.status:
            raise ValueError(
                f'External task failure {self.failure_code.value} delivered as '
                f'{self.delivery.value} is {expected.operation_status.value}, '
                f'not {self.status.value}.'
            )
        return self


class ExternalTaskEvidenceLink(ContractModel):
    """Ties one evidence record to the external task that produced or owes it."""

    task_id: str = Field(min_length=1, max_length=100)
    evidence_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    linked_at: datetime


class ExternalTaskEvidenceView(ContractModel):
    """One external task with the evidence records currently tied to it."""

    task: ExternalTaskRecord
    evidence_ids: list[str] = Field(default_factory=list)


class UntraceableExternalEvidence(ValueError):
    """An externally sourced evidence record names no originating external task."""


class ExternalTaskClaimMismatch(ValueError):
    """A link joins an evidence record and a task that belong to different claims."""


def external_task_for_evidence(
    record: EvidenceRecord,
    links: Sequence[ExternalTaskEvidenceLink],
) -> str | None:
    """Resolve which external task an evidence record originated from.

    Claimant- and staff-sourced material has no external origin and resolves to
    `None`. External-system material must name its task: without a link the
    record's provenance cannot be checked against the provider result, so it is
    rejected rather than treated as unattributed.

    Args:
        record: The evidence record to resolve.
        links: The evidence-to-task links known for the record's claim.

    Returns:
        The originating `task_id`, or `None` for material that has no external
        origin.

    Raises:
        UntraceableExternalEvidence: The record is external-system sourced and no
            link names a task for it.
    """

    if record.source is not EvidenceSource.EXTERNAL_SYSTEM:
        return None
    for link in links:
        if link.evidence_id == record.evidence_id:
            return link.task_id
    raise UntraceableExternalEvidence(
        f'{record.evidence_id}: external-system evidence names no originating task.'
    )


def map_external_task_evidence(
    tasks: Sequence[ExternalTaskRecord],
    links: Sequence[ExternalTaskEvidenceLink],
) -> list[ExternalTaskEvidenceView]:
    """Project external tasks together with the evidence tied to each.

    Args:
        tasks: The external task records to project.
        links: The evidence-to-task links to apply.

    Returns:
        One view per task, in the order given, each carrying the linked evidence
        identifiers in link order.

    Raises:
        ExternalTaskClaimMismatch: A link names a task whose claim differs from
            the link's own claim.
    """

    grouped: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    claims = {task.task_id: task.claim_id for task in tasks}
    for link in links:
        if link.task_id not in grouped:
            continue
        if claims[link.task_id] != link.claim_id:
            raise ExternalTaskClaimMismatch(
                f'{link.evidence_id}: link claim {link.claim_id} does not match task '
                f'{link.task_id} claim {claims[link.task_id]}.'
            )
        grouped[link.task_id].append(link.evidence_id)
    return [
        ExternalTaskEvidenceView(task=task, evidence_ids=grouped[task.task_id]) for task in tasks
    ]
