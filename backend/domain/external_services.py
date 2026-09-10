from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from backend.domain.evidence import is_in_conflict
from backend.domain.models import (
    ActorType,
    ContractModel,
    EvidenceRecord,
    EvidenceSource,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalSource

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


class ExternalTaskResultVerification(str, Enum):
    """How far a provider result has been checked against the claim.

    There is deliberately no value meaning "this is now a confirmed claim fact".
    A provider answer is evidence about the claim, never the claim's own record
    of what is true, and `docs/agent-behaviour-catalogue.md` keeps material facts
    proposed until the claim's own confirmation path accepts them. Promotion to a
    confirmed fact is a claim-level decision made elsewhere, so this enum cannot
    express it and no caller can shortcut to it.
    """

    UNVERIFIED = 'unverified'
    CONSISTENT = 'consistent'
    INCONSISTENT = 'inconsistent'
    REVIEW_REQUIRED = 'review_required'


class ExternalTaskResult(ContractModel):
    """What a third-party returned for one task, and how far it has been checked.

    A result is separate from the material it may have produced. A task can
    return an answer and no material at all, such as a provider reporting no
    record found, and it can return material whose consistency with the claim is
    still unknown. Collapsing the two would make an absent answer and an
    unverified one indistinguishable.

    Verification starts at `UNVERIFIED` and a checked result must say when it was
    checked, so an unchecked result cannot be presented as a checked one.
    """

    result_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    source: RetrievalSource
    summary: str = Field(min_length=1, max_length=500)
    verification: ExternalTaskResultVerification = ExternalTaskResultVerification.UNVERIFIED
    verified_at: datetime | None = None
    verified_against_revision: int | None = Field(default=None, ge=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    received_at: datetime

    @model_validator(mode='after')
    def validate_result_state(self) -> 'ExternalTaskResult':
        if not self.summary.strip():
            raise ValueError('An external task result must say something readable.')
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError('Result evidence identifiers must be unique.')
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError('A result evidence identifier must name something.')
        unverified = self.verification is ExternalTaskResultVerification.UNVERIFIED
        if unverified and self.verified_at is not None:
            raise ValueError('An unverified result cannot record a verification time.')
        if not unverified and self.verified_at is None:
            raise ValueError(
                f'A result verified as {self.verification.value} must record when it was checked.'
            )
        if self.verified_at is not None and self.verified_at < self.received_at:
            raise ValueError('A result cannot be verified before it was received.')
        if unverified and self.verified_against_revision is not None:
            raise ValueError('An unverified result cannot name a revision it was checked against.')
        if not unverified and self.verified_against_revision is None:
            raise ValueError(
                f'A result verified as {self.verification.value} must name the claim revision '
                'it was checked against, so a later revision can tell the check is stale.'
            )
        return self


_RESULT_BEARING_TASK_STATES = frozenset(
    {
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
    }
)


class TaskCannotHaveResultError(ValueError):
    """A task in this state cannot have received a provider answer."""


class StaleVerificationError(ValueError):
    """A result was checked against an earlier revision of the claim."""


class UnsettledResultError(ValueError):
    """A result that has not been checked as consistent cannot settle a claim fact."""


def assert_result_matches_task(
    result: ExternalTaskResult,
    task: ExternalTaskRecord,
) -> None:
    """Check that a result belongs to a task that could have produced one.

    Identity is not enough. A task still `prepared` has not been submitted, and a
    task that failed retryably or terminally received no answer, so recording a
    provider result against any of them would assert an answer that cannot exist.
    Only two states can carry one: `accepted`, where the provider took the request
    and may respond, and `unknown_outcome`, which is precisely the state
    reconciliation resolves when a late answer arrives.

    Args:
        result: The recorded provider result.
        task: The external task record the result names.

    Returns:
        None. The result is left unchanged; this raises or returns quietly.

    Raises:
        ExternalRequestTaskMismatchError: The result names a different task, or
            belongs to a different claim than the task it names.
        TaskCannotHaveResultError: The task is in a state that received no answer.
    """

    if result.task_id != task.task_id:
        raise ExternalRequestTaskMismatchError(
            f'{result.result_id}: names task {result.task_id}, not {task.task_id}.'
        )
    if result.claim_id != task.claim_id:
        raise ExternalRequestTaskMismatchError(
            f'{result.result_id}: claim {result.claim_id} does not match task '
            f'{task.task_id} claim {task.claim_id}.'
        )
    if task.status not in _RESULT_BEARING_TASK_STATES:
        raise TaskCannotHaveResultError(
            f'{result.result_id}: task {task.task_id} is {task.status.value}, which received '
            'no provider answer, so it cannot carry a result.'
        )


def assert_result_evidence_is_linked(
    result: ExternalTaskResult,
    links: Sequence[ExternalTaskEvidenceLink],
) -> None:
    """Check that every material a result claims reaches it through a link.

    Holding evidence identifiers directly would reopen the boundary the
    evidence-to-task link already closes: a result on one claim could name
    material belonging to another, or material produced by a different task. The
    links are the only route by which material is attributed, so a result's
    evidence must be present in them, on this result's task and claim.

    Every link for a given identifier is read before an answer is given. Keeping
    only one of them, however chosen, would let the order of the list decide
    whether conflicting attribution is noticed. Repeated links naming the same
    task and claim are one origin and are accepted; two different tasks are a
    conflict whichever order they arrive in.

    Args:
        result: The recorded provider result.
        links: The evidence-to-task links known for this claim.

    Returns:
        None. The result is left unchanged; this raises or returns quietly.

    Raises:
        ExternalTaskClaimMismatchError: A link for this material names another
            claim.
        ConflictingEvidenceOriginError: A link attributes this material to a
            different task.
        UntraceableExternalEvidenceError: The result names material no link
            accounts for.
    """

    for evidence_id in result.evidence_ids:
        matching = [link for link in links if link.evidence_id == evidence_id]
        if not matching:
            raise UntraceableExternalEvidenceError(
                f'{result.result_id}: names evidence {evidence_id}, which no link attributes '
                'to any task.'
            )
        claims = sorted({link.claim_id for link in matching})
        if claims != [result.claim_id]:
            raise ExternalTaskClaimMismatchError(
                f'{result.result_id}: evidence {evidence_id} is linked under claim '
                f'{", ".join(claims)}, not {result.claim_id} alone.'
            )
        tasks = sorted({link.task_id for link in matching})
        if len(tasks) > 1:
            raise ConflictingEvidenceOriginError(
                f'{result.result_id}: evidence {evidence_id} is linked to more than one task '
                f'on claim {result.claim_id}: {", ".join(tasks)}.'
            )
        if tasks != [result.task_id]:
            raise ConflictingEvidenceOriginError(
                f'{result.result_id}: evidence {evidence_id} is linked to task {tasks[0]}, '
                f'not {result.task_id}.'
            )


def assert_result_may_settle_fact(
    result: ExternalTaskResult,
    *,
    claim_revision: int,
) -> None:
    """Check that a result was checked, agreed, and was checked against this claim.

    Being marked consistent is not sufficient on its own. A check is made against
    a particular revision of the claim, and a later revision may have changed the
    facts it agreed with, so the revision is compared rather than trusted. What
    made the result consistent is decided elsewhere; this only refuses to let a
    stale or unchecked answer settle anything.

    Args:
        result: The recorded provider result.
        claim_revision: The current revision of the claim it would inform.

    Returns:
        None. Nothing is settled here; this raises or returns quietly.

    Raises:
        UnsettledResultError: The result has not been checked, or was checked and
            did not agree.
        StaleVerificationError: The result agreed with an earlier revision of the
            claim than the one it would now inform.
    """

    if result.verification is not ExternalTaskResultVerification.CONSISTENT:
        reasons = {
            ExternalTaskResultVerification.UNVERIFIED: 'has not been checked against the claim',
            ExternalTaskResultVerification.INCONSISTENT: 'conflicts with the claim',
            ExternalTaskResultVerification.REVIEW_REQUIRED: 'needs review before it can be used',
        }
        raise UnsettledResultError(f'{result.result_id}: {reasons[result.verification]}.')
    if result.verified_against_revision != claim_revision:
        raise StaleVerificationError(
            f'{result.result_id}: was checked against claim revision '
            f'{result.verified_against_revision}, and the claim is now at {claim_revision}, '
            'so the check no longer covers it.'
        )


class ExternalTaskAttempt(ContractModel):
    """One recorded attempt at an external task, kept whether it succeeded or not.

    A failure that leaves nothing behind is the same as one that never happened,
    and the claim then cannot explain why it is waiting. Each attempt records its
    place in the sequence, when it ran, the claim revision it ran against, and
    what came back, so a claimant or staff reader can see the history rather than
    only the current state.

    The operation identity is the same across every attempt for one request. That
    is what makes a retry the same request rather than a second one, so it is
    recorded here as well and checked before another attempt is permitted.

    Delivery follows the same contract as the task record it belongs to: an
    accepted attempt must have reached the provider, and reaching the provider
    must be evidenced rather than asserted. Without that an attempt could record
    a provider acceptance for a request that was never sent.
    """

    attempt_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    operation_id: str = Field(min_length=1, max_length=100)
    attempt_number: int = Field(ge=1)
    claim_revision: int = Field(ge=1)
    started_at: datetime
    outcome: ExternalTaskOperationStatus
    failure_code: ExternalTaskFailureCode | None = None
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.NOT_SUBMITTED
    delivery_evidence: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_attempt_state(self) -> 'ExternalTaskAttempt':
        if self.delivery is ExternalTaskDelivery.SUBMITTED:
            if self.delivery_evidence is None:
                raise ValueError(
                    'A submitted attempt must name the evidence that the request reached the '
                    'provider.'
                )
        elif self.delivery_evidence is not None:
            raise ValueError('An unsubmitted attempt cannot hold delivery evidence.')
        if self.outcome is ExternalTaskOperationStatus.PREPARED:
            raise ValueError('An attempt that ran cannot record the prepared state.')
        if self.outcome is ExternalTaskOperationStatus.ACCEPTED:
            if self.failure_code is not None:
                raise ValueError('An accepted attempt cannot record a failure code.')
            if self.delivery is not ExternalTaskDelivery.SUBMITTED:
                raise ValueError(
                    'An accepted attempt must have reached the provider, so it must be '
                    'submitted with evidence.'
                )
            return self
        if self.failure_code is None:
            raise ValueError(
                f'An attempt that ended {self.outcome.value} must record a failure code.'
            )
        expected = classify_external_task_failure(
            failure_code=self.failure_code,
            delivery=self.delivery,
        )
        if expected.operation_status is not self.outcome:
            raise ValueError(
                f'Attempt failure {self.failure_code.value} delivered as '
                f'{self.delivery.value} is {expected.operation_status.value}, '
                f'not {self.outcome.value}.'
            )
        return self


class DuplicateExternalRequestError(ValueError):
    """Another attempt would send a second request rather than repeat the first."""


class RetryNotPermittedError(ValueError):
    """The recovery path for the last attempt does not allow another attempt."""


def assert_retry_is_permitted(
    request: ExternalTaskRequest,
    attempts: Sequence[ExternalTaskAttempt],
) -> None:
    """Check that retrying this request repeats it rather than duplicating it.

    Three separate things can go wrong. An attempt can belong to another request
    entirely, and deciding claim A's retry from claim B's history would spend one
    claim's authority on another's work, so the task, claim, and operation
    identity must all agree. A retry can carry a new operation identity, which
    the provider sees as a second request rather than the same one. And a retry
    can be attempted after an outcome whose recovery path forbids it: an unknown
    outcome must be reconciled first, and a terminal failure needs review,
    because in both cases another send may repeat a side effect that already
    happened.

    An accepted attempt is not retryable either. The request succeeded, so a
    further attempt would be a second request by definition.

    The latest attempt decides, chosen by sequence number rather than list
    position. Two attempts sharing a number leave that undecidable, and guessing
    would let a malformed history authorise a send, so an ambiguous history fails
    closed.

    Args:
        request: The sent request being retried.
        attempts: Every recorded attempt for this request, in any order.

    Returns:
        None. Nothing is retried here; this raises or returns quietly.

    Raises:
        ExternalRequestTaskMismatchError: An attempt belongs to a different task
            or claim than the request.
        DuplicateExternalRequestError: The request holds no operation identity, or
            an attempt carries a different one.
        RetryNotPermittedError: There are no attempts to retry, the history is
            ambiguous, or the latest outcome does not permit another attempt.
    """

    if request.operation_id is None:
        raise DuplicateExternalRequestError(
            f'{request.request_id}: has not been sent, so there is nothing to retry and a '
            'send would need its own operation identity.'
        )
    for attempt in attempts:
        for label, on_attempt, on_request in (
            ('task', attempt.task_id, request.task_id),
            ('claim', attempt.claim_id, request.claim_id),
        ):
            if on_attempt != on_request:
                raise ExternalRequestTaskMismatchError(
                    f'{request.request_id}: attempt {attempt.attempt_id} belongs to {label} '
                    f'{on_attempt}, not {on_request}, so it says nothing about this request.'
                )
        if attempt.operation_id != request.operation_id:
            raise DuplicateExternalRequestError(
                f'{request.request_id}: attempt {attempt.attempt_id} carries operation '
                f'{attempt.operation_id}, not {request.operation_id}, so retrying it would '
                'send a second request.'
            )
    if not attempts:
        raise RetryNotPermittedError(
            f'{request.request_id}: no attempt has been recorded, so there is nothing to retry.'
        )
    numbers = [attempt.attempt_number for attempt in attempts]
    if len(numbers) != len(set(numbers)):
        repeated = sorted({n for n in numbers if numbers.count(n) > 1})
        raise RetryNotPermittedError(
            f'{request.request_id}: attempt numbers '
            f'{", ".join(str(n) for n in repeated)} appear more than once, so which attempt '
            'is latest cannot be decided and another send is refused.'
        )
    latest = max(attempts, key=lambda attempt: attempt.attempt_number)
    if latest.outcome is ExternalTaskOperationStatus.ACCEPTED:
        raise RetryNotPermittedError(
            f'{request.request_id}: attempt {latest.attempt_number} was accepted, so another '
            'attempt would be a second request.'
        )
    if latest.failure_code is None:
        raise RetryNotPermittedError(
            f'{request.request_id}: attempt {latest.attempt_number} recorded no failure code, '
            'so no recovery path can be derived.'
        )
    recovery = classify_external_task_failure(
        failure_code=latest.failure_code,
        delivery=latest.delivery,
    ).recovery
    if recovery is not ExternalTaskRecovery.RETRY_SAME_OPERATION:
        raise RetryNotPermittedError(
            f'{request.request_id}: attempt {latest.attempt_number} ended '
            f'{latest.outcome.value}, whose recovery is {recovery.value}, not a retry.'
        )


class ResultAlreadyVerifiedError(ValueError):
    """A result that already carries a verification cannot be checked again."""


class CrossClaimEvidenceError(ValueError):
    """An evidence record offered for this check belongs to another claim."""


class UnboundEvidenceSnapshotError(ValueError):
    """Evidence was recorded after the claim snapshot it would be checked against."""


class VerificationPrecedesStateError(ValueError):
    """A check is dated before some state it read came into being."""


def _assert_evidence_belongs_to_snapshot(
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
) -> None:
    """Check that the evidence offered is the evidence of this claim snapshot.

    Evidence ownership is `claim_id` plus `evidence_id`, so an identifier alone
    does not say which claim a record belongs to. `assert_result_evidence_is_linked`
    checks the links, not the records passed beside them, so without this a record
    carrying a familiar `evidence_id` under a different claim would be read and one
    claim's evidence state would decide another claim's provider result.

    The revision the decision records comes from the claim, and evidence carries no
    revision of its own, so the two inputs cannot be compared directly. They can be
    ordered. `backend/services/evidence.py` advances a claim on every evidence
    mutation and sets `updated_at` to the newest record in the bundle it wrote, so
    within one snapshot no record is newer than the claim. A record that is newer
    was written after this claim was read, and recording the decision against the
    claim's revision would name a revision the check did not use.

    This detects a demonstrable mismatch; it does not prove that the two reads were
    atomic. A caller that reads them separately with nothing in between is not
    distinguishable from one that read them together, and nothing in the models
    could tell them apart. What it removes is the case where the mismatch is
    visible in the data and was previously ignored.

    Args:
        claim: The claim snapshot the check is made against.
        evidence: The evidence records offered with it.

    Returns:
        None. Nothing is modified; this raises or returns quietly.

    Raises:
        CrossClaimEvidenceError: A record belongs to a different claim.
        UnboundEvidenceSnapshotError: A record was updated after the claim
            snapshot was taken.
    """

    for record in evidence:
        if record.claim_id != claim.claim_id:
            raise CrossClaimEvidenceError(
                f'{record.evidence_id}: belongs to claim {record.claim_id}, and the check '
                f'was offered the snapshot of claim {claim.claim_id}.'
            )
        if record.updated_at > claim.updated_at:
            raise UnboundEvidenceSnapshotError(
                f'{record.evidence_id}: was updated at {record.updated_at.isoformat()}, '
                f'after claim {claim.claim_id} was read at '
                f'{claim.updated_at.isoformat()} on revision {claim.revision}, so the '
                'decision cannot be recorded against that revision.'
            )


def _latest_state_read(
    result: ExternalTaskResult,
    *,
    task: ExternalTaskRecord,
    links: Sequence[ExternalTaskEvidenceLink],
    claim: WorkingClaim,
) -> tuple[str, datetime]:
    """Name and time of the most recent state the decision depends on.

    The evidence records are deliberately absent. `_assert_evidence_belongs_to_snapshot`
    has already refused any record newer than the claim, so the claim's own time
    bounds every one of them and a separate comparison could never be the latest.

    Args:
        result: The provider result being checked.
        task: The external task record the result names.
        links: The evidence-to-task links known for this claim.
        claim: The claim snapshot the check is made against.

    Returns:
        A pair of a human-readable description and the time it refers to.
    """

    latest = ('the result arriving', result.received_at)
    candidates = [
        ('the task record being updated', task.updated_at),
        ('the claim snapshot being written', claim.updated_at),
    ]
    named = set(result.evidence_ids)
    for link in links:
        if link.evidence_id not in named:
            continue
        candidates.append((f'evidence {link.evidence_id} being linked', link.linked_at))
    for candidate in candidates:
        if candidate[1] > latest[1]:
            latest = candidate
    return latest


def _names_conflicting_material(
    result: ExternalTaskResult,
    evidence: Sequence[EvidenceRecord],
) -> bool:
    """Report whether material this result itself names stands in an unresolved conflict.

    The question is unchanged; where the answer is read from is not. A conflict used to
    be a status, which could say that a material was contested but never with what. It is
    a typed reference now, so the same guard reads the record's references and a
    resolved conflict no longer counts against the provider.
    """

    named = set(result.evidence_ids)
    for record in evidence:
        if record.evidence_id not in named:
            continue
        if is_in_conflict(record.references):
            return True
    return False


def _decide_result_verification(
    result: ExternalTaskResult,
    *,
    task: ExternalTaskRecord,
    evidence: Sequence[EvidenceRecord],
) -> ExternalTaskResultVerification:
    """Choose the verification an already-validated result earns."""

    if task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        return ExternalTaskResultVerification.REVIEW_REQUIRED
    if _names_conflicting_material(result, evidence):
        return ExternalTaskResultVerification.INCONSISTENT
    return ExternalTaskResultVerification.REVIEW_REQUIRED


def verify_external_task_result(
    result: ExternalTaskResult,
    *,
    task: ExternalTaskRecord,
    links: Sequence[ExternalTaskEvidenceLink],
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
    checked_at: datetime,
) -> ExternalTaskResult:
    """Check a provider result against its own material, and record the answer.

    `assert_result_may_settle_fact` refuses a result that has not been checked and
    says in its own wording that what made a result consistent is decided
    elsewhere. This is that decision, bounded to what this repository can actually
    evidence today.

    **This function never returns `CONSISTENT`, and that is the point.** Agreement
    between a provider answer and the claim is a statement about content: what the
    provider said, measured against what the claim records as true. Nothing here
    models the claim's facts in a form that comparison could be made against, and
    an answer that has not been compared has not been agreed with. Returning
    `CONSISTENT` from task state and evidence links alone would assert a check that
    was never performed, and `assert_result_may_settle_fact` would then let it
    settle a claim fact. `CONSISTENT` stays reserved for a comparison that can be
    evidenced, and until one exists no code in this repository produces it.

    Two outcomes are therefore reachable:

    - `INCONSISTENT` when material this result itself names is recorded as
      standing in an unresolved conflict with another record or a claim fact. The
      conflict is read from the references of the records the result names, never from
      the claim's aggregate evidence state, because a claim-wide rollup would attribute
      an unrelated conflict to this provider.
    - `REVIEW_REQUIRED` otherwise, which is the honest description of an answer
      that has been placed and attributed but not compared.

    An `unknown_outcome` task yields `REVIEW_REQUIRED` before the conflict is
    considered. Its delivery is still unreconciled, so a conflict cannot be
    attributed to the provider any more than an agreement can.

    The claim is taken as one snapshot rather than as an identifier, a state, and
    a revision passed separately. Those three can disagree, and a caller passing an
    older state beside a newer revision number would have the decision recorded
    against a snapshot it never read.

    The evidence records are a second input and are not inside that snapshot, so
    they are checked against it rather than trusted: a record owned by another
    claim, or written after the claim was read, is refused. See
    `_assert_evidence_belongs_to_snapshot` for what that does and does not
    establish.

    A check cannot be dated before the state it read. `checked_at` is compared
    against the latest of the result's arrival, the task record, the claim snapshot,
    and the links this result's material reaches it through. A verification stamped
    at a moment when that state did not yet exist describes a check that could not
    have happened, and the record would then be a false account of when the claim
    was examined rather than a merely imprecise one. The evidence records need no
    separate bound, because none of them can be newer than the claim by the time
    this comparison is made.

    Args:
        result: The unverified provider result to check.
        task: The external task record the result names.
        links: The evidence-to-task links known for this claim.
        claim: The claim snapshot the check is made against, supplying both the
            identity the result must match and the revision recorded with it.
        evidence: The evidence records read with that snapshot.
        checked_at: When the check was performed.

    Returns:
        A new `ExternalTaskResult` carrying the decided verification, the time of
        the check, and the claim revision it was made against. The argument is left
        unchanged.

    Raises:
        ResultAlreadyVerifiedError: The result already carries a verification, so
            checking it would replace a decision rather than make one.
        ExternalTaskClaimMismatchError: The claim snapshot belongs to a different
            claim than the result.
        ExternalRequestTaskMismatchError: The result names a different task, or a
            different claim than the task it names.
        TaskCannotHaveResultError: The task is in a state that received no answer.
        ConflictingEvidenceOriginError: A link attributes the result's material to
            a different task.
        UntraceableExternalEvidenceError: The result names material no link
            accounts for.
        CrossClaimEvidenceError: An evidence record belongs to another claim.
        UnboundEvidenceSnapshotError: An evidence record was written after the
            claim snapshot was read.
        VerificationPrecedesStateError: The check is dated before the result
            arrived, or before the task, claim, or relevant link it read.
    """

    if result.verification is not ExternalTaskResultVerification.UNVERIFIED:
        raise ResultAlreadyVerifiedError(
            f'{result.result_id}: is already recorded as {result.verification.value}, so '
            'checking it again would replace a decision rather than make one.'
        )
    if result.claim_id != claim.claim_id:
        raise ExternalTaskClaimMismatchError(
            f'{result.result_id}: belongs to claim {result.claim_id}, and the check was '
            f'offered the snapshot of claim {claim.claim_id}.'
        )
    assert_result_matches_task(result, task)
    assert_result_evidence_is_linked(result, links)
    _assert_evidence_belongs_to_snapshot(claim, evidence)
    description, latest = _latest_state_read(result, task=task, links=links, claim=claim)
    if checked_at < latest:
        raise VerificationPrecedesStateError(
            f'{result.result_id}: cannot be checked at {checked_at.isoformat()}, which is '
            f'before {description} at {latest.isoformat()}.'
        )

    verification = _decide_result_verification(result, task=task, evidence=evidence)
    fields = result.model_dump()
    fields['verification'] = verification
    fields['verified_at'] = checked_at
    fields['verified_against_revision'] = claim.revision
    return ExternalTaskResult(**fields)


class TaskIdentityChangedError(ValueError):
    """A proposed task record does not describe the same task as the current one."""


class TaskTransitionNotPermittedError(ValueError):
    """The lifecycle does not allow this task to move from its current state."""


_SETTLED_TASK_STATES = frozenset(
    {
        ExternalTaskOperationStatus.ACCEPTED,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    }
)

_TASK_IDENTITY_FIELDS = (
    'task_id',
    'claim_id',
    'service_identity',
    'requested_action',
    'integration_source',
    'created_at',
)


def _assert_same_task(
    current: ExternalTaskRecord,
    proposed: ExternalTaskRecord,
) -> None:
    """Check that a proposed record describes the task it claims to replace."""

    for field in _TASK_IDENTITY_FIELDS:
        held = getattr(current, field)
        offered = getattr(proposed, field)
        if held != offered:
            raise TaskIdentityChangedError(
                f'{current.task_id}: {field} would change from {held} to {offered}, so the '
                'proposed record describes a different task rather than a later state of '
                'this one.'
            )


def assert_task_transition_is_permitted(
    current: ExternalTaskRecord,
    proposed: ExternalTaskRecord,
) -> None:
    """Check that a task may move from the state it holds to the one proposed.

    `ExternalTaskRecord` validates one record against itself: a snapshot cannot be
    internally contradictory. Nothing checked the move between two snapshots, so a
    task could be rewritten from `terminal_failure` back to `accepted`, or from
    `submitted` back to `not_submitted`, and every individual record involved would
    still validate. This closes that gap for the four paths the recovery matrix in
    `docs/claim-creation-boundary.md` governs.

    **Identity first.** A later state of a task must still be that task, so the
    identifiers, the service and action it names, its source class, and its creation
    time are all fixed. `integration_source` matters most: allowing it to change
    would let a fixture task be rewritten as a configured-service one, which is the
    distinction `assert_task_matches_entry` exists to protect at the other end.

    **Delivery never regresses, which is the retry path.** `submitted` to
    `not_submitted` would erase the record that the request may already have reached
    the provider, and the matrix decides `retry_same_operation` against
    `reconcile_before_retry` on exactly that field. The evidence naming the delivery
    is fixed for the same reason: rewriting it rewrites what happened. A timeout that
    was submitted therefore cannot be made to look retryable by lowering its
    delivery.

    **A settled task stays settled, which is the rejection path.** `terminal_failure`
    recovers through `review_required`, not through another attempt, and `accepted`
    is the outcome a retry must not be able to rewind. Neither may move to another
    status here. What happens after review is a claim-level decision recorded
    elsewhere, not a quiet transition on this record.

    **An unknown outcome is reconciled, not assumed, which is the unknown-result
    path.** `partial`, and `timeout` after submission, both recover through
    `reconcile_before_retry`. Reconciliation is what produces the provider's own
    reference for the operation, so moving to `accepted` requires a provider
    reference the unknown record did not hold. Moving to `retryable_failure` is
    refused outright: it would convert an outcome the matrix marks not retryable
    into one that is.

    Nothing may move *to* `prepared`. Prepared means the request has not been sent,
    and a task that has been sent cannot return to not having been.

    Args:
        current: The task record as it is held now.
        proposed: The record that would replace it.

    Returns:
        None. Nothing is written here; this raises or returns quietly.

    Raises:
        TaskIdentityChangedError: The proposed record describes a different task.
        TaskTransitionNotPermittedError: The move is not one the lifecycle allows.
    """

    _assert_same_task(current, proposed)

    if proposed.updated_at < current.updated_at:
        raise TaskTransitionNotPermittedError(
            f'{current.task_id}: the proposed record is dated {proposed.updated_at.isoformat()}, '
            f'before the state it would replace at {current.updated_at.isoformat()}.'
        )

    if current.delivery is ExternalTaskDelivery.SUBMITTED:
        if proposed.delivery is not ExternalTaskDelivery.SUBMITTED:
            raise TaskTransitionNotPermittedError(
                f'{current.task_id}: has reached the provider, and lowering delivery to '
                f'{proposed.delivery.value} would erase the record that it may already have '
                'had an effect.'
            )
        if proposed.delivery_evidence != current.delivery_evidence:
            raise TaskTransitionNotPermittedError(
                f'{current.task_id}: delivery evidence would change from '
                f'{current.delivery_evidence} to {proposed.delivery_evidence}, which rewrites '
                'what reached the provider rather than recording what happened next.'
            )

    if proposed.status is ExternalTaskOperationStatus.PREPARED:
        if current.status is not ExternalTaskOperationStatus.PREPARED:
            raise TaskTransitionNotPermittedError(
                f'{current.task_id}: is {current.status.value} and cannot return to prepared, '
                'which would assert that the request had not been sent.'
            )
        return

    if current.status in _SETTLED_TASK_STATES and proposed.status is not current.status:
        raise TaskTransitionNotPermittedError(
            f'{current.task_id}: is {current.status.value}, which the recovery matrix settles '
            f'through review rather than another attempt, so it cannot become '
            f'{proposed.status.value} here.'
        )

    if current.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        if proposed.status is ExternalTaskOperationStatus.RETRYABLE_FAILURE:
            raise TaskTransitionNotPermittedError(
                f'{current.task_id}: recovers through reconciliation, so it cannot be recorded '
                'as a retryable failure, which would permit an attempt the matrix refuses.'
            )
        if proposed.status is ExternalTaskOperationStatus.ACCEPTED:
            if proposed.provider_reference is None:
                raise TaskTransitionNotPermittedError(
                    f'{current.task_id}: cannot be accepted without a provider reference, '
                    'which is what reconciling an unknown outcome produces.'
                )
            if proposed.provider_reference == current.provider_reference:
                raise TaskTransitionNotPermittedError(
                    f'{current.task_id}: carries provider reference '
                    f'{current.provider_reference} already, so accepting it on the same '
                    'reference records no reconciliation.'
                )


class TaskHasNotFailedError(ValueError):
    """A task that has not failed has no failure continuation to describe."""


class ExternalTaskContinuation(str, Enum):
    """What a failed third-party task means for whoever is waiting on it.

    These are internal names, not a response contract. An earlier revision of this
    head added the same three outcomes to `ClaimantExternalServiceStatus`, which is
    published in `docs/api.md` and the OpenAPI snapshot. `docs-contract.md` requires
    an API contract change to update its claimant and staff consumers in the same
    pull request, and no consumer exists yet, so the vocabulary stays here until the
    card that renders it can publish it alongside its own consumer.
    """

    RETRY_PERMITTED_BY_THE_FAILURE = 'retry_permitted_by_the_failure'
    AWAITING_RECONCILIATION = 'awaiting_reconciliation'
    AWAITING_REVIEW = 'awaiting_review'


class ExternalTaskContinuationOutcome(ContractModel):
    """What a failure means, and whose turn it is, with no claim-level permission.

    `failure_permits_another_attempt` is deliberately narrow and deliberately named
    for what it is. It reports only that the recovery matrix marks *this failure*
    retryable. It is not permission to send again: that depends on the claim as it
    stands now — its workflow state, whether a handoff is open, whether consent is
    still current — and `claimant_assessor_action` already owns that decision with
    the information to make it. A record of a past failure cannot know any of it.

    Reporting the two separately would be worse than reporting one. An earlier
    revision of this head returned a `can_request` flag derived from the failure
    alone, which would have told a claimant they could ask again after their claim
    had moved to professional review. The flag was not wrong about the failure; it
    was answering a question the failure cannot answer.

    There is deliberately no responsible party here either, for the same reason one
    step removed. `docs/claim-creation-boundary.md` maps a failure and its delivery
    to an operation status, a recovery path, and retryability. It does not map a
    recovery path to whoever is responsible now, and it could not: a task that the
    matrix marks retryable may sit under a claim in professional review or with an
    open handoff, where the next move is not the claimant's. Whose turn it is
    depends on the live claim, and belongs where that is available.
    """

    continuation: ExternalTaskContinuation
    failure_permits_another_attempt: bool


_CONTINUATION_BY_RECOVERY = {
    ExternalTaskRecovery.RETRY_SAME_OPERATION: (
        ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE,
        True,
    ),
    ExternalTaskRecovery.RECONCILE_BEFORE_RETRY: (
        ExternalTaskContinuation.AWAITING_RECONCILIATION,
        False,
    ),
    ExternalTaskRecovery.REVIEW_REQUIRED: (
        ExternalTaskContinuation.AWAITING_REVIEW,
        False,
    ),
}


def continuation_for_failed_task(task: ExternalTaskRecord) -> ExternalTaskContinuationOutcome:
    """Say what a failed third-party task means for whoever is waiting on it.

    The failure itself is already preserved: `ExternalTaskRecord` records the
    status, the failure class, and whether the request reached the provider, and
    `list_external_tasks_internal` keeps it on the protected surface. What has been
    missing is the other half of the card — nothing turns that record into a
    statement about who acts next.

    The answer is derived from the recovery path rather than from the failure
    class, because recovery is the part that says whose turn it is.
    `retry_same_operation` means the failure does not itself bar another attempt;
    `reconcile_before_retry` means Northwind must first establish what actually
    happened at the provider, and asking again could duplicate a side effect;
    `review_required` means a person decides before anything else happens.

    **This grants no permission and names no responsible party**, and the fields say
    so by being absent. Both depend on the claim as it stands, which this function
    is not given and could not evaluate from a past failure. It reports only the
    two things the recovery matrix determines.

    A task that has not failed is refused rather than given a neutral answer. An
    accepted or still-prepared task has nothing to continue from, and answering
    for it would let a live request be presented as a failed one.

    Args:
        task: The failed external task record.

    Returns:
        The continuation the failure implies, and whether the failure itself bars
        another attempt.

    Raises:
        TaskHasNotFailedError: The task is prepared or accepted, so it has not
            failed and has no continuation.
    """

    if task.failure_code is None:
        raise TaskHasNotFailedError(
            f'{task.task_id}: is {task.status.value} and holds no failure, so it has no '
            'continuation to describe.'
        )
    recovery = classify_external_task_failure(
        failure_code=task.failure_code,
        delivery=task.delivery,
    ).recovery
    continuation, permits_attempt = _CONTINUATION_BY_RECOVERY[recovery]
    return ExternalTaskContinuationOutcome(
        continuation=continuation,
        failure_permits_another_attempt=permits_attempt,
    )


class ResultAdvanceNotPermittedError(ValueError):
    """The stored result does not allow this write to replace it."""


_RESULT_INGESTION_FACTS = (
    'result_id',
    'task_id',
    'claim_id',
    'source',
    'summary',
    'evidence_ids',
    'received_at',
)


def assert_result_advance_is_permitted(
    current: ExternalTaskResult,
    proposed: ExternalTaskResult,
) -> None:
    """Check that a stored result may be replaced by the one proposed.

    `ExternalTaskResult` validates one record against itself; nothing checked the
    move between two of them. Without that check a recorded answer could be quietly
    rewritten with a different summary or different evidence, and a completed
    verification could be reset to `unverified`, with every individual record still
    valid. A returned result is the record of what a third party said, so rewriting
    it is not an update but a substitution.

    **A task carries one canonical result.** Two results for the same task would
    make "the result" ambiguous for every reader, so a second identity is refused
    rather than stored alongside the first.

    **What arrived is fixed at ingestion.** The identity, the task and claim it
    belongs to, its source, its summary, its evidence identifiers, and the time it
    was received cannot move. `received_at` in particular is an ingestion fact and
    not an advancing update stamp: unlike a task record, a later write must not
    push it forward, because it records when the answer arrived and not when the
    row was last touched.

    **Verification advances once and does not reverse.** A result is ingested
    `unverified` and may make the single transition to a checked state. Writing the
    identical record again is a no-op, which is what makes an ingestion retry safe.
    Anything else — a different checked state, or a return to `unverified` — is a
    contradiction of a check that has already been recorded and fails closed.

    Args:
        current: The result already stored for this task.
        proposed: The result the caller would write.

    Returns:
        None. Nothing is written here; this raises or returns quietly.

    Raises:
        ResultAdvanceNotPermittedError: The write changes an ingestion fact, adds a
            second result to one task, or contradicts a recorded verification.
    """

    if current.result_id != proposed.result_id:
        raise ResultAdvanceNotPermittedError(
            f'{current.task_id}: already holds result {current.result_id}, and a task carries '
            f'one canonical result, so {proposed.result_id} cannot be added beside it.'
        )
    changed = [
        name
        for name in _RESULT_INGESTION_FACTS
        if getattr(current, name) != getattr(proposed, name)
    ]
    if changed:
        raise ResultAdvanceNotPermittedError(
            f'{current.result_id}: {", ".join(changed)} '
            f'{"were" if len(changed) > 1 else "was"} fixed when the answer was ingested and '
            'cannot be rewritten.'
        )
    if current.verification is proposed.verification:
        if (
            current.verified_at != proposed.verified_at
            or current.verified_against_revision != proposed.verified_against_revision
        ):
            raise ResultAdvanceNotPermittedError(
                f'{current.result_id}: is already recorded as {current.verification.value} and '
                'the check it names cannot be restated differently.'
            )
        return
    if current.verification is not ExternalTaskResultVerification.UNVERIFIED:
        raise ResultAdvanceNotPermittedError(
            f'{current.result_id}: was checked as {current.verification.value}; moving it to '
            f'{proposed.verification.value} would contradict a check already recorded.'
        )
