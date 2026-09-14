"""Canonical external-service lifecycle vocabulary and transition registry.

This module is the single definition entry for external request lifecycle semantics.
Persisted ``ExternalTaskRecord`` values remain the operation record; this registry
supplies the stable vocabulary and projection metadata consumed by adapters and UIs.
"""

from enum import Enum
from types import MappingProxyType
from typing import Final

from pydantic import Field, model_validator

from backend.domain.models import ContractModel

REGISTRY_VERSION: Final = 'external-service-lifecycle.v1'


class ExternalLifecycleStatus(str, Enum):
    """Canonical status IDs, including operation and result stages."""

    CONSENT_REQUIRED = 'consent_required'
    AUTHORISED = 'authorised'
    PREPARED = 'prepared'
    SUBMITTING = 'submitting'
    ACCEPTED = 'accepted'
    QUEUED = 'queued'
    ASSIGNED = 'assigned'
    RETRYABLE_FAILURE = 'retryable_failure'
    TERMINAL_FAILURE = 'terminal_failure'
    UNKNOWN_OUTCOME = 'unknown_outcome'
    RESULT_RECEIVED = 'result_received'
    RESULT_VERIFIED = 'result_verified'
    WRITTEN_BACK = 'written_back'


class ExternalLifecycleStage(str, Enum):
    PREPARATION = 'preparation'
    OPERATION = 'operation'
    RESULT = 'result'


class ExternalCapabilityProvenance(str, Enum):
    CONFIGURED = 'configured'
    SIMULATED = 'simulated'
    MANUAL = 'manual'
    UNAVAILABLE = 'unavailable'


class ExternalTaskResultVerification(str, Enum):
    """Canonical outcomes from checking a provider result against the Claim.

    No value promotes a provider answer into confirmed Claim State. Write-back
    remains a separate, authorised lifecycle stage.
    """

    UNVERIFIED = 'unverified'
    CONSISTENT = 'consistent'
    INCONSISTENT = 'inconsistent'
    REVIEW_REQUIRED = 'review_required'


class ExternalLifecycleDefinition(ContractModel):
    """Stable meaning and legal recovery metadata for one lifecycle status."""

    status: ExternalLifecycleStatus
    stage: ExternalLifecycleStage
    claimant_meaning: str = Field(min_length=1, max_length=500)
    staff_meaning: str = Field(min_length=1, max_length=500)
    agent_meaning: str = Field(min_length=1, max_length=500)
    terminal: bool
    allowed_next: tuple[ExternalLifecycleStatus, ...] = ()
    recovery: str = Field(min_length=1, max_length=200)
    claim_state_effect: str = Field(min_length=1, max_length=300)
    state_invariants: tuple[str, ...] = ('claim_scope',)
    transition_preconditions: tuple[str, ...] = ()
    requires_reconciliation: bool = False
    implies_completion: bool = False

    @model_validator(mode='after')
    def validate_safety_invariants(self) -> 'ExternalLifecycleDefinition':
        if self.status is ExternalLifecycleStatus.UNKNOWN_OUTCOME:
            if not self.requires_reconciliation:
                raise ValueError('unknown_outcome must require reconciliation.')
            if self.implies_completion:
                raise ValueError('unknown_outcome cannot imply completion.')
        if (
            self.status
            in {
                ExternalLifecycleStatus.ACCEPTED,
                ExternalLifecycleStatus.ASSIGNED,
            }
            and self.implies_completion
        ):
            raise ValueError('accepted and assigned cannot imply completion.')
        if self.terminal and self.allowed_next:
            raise ValueError('A terminal lifecycle status cannot have next transitions.')
        return self


