from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from backend.domain.models import (
    ActorType,
    ContractModel,
    EvidenceRecord,
    EvidenceSource,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
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


class UntraceableExternalEvidenceError(ValueError):
    """An externally sourced evidence record names no originating external task."""


class ExternalTaskClaimMismatchError(ValueError):
    """A link joins an evidence record and a task that belong to different claims."""


class ConflictingEvidenceOriginError(ValueError):
    """One evidence record is linked to more than one external task on its own claim."""


def external_task_for_evidence(
    record: EvidenceRecord,
    links: Sequence[ExternalTaskEvidenceLink],
) -> str | None:
    """Resolve which external task an evidence record originated from.

    Claimant- and staff-sourced material has no external origin and resolves to
    `None`. External-system material must name its task: without a link the
    record's provenance cannot be checked against the provider result, so it is
    rejected rather than treated as unattributed.

    A link must agree with the record on the claim it belongs to. Matching on the
    evidence identifier alone would let material on one claim take its provenance
    from a link declared against another, so a link that names a different claim
    is rejected rather than skipped: treating it as absent would report a claim
    isolation failure as ordinary missing provenance.

    A record has one origin or none. Every same-claim link is read before an
    answer is given, so two links naming different tasks fail closed instead of
    letting whichever appears first decide. Returning on the first match would
    make provenance depend on list order, which is the opposite of what a
    traceability boundary is for. Repeated links naming the same task are one
    origin and are accepted.

    Args:
        record: The evidence record to resolve.
        links: The evidence-to-task links known for the record's claim.

    Returns:
        The originating `task_id`, or `None` for material that has no external
        origin.

    Raises:
        ConflictingEvidenceOriginError: Same-claim links name more than one
            originating task for this record.
        ExternalTaskClaimMismatchError: A link names this evidence record under a
            different claim.
        UntraceableExternalEvidenceError: The record is external-system sourced and no
            link names a task for it.
    """

    if record.source is not EvidenceSource.EXTERNAL_SYSTEM:
        return None
    origins: list[str] = []
    mismatched: ExternalTaskEvidenceLink | None = None
    for link in links:
        if link.evidence_id != record.evidence_id:
            continue
        if link.claim_id != record.claim_id:
            if mismatched is None:
                mismatched = link
            continue
        if link.task_id not in origins:
            origins.append(link.task_id)
    if len(origins) > 1:
        raise ConflictingEvidenceOriginError(
            f'{record.evidence_id}: linked to more than one external task on claim '
            f'{record.claim_id}: {", ".join(sorted(origins))}.'
        )
    if origins:
        return origins[0]
    if mismatched is not None:
        raise ExternalTaskClaimMismatchError(
            f'{record.evidence_id}: link claim {mismatched.claim_id} does not match evidence '
            f'claim {record.claim_id}.'
        )
    raise UntraceableExternalEvidenceError(
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

    One evidence record belongs to one task within a claim. Projecting the same
    record under two tasks would show a reader two origins for one document and
    let reconciliation settle the wrong external operation, so that input is
    rejected rather than rendered. A repeated link to the same task is one
    membership and appears once.

    Args:
        tasks: The external task records to project.
        links: The evidence-to-task links to apply.

    Returns:
        One view per task, in the order given, each carrying the linked evidence
        identifiers in link order, without repeats.

    Raises:
        ConflictingEvidenceOriginError: One evidence record is linked to more than
            one task on the same claim.
        ExternalTaskClaimMismatchError: A link names a task whose claim differs from
            the link's own claim.
    """

    grouped: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    claims = {task.task_id: task.claim_id for task in tasks}
    origins: dict[tuple[str, str], str] = {}
    for link in links:
        if link.task_id not in grouped:
            continue
        if claims[link.task_id] != link.claim_id:
            raise ExternalTaskClaimMismatchError(
                f'{link.evidence_id}: link claim {link.claim_id} does not match task '
                f'{link.task_id} claim {claims[link.task_id]}.'
            )
        key = (link.claim_id, link.evidence_id)
        held = origins.get(key)
        if held is None:
            origins[key] = link.task_id
            grouped[link.task_id].append(link.evidence_id)
        elif held != link.task_id:
            raise ConflictingEvidenceOriginError(
                f'{link.evidence_id}: linked to more than one external task on claim '
                f'{link.claim_id}: {", ".join(sorted((held, link.task_id)))}.'
            )
    return [
        ExternalTaskEvidenceView(task=task, evidence_ids=grouped[task.task_id]) for task in tasks
    ]


class ExternalTaskAuthorisation(ContractModel):
    """The two independent authorities one external request needs.

    `docs/claim-creation-boundary.md` requires both a current Northwind rule or
    staff decision and a matching active claimant-consent record, and states
    that neither substitutes for the other. They are separate fields here for
    that reason: a request holding only one of them is not authorised, and no
    code path can satisfy the pair by supplying the same reference twice.
    """

    northwind_authority_ref: str = Field(min_length=1, max_length=100)
    claimant_consent_ref: str = Field(min_length=1, max_length=100)
    authorised_revision: int = Field(ge=1)

    @model_validator(mode='after')
    def validate_separate_authorities(self) -> 'ExternalTaskAuthorisation':
        if self.northwind_authority_ref == self.claimant_consent_ref:
            raise ValueError(
                'Northwind authority and claimant consent are separate authorities and '
                'cannot be the same reference.'
            )
        return self


class ExternalTaskRequest(ContractModel):
    """What one external task will disclose, to whom, under what authority, and why.

    The five properties the card requires are each their own field rather than a
    free-form payload: the stakeholder, the claim, the fields actually disclosed,
    the authorisation, and the purpose a claimant can read. A request that cannot
    say all five is not preparable.

    Preparation and sending are separate states. An unsent request holds no
    operation identity, because the identity is what makes a retry the same
    request rather than a second one.
    """

    request_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    service_identity: str = Field(min_length=1, max_length=100)
    requested_action: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=300)
    disclosed_fields: list[str] = Field(min_length=1, max_length=20)
    authorisation: ExternalTaskAuthorisation
    prepared_at: datetime
    sent_at: datetime | None = None
    operation_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_request_state(self) -> 'ExternalTaskRequest':
        if len(self.disclosed_fields) != len(set(self.disclosed_fields)):
            raise ValueError('Disclosed fields must be unique.')
        if any(not field.strip() for field in self.disclosed_fields):
            raise ValueError('A disclosed field must name something readable.')
        if not self.purpose.strip():
            raise ValueError('An external request must state a readable purpose.')
        if (self.sent_at is None) != (self.operation_id is None):
            raise ValueError(
                'A sent external request records both a send time and an operation '
                'identity; an unsent one records neither.'
            )
        if self.sent_at is not None and self.sent_at < self.prepared_at:
            raise ValueError('An external request cannot be sent before it was prepared.')
        return self


class UnauthorisedDisclosureError(ValueError):
    """A request would disclose more than the claimant's consent permits."""


class ExternalRequestTaskMismatchError(ValueError):
    """A request and the external task it names disagree on what they describe."""


def assert_request_matches_task(
    request: ExternalTaskRequest,
    task: ExternalTaskRecord,
) -> None:
    """Check that a request agrees with the task it names.

    The request repeats the task's claim, service, and action so it can be read
    on its own. Repetition without a check is a place for the two to drift, and a
    request naming a task on another claim would carry one claim's authority into
    another claim's work. That is the same failure the evidence-to-task resolver
    already refuses.

    Args:
        request: The prepared request.
        task: The external task record the request names.

    Raises:
        ExternalRequestTaskMismatchError: The request names this task but differs
            from it on the claim, service, or action.
    """

    if request.task_id != task.task_id:
        raise ExternalRequestTaskMismatchError(
            f'{request.request_id}: names task {request.task_id}, not {task.task_id}.'
        )
    for label, on_request, on_task in (
        ('claim', request.claim_id, task.claim_id),
        ('service', request.service_identity, task.service_identity),
        ('action', request.requested_action, task.requested_action),
    ):
        if on_request != on_task:
            raise ExternalRequestTaskMismatchError(
                f'{request.request_id}: {label} {on_request} does not match task '
                f'{task.task_id} {label} {on_task}.'
            )


def assert_disclosure_within_consent(
    request: ExternalTaskRequest,
    consent: ExternalServiceConsent,
    *,
    claim_customer_id: str,
) -> None:
    """Check that a prepared request discloses only what its consent permits.

    The consent must be the one this request names, granted by the claimant this
    claim belongs to, still granted, and issued for the same service and action.
    Matching on the reference alone would let a withdrawn consent, one granted for
    a different action, or one belonging to another customer entirely, authorise a
    disclosure it never covered.

    `docs/claim-creation-boundary.md` requires the record to have been granted by
    the claimant linked to the Working Claim, and states that
    authorised-representative consent is unsupported. Both are enforced here:
    the grantor must be a claimant, and must be this claim's customer.

    Args:
        request: The prepared request about to be sent.
        consent: The claimant-consent record the request names.
        claim_customer_id: The customer the Working Claim belongs to.

    Raises:
        UnauthorisedDisclosureError: The consent does not cover this request, was
            not granted by this claim's claimant, or the request discloses a field
            the consent does not permit.
    """

    if consent.consent_ref != request.authorisation.claimant_consent_ref:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent {consent.consent_ref} is not the consent this '
            f'request names ({request.authorisation.claimant_consent_ref}).'
        )
    if consent.status is not ExternalServiceConsentStatus.GRANTED:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent {consent.consent_ref} is '
            f'{consent.status.value}, so it authorises no disclosure.'
        )
    if consent.granted_by.actor_type is not ActorType.CLAIMANT:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent {consent.consent_ref} was granted by '
            f'{consent.granted_by.actor_type.value}, and only the claimant may consent to '
            'a disclosure.'
        )
    if consent.granted_by.actor_id != claim_customer_id:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent {consent.consent_ref} was granted by another '
            f'customer, so it authorises nothing on this claim.'
        )
    if consent.service_identity != request.service_identity:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent covers service {consent.service_identity}, '
            f'not {request.service_identity}.'
        )
    if consent.requested_action != request.requested_action:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent covers action {consent.requested_action}, '
            f'not {request.requested_action}.'
        )
    beyond = sorted(set(request.disclosed_fields) - set(consent.permitted_fields))
    if beyond:
        raise UnauthorisedDisclosureError(
            f'{request.request_id}: consent {consent.consent_ref} does not permit '
            f'{", ".join(beyond)}.'
        )
