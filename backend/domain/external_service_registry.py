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
    supported_statuses: tuple[ExternalLifecycleStatus, ...] = Field(min_length=1)
    limitation: str = Field(min_length=1, max_length=500)


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


LIFECYCLE_REGISTRY: Final[tuple[ExternalLifecycleDefinition, ...]] = _DEFINITIONS
LIFECYCLE_BY_STATUS: Final = MappingProxyType({item.status: item for item in _DEFINITIONS})


REGISTRY_ENTRIES: Final[tuple[ExternalServiceRegistryEntry, ...]] = (
    ExternalServiceRegistryEntry(
        service_identity='vehicle_damage_assessment_routing',
        catalogue_reference='P3-ASSESSOR',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='controlled assessor simulation',
        supported_statuses=(
            ExternalLifecycleStatus.PREPARED,
            ExternalLifecycleStatus.SUBMITTING,
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.QUEUED,
            ExternalLifecycleStatus.ASSIGNED,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ),
        limitation='Simulation-only; it must not be described as a production provider.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='repairer_information_or_link',
        catalogue_reference='P3-REPAIRER',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='claimant-provided link or staff-mediated request',
        supported_statuses=(ExternalLifecycleStatus.CONSENT_REQUIRED,),
        limitation='Manual path; no synthetic ExternalTask is created for an official link.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='police_guidance_or_official_link',
        catalogue_reference='P3-POLICE',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='official link, phone guidance, or staff-mediated path',
        supported_statuses=(ExternalLifecycleStatus.CONSENT_REQUIRED,),
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