class ExternalServiceRegistryEntry(ContractModel):
    """Capability and access-form metadata for one service identity."""

    service_identity: str = Field(min_length=1, max_length=100)
    catalogue_reference: str | None = Field(default=None, min_length=1, max_length=100)
    provenance: ExternalCapabilityProvenance
    access_form: str = Field(min_length=1, max_length=200)
    uses_external_task: bool = True
    projectable_statuses: tuple[ExternalLifecycleStatus, ...] = ()
    transient_statuses: tuple[ExternalLifecycleStatus, ...] = ()
    limitation: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def validate_task_boundary(self) -> 'ExternalServiceRegistryEntry':
        declared_statuses = self.projectable_statuses + self.transient_statuses
        if self.uses_external_task and not self.projectable_statuses:
            raise ValueError('An external-task service must declare projectable statuses.')
        if not self.uses_external_task and declared_statuses:
            raise ValueError('A manual path must not declare external-task statuses.')
        if set(self.projectable_statuses) & set(self.transient_statuses):
            raise ValueError('A lifecycle status cannot be both projectable and transient.')
        return self


class ExternalServiceLifecycleProjection(ContractModel):
    """Role-safe, bounded projection shared by Agent and staff consumers."""

    registry_version: str = REGISTRY_VERSION
    service_identity: str = Field(min_length=1, max_length=100)
    catalogue_reference: str | None = None
    provenance: ExternalCapabilityProvenance
    access_form: str = Field(min_length=1, max_length=200)
    limitation: str = Field(min_length=1, max_length=500)
    operation_status: ExternalLifecycleStatus
    result_status: ExternalLifecycleStatus | None = None
    result_verification: ExternalTaskResultVerification | None = None
    claimant_meaning: str = Field(min_length=1, max_length=500)
    agent_meaning: str = Field(min_length=1, max_length=500)
    state_invariants: tuple[str, ...] = ('claim_scope',)
    transition_preconditions: tuple[str, ...] = ()
    pending_owner: str = Field(min_length=1, max_length=80)
    next_action: str = Field(min_length=1, max_length=500)
    requires_reconciliation: bool = False
    allowed_next: tuple[ExternalLifecycleStatus, ...] = ()


def _definition(
    status: ExternalLifecycleStatus,
    stage: ExternalLifecycleStage,
    claimant: str,
    staff: str,
    agent: str,
    *,
    terminal: bool = False,
    next_statuses: tuple[ExternalLifecycleStatus, ...] = (),
    recovery: str,
    claim_effect: str,
    reconcile: bool = False,
) -> ExternalLifecycleDefinition:
    return ExternalLifecycleDefinition(
        status=status,
        stage=stage,
        claimant_meaning=claimant,
        staff_meaning=staff,
        agent_meaning=agent,
        terminal=terminal,
        allowed_next=next_statuses,
        recovery=recovery,
        claim_state_effect=claim_effect,
        requires_reconciliation=reconcile,
    )


_DEFINITIONS = (
    _definition(
        ExternalLifecycleStatus.CONSENT_REQUIRED,
        ExternalLifecycleStage.PREPARATION,
        'Your permission is needed before sharing.',
        'Obtain and verify task-specific consent.',
        'Do not submit until consent is granted.',
        next_statuses=(ExternalLifecycleStatus.AUTHORISED,),
        recovery='Request consent; no external side effect.',
        claim_effect='No Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.AUTHORISED,
        ExternalLifecycleStage.PREPARATION,
        'Permission and Northwind authority are recorded.',
        'Review the authorised disclosure.',
        'Prepare only the authorised fields.',
        next_statuses=(ExternalLifecycleStatus.PREPARED,),
        recovery='Prepare the disclosed payload.',
        claim_effect='No Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.PREPARED,
        ExternalLifecycleStage.PREPARATION,
        'The request is ready but not sent.',
        'Confirm disclosure and submit once.',
        'May propose submission; cannot bypass consent.',
        next_statuses=(ExternalLifecycleStatus.SUBMITTING,),
        recovery='Submit with the existing operation identity.',
        claim_effect='No Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.SUBMITTING,
        ExternalLifecycleStage.OPERATION,
        'The request is being sent.',
        'Observe delivery evidence.',
        'Wait for the operation result.',
        next_statuses=(
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.QUEUED,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ),
        recovery='Use idempotency and delivery evidence.',
        claim_effect='Claim remains unchanged.',
    ),
    _definition(
        ExternalLifecycleStatus.ACCEPTED,
        ExternalLifecycleStage.OPERATION,
        'The service acknowledged the request; completion is not confirmed.',
        'Track the provider response.',
        'Do not treat acknowledgement as completion.',
        next_statuses=(
            ExternalLifecycleStatus.QUEUED,
            ExternalLifecycleStatus.ASSIGNED,
            ExternalLifecycleStatus.RESULT_RECEIVED,
        ),
        recovery='Await provider result.',
        claim_effect='No automatic Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.QUEUED,
        ExternalLifecycleStage.OPERATION,
        'The request is waiting with the service.',
        'Monitor the queue.',
        'Report pending progress only.',
        next_statuses=(
            ExternalLifecycleStatus.ASSIGNED,
            ExternalLifecycleStatus.RESULT_RECEIVED,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ),
        recovery='Track by operation identity.',
        claim_effect='No automatic Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.ASSIGNED,
        ExternalLifecycleStage.OPERATION,
        'A service participant has been assigned; work is not complete.',
        'Monitor assignment and result.',
        'Do not infer a verified result.',
        next_statuses=(ExternalLifecycleStatus.RESULT_RECEIVED,),
        recovery='Await result evidence.',
        claim_effect='No automatic Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.RETRYABLE_FAILURE,
        ExternalLifecycleStage.OPERATION,
        'The request did not complete and may be retried.',
        'Correct the dependency and retry the same operation.',
        'Retry only when the contract permits.',
        next_statuses=(ExternalLifecycleStatus.SUBMITTING,),
        recovery='Retry the same operation identity.',
        claim_effect='No Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.TERMINAL_FAILURE,
        ExternalLifecycleStage.OPERATION,
        'The request needs professional review.',
        'Review before any new request.',
        'Do not retry automatically.',
        terminal=True,
        recovery='Review required; no automatic retry.',
        claim_effect='Record failure; do not mutate Claim facts.',
    ),
    _definition(
        ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ExternalLifecycleStage.OPERATION,
        'We cannot confirm whether the request reached the service.',
        'Reconcile by operation or provider reference before retry.',
        'Reconcile before proposing another side effect.',
        next_statuses=(ExternalLifecycleStatus.ACCEPTED, ExternalLifecycleStatus.TERMINAL_FAILURE),
        recovery='Reconcile before retry.',
        claim_effect='Claim remains unchanged.',
        reconcile=True,
    ),
    _definition(
        ExternalLifecycleStatus.RESULT_RECEIVED,
        ExternalLifecycleStage.RESULT,
        'A result was received but is not verified.',
        'Check result against the current Claim and evidence.',
        'Keep result advisory until verification.',
        next_statuses=(ExternalLifecycleStatus.RESULT_VERIFIED,),
        recovery='Verify against Claim revision.',
        claim_effect='No Claim State change.',
    ),
    _definition(
        ExternalLifecycleStatus.RESULT_VERIFIED,
        ExternalLifecycleStage.RESULT,
        'The result was checked against the Claim.',
        'Use only through an authorised Claim decision.',
        'Do not promote facts without Claim decision.',
        next_statuses=(ExternalLifecycleStatus.WRITTEN_BACK,),
        recovery='Apply an explicit Claim decision.',
        claim_effect='Still not Claim State by itself.',
    ),
    _definition(
        ExternalLifecycleStatus.WRITTEN_BACK,
        ExternalLifecycleStage.RESULT,
        'The authorised result was recorded in the Claim or Evidence boundary.',
        'Review the recorded provenance and revision.',
        'Use the authoritative projection.',
        terminal=True,
        recovery='No operation retry; amend through Claim rules.',
        claim_effect='Explicit, revision-checked write-back only.',
    ),
)


_STATE_INVARIANTS: Final = {
    ExternalLifecycleStatus.CONSENT_REQUIRED: ('claim_scope', 'consent_pending'),
    ExternalLifecycleStatus.AUTHORISED: ('claim_scope', 'consent_ref', 'authorised_revision'),
    ExternalLifecycleStatus.PREPARED: (
        'claim_scope',
        'request_id',
        'authorisation',
        'disclosed_fields',
        'prepared_at',
    ),
    ExternalLifecycleStatus.SUBMITTING: (
        'claim_scope',
        'operation_id',
        'idempotency_key',
        'authorisation',
        'dispatch_reserved_at',
    ),
    ExternalLifecycleStatus.ACCEPTED: ('claim_scope', 'delivery', 'delivery_evidence'),
    ExternalLifecycleStatus.QUEUED: ('claim_scope', 'delivery_evidence', 'operation_id'),
    ExternalLifecycleStatus.ASSIGNED: ('claim_scope', 'delivery_evidence', 'provider_reference'),
    ExternalLifecycleStatus.RETRYABLE_FAILURE: (
        'claim_scope',
        'failure_code',
        'delivery',
    ),
    ExternalLifecycleStatus.TERMINAL_FAILURE: (
        'claim_scope',
        'failure_code',
        'delivery',
    ),
    ExternalLifecycleStatus.UNKNOWN_OUTCOME: (
        'claim_scope',
        'failure_code',
        'delivery',
    ),
    ExternalLifecycleStatus.RESULT_RECEIVED: (
        'claim_scope',
        'source',
        'received_at',
        'evidence_ids',
    ),
    ExternalLifecycleStatus.RESULT_VERIFIED: (
        'claim_scope',
        'verification',
        'verified_at',
        'verified_against_revision',
    ),
    ExternalLifecycleStatus.WRITTEN_BACK: (
        'claim_scope',
        'authorised_decision',
        'resulting_revision',
        'provenance_refs',
    ),
}

_TRANSITION_PRECONDITIONS: Final = {
    ExternalLifecycleStatus.CONSENT_REQUIRED: ('consent_ref', 'granted_at'),
    ExternalLifecycleStatus.AUTHORISED: ('disclosed_fields', 'purpose', 'prepared_at'),
    ExternalLifecycleStatus.PREPARED: (
        'operation_id',
        'idempotency_key',
        'dispatch_reserved_at',
    ),
    ExternalLifecycleStatus.SUBMITTING: ('sent_at', 'delivery_evidence'),
    ExternalLifecycleStatus.ACCEPTED: ('source', 'received_at'),
    ExternalLifecycleStatus.QUEUED: ('provider_reference',),
    ExternalLifecycleStatus.ASSIGNED: ('source', 'received_at'),
    ExternalLifecycleStatus.RETRYABLE_FAILURE: ('operation_id', 'retry_same_operation'),
    ExternalLifecycleStatus.TERMINAL_FAILURE: (),
    ExternalLifecycleStatus.UNKNOWN_OUTCOME: ('reconciliation_evidence',),
    ExternalLifecycleStatus.RESULT_RECEIVED: (
        'verified_at',
        'verified_against_revision',
    ),
    ExternalLifecycleStatus.RESULT_VERIFIED: ('authorised_decision', 'resulting_revision'),
    ExternalLifecycleStatus.WRITTEN_BACK: (),
}

LIFECYCLE_REGISTRY: Final[tuple[ExternalLifecycleDefinition, ...]] = tuple(
    item.model_copy(
        update={
            'state_invariants': _STATE_INVARIANTS[item.status],
            'transition_preconditions': _TRANSITION_PRECONDITIONS[item.status],
        }
    )
    for item in _DEFINITIONS
)
LIFECYCLE_BY_STATUS: Final = MappingProxyType({item.status: item for item in LIFECYCLE_REGISTRY})


REGISTRY_ENTRIES: Final[tuple[ExternalServiceRegistryEntry, ...]] = (
    ExternalServiceRegistryEntry(
        service_identity='vehicle_damage_assessment_routing',
        catalogue_reference='P3-ASSESSOR',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='controlled assessor simulation',
        projectable_statuses=(
            ExternalLifecycleStatus.PREPARED,
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.QUEUED,
            ExternalLifecycleStatus.ASSIGNED,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
            ExternalLifecycleStatus.TERMINAL_FAILURE,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ),
        transient_statuses=(ExternalLifecycleStatus.SUBMITTING,),
        limitation='Simulation-only; it must not be described as a production provider.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='repairer_information_or_link',
        catalogue_reference='P3-REPAIRER',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='claimant-provided link or staff-mediated request',
        uses_external_task=False,
        limitation='Manual path; no synthetic ExternalTask is created for an official link.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='police_105_reporting_guidance',
        catalogue_reference='P3-NZP-REPORT',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='official 105 link or phone guidance',
        uses_external_task=False,
        limitation='Manual guidance path; Northwind does not submit or read Police status.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='police_traffic_crash_report_guidance',
        catalogue_reference='P3-NZP-TCR',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='official TCR request guidance or staff-mediated path',
        uses_external_task=False,
        limitation='Guidance/manual path; Northwind does not claim Police submission.',
    ),
)

SERVICE_REGISTRY: Final = MappingProxyType(
    {item.service_identity: item for item in REGISTRY_ENTRIES}
)

OPERATION_STATUS_IDS: Final = frozenset(
    {
        ExternalLifecycleStatus.PREPARED,
        ExternalLifecycleStatus.ACCEPTED,
        ExternalLifecycleStatus.RETRYABLE_FAILURE,
        ExternalLifecycleStatus.TERMINAL_FAILURE,
        ExternalLifecycleStatus.UNKNOWN_OUTCOME,
    }
)

# ``submitting`` is an observable lifecycle stage, but the existing persisted
# task record intentionally stores only the pre-send snapshot and the adapter's
# post-send outcome.  This mapping makes that boundary explicit instead of
# letting repositories infer it from an unrelated transition table.
PERSISTED_OPERATION_STATUS_IDS: Final = frozenset(OPERATION_STATUS_IDS)

# The result record can coexist only with task states that the authoritative
# ``ExternalTaskResult`` contract accepts. Write-back is intentionally absent:
# proving it needs an authorised Claim/Evidence record, not only a task/result.
_LEGAL_RESULT_STATUSES_BY_OPERATION: Final = MappingProxyType(
    {
        ExternalLifecycleStatus.PREPARED: frozenset(),
        ExternalLifecycleStatus.ACCEPTED: frozenset(
            {
                ExternalLifecycleStatus.RESULT_RECEIVED,
                ExternalLifecycleStatus.RESULT_VERIFIED,
            }
        ),
        ExternalLifecycleStatus.RETRYABLE_FAILURE: frozenset(),
        ExternalLifecycleStatus.TERMINAL_FAILURE: frozenset(),
        ExternalLifecycleStatus.UNKNOWN_OUTCOME: frozenset(
            {
                ExternalLifecycleStatus.RESULT_RECEIVED,
                ExternalLifecycleStatus.RESULT_VERIFIED,
            }
        ),
    }
)


class InvalidExternalLifecycleTransition(ValueError):
    """A proposed lifecycle move is not in the canonical registry."""


def lifecycle_definition(status: ExternalLifecycleStatus | str) -> ExternalLifecycleDefinition:
    """Return the canonical definition for a status."""

    try:
        return LIFECYCLE_BY_STATUS[ExternalLifecycleStatus(status)]
    except (KeyError, ValueError) as exc:
        raise InvalidExternalLifecycleTransition(f'Unknown lifecycle status: {status}.') from exc


def assert_lifecycle_transition(
    current: ExternalLifecycleStatus | str, proposed: ExternalLifecycleStatus | str
) -> None:
    """Raise when a status move is not explicitly permitted by the registry."""

    current_definition = lifecycle_definition(current)
    proposed_status = ExternalLifecycleStatus(proposed)
    if (
        proposed_status not in current_definition.allowed_next
        and proposed_status != current_definition.status
    ):
        raise InvalidExternalLifecycleTransition(
            f'{current_definition.status.value} cannot transition to {proposed_status.value}.'
        )


def service_registry_entry(service_identity: str) -> ExternalServiceRegistryEntry:
    """Return the catalogue/access metadata for a service identity."""

    try:
        return SERVICE_REGISTRY[service_identity]
    except KeyError as exc:
        raise KeyError(f'No canonical external-service entry for {service_identity}.') from exc


def assert_operation_status_registered(status: str) -> None:
    """Ensure a persisted operation status belongs to the canonical vocabulary."""

    try:
        operation_status = ExternalLifecycleStatus(status)
    except ValueError as exc:
        raise InvalidExternalLifecycleTransition(f'Unknown operation status: {status}.') from exc
    if operation_status not in OPERATION_STATUS_IDS:
        raise InvalidExternalLifecycleTransition(
            f'{operation_status.value} is not an operation status in the persisted task contract.'
        )


def assert_persisted_operation_transition(current: str, proposed: str) -> None:
    """Validate a persisted task move through the canonical lifecycle.

    ``submitting`` is transient and therefore never appears in
    ``ExternalTaskRecord``.  Persisted direct edges that cross that transient
    stage are nevertheless checked against its canonical outgoing transitions.
    """

    assert_operation_status_registered(current)
    assert_operation_status_registered(proposed)
    current_status = ExternalLifecycleStatus(current)
    proposed_status = ExternalLifecycleStatus(proposed)
    if current_status is proposed_status:
        return
    if current_status is ExternalLifecycleStatus.PREPARED:
        if proposed_status not in {
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
            ExternalLifecycleStatus.TERMINAL_FAILURE,
        }:
            raise InvalidExternalLifecycleTransition(
                f'{current_status.value} cannot transition to {proposed_status.value}.'
            )
        if proposed_status is not ExternalLifecycleStatus.TERMINAL_FAILURE:
            assert_lifecycle_transition(ExternalLifecycleStatus.SUBMITTING, proposed_status)
        return
    if current_status is ExternalLifecycleStatus.RETRYABLE_FAILURE:
        if proposed_status not in {
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        }:
            raise InvalidExternalLifecycleTransition(
                f'{current_status.value} cannot transition to {proposed_status.value}.'
            )
        assert_lifecycle_transition(ExternalLifecycleStatus.SUBMITTING, proposed_status)
        return
    assert_lifecycle_transition(current_status, proposed_status)


class ExternalProjectionMetadata(ContractModel):
    """Canonical staff projection metadata for one persisted operation status."""

    label: str = Field(min_length=1, max_length=120)
    pending_owner: str = Field(min_length=1, max_length=80)
    next_action: str = Field(min_length=1, max_length=500)


_PROJECTION_METADATA: Final = MappingProxyType(
    {
        ExternalLifecycleStatus.PREPARED: ExternalProjectionMetadata(
            label='Pending',
            pending_owner='claims_professional',
            next_action=(
                'Review the projected disclosure, authority, and consent before submission.'
            ),
        ),
        ExternalLifecycleStatus.ACCEPTED: ExternalProjectionMetadata(
            label='Completion not confirmed',
            pending_owner='external_party',
            next_action='Track the provider result and verify it before reconciling Claim State.',
        ),
        ExternalLifecycleStatus.QUEUED: ExternalProjectionMetadata(
            label='Awaiting service assignment',
            pending_owner='external_party',
            next_action='Track the queued operation by its operation identity.',
        ),
        ExternalLifecycleStatus.ASSIGNED: ExternalProjectionMetadata(
            label='Assessor assigned',
            pending_owner='external_party',
            next_action='Await the assessor result and verify it against the Claim.',
        ),
        ExternalLifecycleStatus.RETRYABLE_FAILURE: ExternalProjectionMetadata(
            label='Failed',
            pending_owner='claims_professional',
            next_action=(
                'Correct the dependency problem, then retry with the same operation identity.'
            ),
        ),
        ExternalLifecycleStatus.TERMINAL_FAILURE: ExternalProjectionMetadata(
            label='Failed',
            pending_owner='claims_professional',
            next_action='Review the failure before another request is attempted.',
        ),
        ExternalLifecycleStatus.UNKNOWN_OUTCOME: ExternalProjectionMetadata(
            label='Outcome not confirmed',
            pending_owner='claims_professional',
            next_action='Reconcile by operation or provider reference before any retry.',
        ),
    }
)


def projection_metadata(status: ExternalLifecycleStatus | str) -> ExternalProjectionMetadata:
    """Return the canonical projection metadata for a persisted operation status."""

    operation_status = ExternalLifecycleStatus(status)
    try:
        return _PROJECTION_METADATA[operation_status]
    except KeyError as exc:
        raise InvalidExternalLifecycleTransition(
            f'{operation_status.value} has no persisted operation projection.'
        ) from exc


def build_lifecycle_projection(
    *,
    service_identity: str,
    operation_status: ExternalLifecycleStatus | str,
    result_status: ExternalLifecycleStatus | str | None = None,
    result_verification: ExternalTaskResultVerification | str | None = None,
) -> ExternalServiceLifecycleProjection:
    """Build one projection from the registered service and canonical status."""

    entry = service_registry_entry(service_identity)
    operation = lifecycle_definition(operation_status)
    if not entry.uses_external_task or operation.status not in entry.projectable_statuses:
        raise InvalidExternalLifecycleTransition(
            f'{operation.status.value} is not projectable for {service_identity}.'
        )
    metadata = projection_metadata(operation.status)
    result = ExternalLifecycleStatus(result_status) if result_status is not None else None
    verification = (
        ExternalTaskResultVerification(result_verification)
        if result_verification is not None
        else None
    )
    if (
        result is not None
        and lifecycle_definition(result).stage is not ExternalLifecycleStage.RESULT
    ):
        raise InvalidExternalLifecycleTransition(
            f'{result.value} is not a result-stage lifecycle status.'
        )
    legal_results = _LEGAL_RESULT_STATUSES_BY_OPERATION.get(operation.status, frozenset())
    if result is not None and result not in legal_results:
        raise InvalidExternalLifecycleTransition(
            f'{operation.status.value} cannot be projected with {result.value}.'
        )
    if result is None and verification is not None:
        raise InvalidExternalLifecycleTransition(
            'A verification outcome requires a result lifecycle status.'
        )
    if result is ExternalLifecycleStatus.RESULT_RECEIVED and verification is not (
        ExternalTaskResultVerification.UNVERIFIED
    ):
        raise InvalidExternalLifecycleTransition('result_received requires the unverified outcome.')
    if result is ExternalLifecycleStatus.RESULT_VERIFIED and verification not in {
        ExternalTaskResultVerification.CONSISTENT,
        ExternalTaskResultVerification.INCONSISTENT,
        ExternalTaskResultVerification.REVIEW_REQUIRED,
    }:
        raise InvalidExternalLifecycleTransition(
            'result_verified requires a checked verification outcome.'
        )
    return ExternalServiceLifecycleProjection(
        service_identity=service_identity,
        catalogue_reference=entry.catalogue_reference,
        provenance=entry.provenance,
        access_form=entry.access_form,
        limitation=entry.limitation,
        operation_status=operation.status,
        result_status=result,
        result_verification=verification,
        claimant_meaning=operation.claimant_meaning,
        agent_meaning=operation.agent_meaning,
        state_invariants=operation.state_invariants,
        transition_preconditions=operation.transition_preconditions,
        pending_owner=metadata.pending_owner,
        next_action=metadata.next_action,
        requires_reconciliation=operation.requires_reconciliation,
        allowed_next=operation.allowed_next,
    )
