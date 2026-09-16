"""Canonical external-service lifecycle vocabulary and transition registry.

This module is the single definition entry for external request lifecycle semantics.
Persisted ``ExternalTaskRecord`` values remain the operation record; this registry
supplies the stable vocabulary and projection metadata consumed by adapters and UIs.
"""

from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import Field, model_validator

from backend.domain.models import ContractModel

if TYPE_CHECKING:
    from backend.domain.models import ExternalCapabilityProjection

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
    projectable_statuses: tuple[ExternalLifecycleStatus, ...] = (
        ExternalLifecycleStatus.PREPARED,
        ExternalLifecycleStatus.ACCEPTED,
        ExternalLifecycleStatus.QUEUED,
        ExternalLifecycleStatus.ASSIGNED,
        ExternalLifecycleStatus.RETRYABLE_FAILURE,
        ExternalLifecycleStatus.TERMINAL_FAILURE,
        ExternalLifecycleStatus.UNKNOWN_OUTCOME,
    )
    transient_statuses: tuple[ExternalLifecycleStatus, ...] = ()
    limitation: str = Field(min_length=1, max_length=500)
    service_name: str = Field(default='', max_length=160)
    provider_name: str = Field(default='', max_length=160)
    purpose: str = Field(default='', max_length=500)
    requested_action: str = Field(default='submit_request', min_length=1, max_length=100)
    product_families: tuple[str, ...] = ('motor', 'home', 'contents')
    required_fields: tuple[str, ...] = ()
    disclosure_fields: tuple[str, ...] = ()
    official_url: str | None = None
    official_phone: str | None = None
    adapter_kind: str = Field(default='registry_adapter', max_length=80)
    result_semantics: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def validate_task_boundary(self) -> 'ExternalServiceRegistryEntry':
        declared_statuses = self.projectable_statuses + self.transient_statuses
        if self.uses_external_task and not self.projectable_statuses:
            raise ValueError('An external-task service must declare projectable statuses.')
        if not self.uses_external_task and declared_statuses:
            raise ValueError('A manual path must not declare external-task statuses.')
        if set(self.projectable_statuses) & set(self.transient_statuses):
            raise ValueError('A lifecycle status cannot be both projectable and transient.')
        if not self.service_name:
            object.__setattr__(
                self, 'service_name', self.service_identity.replace('_', ' ').title()
            )
        if not self.provider_name:
            object.__setattr__(self, 'provider_name', 'Registered external service')
        if not self.purpose:
            object.__setattr__(self, 'purpose', self.access_form)
        if not self.result_semantics:
            object.__setattr__(
                self,
                'result_semantics',
                'Provider response remains external evidence until verified.',
            )
        return self


class ExternalServiceLifecycleProjection(ContractModel):
    """Role-safe, bounded projection shared by Agent and staff consumers."""

    registry_version: str = REGISTRY_VERSION
    service_identity: str = Field(min_length=1, max_length=100)
    catalogue_reference: str | None = None
    provenance: ExternalCapabilityProvenance
    access_form: str = Field(min_length=1, max_length=200)
    limitation: str = Field(min_length=1, max_length=500)
    service_name: str = Field(default='', max_length=160)
    provider_name: str = Field(default='', max_length=160)
    purpose: str = Field(default='', max_length=500)
    requested_action: str = Field(default='submit_request', min_length=1, max_length=100)
    product_families: tuple[str, ...] = ()
    disclosure_fields: tuple[str, ...] = ()
    official_url: str | None = None
    official_phone: str | None = None
    uses_external_task: bool = True
    operation_status: ExternalLifecycleStatus
    result_status: ExternalLifecycleStatus | None = None
    result_verification: ExternalTaskResultVerification | None = None
    status_label: str = Field(min_length=1, max_length=120)
    status_detail: str = Field(min_length=1, max_length=500)
    verification_state: str = Field(min_length=1, max_length=80)
    claimant_meaning: str = Field(min_length=1, max_length=500)
    agent_meaning: str = Field(min_length=1, max_length=500)
    state_invariants: tuple[str, ...] = ('claim_scope',)
    transition_preconditions: tuple[str, ...] = ()
    pending_owner: str = Field(min_length=1, max_length=80)
    next_action: str = Field(min_length=1, max_length=500)
    needs_attention: bool = False
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
            ExternalLifecycleStatus.CONSENT_REQUIRED,
            ExternalLifecycleStatus.AUTHORISED,
            ExternalLifecycleStatus.PREPARED,
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.QUEUED,
            ExternalLifecycleStatus.ASSIGNED,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
            ExternalLifecycleStatus.TERMINAL_FAILURE,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        ),
        transient_statuses=(ExternalLifecycleStatus.SUBMITTING,),
        limitation='Assignment confirms service ownership, not completion of the assessment.',
        service_name='Vehicle damage assessment',
        provider_name='Approved assessor adapter',
        product_families=('motor',),
        purpose='Request an external assessment of vehicle damage and repairability.',
        requested_action='vehicle_damage_assessment',
        required_fields=('incident.location',),
        disclosure_fields=(
            'claim_id',
            'external_claim_id',
            'authorisation_ref',
            'claimant_consent_ref',
            'requested_action',
            'location.region',
        ),
        adapter_kind='assessor_task_adapter',
        result_semantics='Assessment result is external evidence and requires verification.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='vehicle_recovery_request',
        catalogue_reference='P3-RECOVERY',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='controlled recovery request',
        limitation='Acceptance records a request, not completed vehicle recovery.',
        service_name='Vehicle recovery',
        provider_name='Registered recovery adapter',
        product_families=('motor',),
        purpose='Arrange recovery when the vehicle is unsafe or not drivable.',
        requested_action='request_vehicle_recovery',
        required_fields=(
            'vehicle.drivable',
            'incident.location',
        ),
        disclosure_fields=(
            'vehicle.drivable',
            'incident.location',
            'incident.description',
        ),
        adapter_kind='recovery_request_adapter',
        result_semantics=(
            'Provider acknowledgement, assignment and completion are distinct results.'
        ),
    ),
    ExternalServiceRegistryEntry(
        service_identity='vehicle_repairer_booking',
        catalogue_reference='P3-REPAIR',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='repair booking request',
        limitation='A booking is not confirmed until a provider result is received and verified.',
        service_name='Vehicle repair booking',
        provider_name='Registered repairer adapter',
        product_families=('motor',),
        purpose='Send an authorised repair request with the minimum necessary claim context.',
        requested_action='book_vehicle_repair',
        required_fields=(
            'vehicle.damage_description',
            'incident.location',
        ),
        disclosure_fields=(
            'vehicle.damage_description',
            'incident.location',
        ),
        adapter_kind='repair_request_adapter',
        result_semantics='Repairer response may be accepted, queued, assigned or unavailable.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='home_emergency_repair_request',
        catalogue_reference='P3-HOME-REPAIR',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='controlled emergency repair request',
        limitation='Urgency and property access must be confirmed before dispatch.',
        service_name='Home emergency repair',
        provider_name='Registered home-services adapter',
        product_families=('home',),
        purpose='Request emergency mitigation for insured home damage.',
        requested_action='request_emergency_home_repair',
        required_fields=(
            'property.address',
            'loss.description',
            'property.ongoing_risk',
        ),
        disclosure_fields=(
            'property.address',
            'loss.description',
            'property.ongoing_risk',
        ),
        adapter_kind='home_repair_request_adapter',
        result_semantics=(
            'Provider result records whether mitigation was accepted, assigned or completed.'
        ),
    ),
    ExternalServiceRegistryEntry(
        service_identity='contents_specialist_assessment',
        catalogue_reference='P3-CONTENTS-ASSESSOR',
        provenance=ExternalCapabilityProvenance.SIMULATED,
        access_form='contents assessment request',
        limitation=(
            'A specialist opinion remains evidence until the Claim decision path verifies it.'
        ),
        service_name='Contents specialist assessment',
        provider_name='Registered contents assessor adapter',
        product_families=('contents',),
        purpose='Request specialist assessment for high-value or complex contents loss.',
        requested_action='request_contents_assessment',
        required_fields=(
            'contents.items',
            'incident.location',
        ),
        disclosure_fields=(
            'contents.items',
            'incident.location',
        ),
        adapter_kind='contents_assessment_adapter',
        result_semantics=(
            'The result identifies assessed items and recommendations, not automatic entitlement.'
        ),
    ),
    ExternalServiceRegistryEntry(
        service_identity='repairer_information_or_link',
        catalogue_reference='P3-REPAIRER',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='claimant-provided link or staff-mediated request',
        uses_external_task=False,
        projectable_statuses=(),
        limitation='Manual path; no synthetic ExternalTask is created for an official link.',
        service_name='Repairer information',
        provider_name='Registered repairer directory',
        product_families=('motor',),
        purpose='Help the claimant find an appropriate repairer.',
        requested_action='open_repairer_information',
        adapter_kind='official_link',
        official_url='https://www.aa.co.nz/cars/repair-and-maintenance/',
        result_semantics=(
            'The claimant follows the official link; Northwind does not claim a booking.'
        ),
    ),
    ExternalServiceRegistryEntry(
        service_identity='police_105_reporting_guidance',
        catalogue_reference='P3-NZP-REPORT',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='official 105 link or phone guidance',
        uses_external_task=False,
        projectable_statuses=(),
        limitation='Manual guidance path; Northwind does not submit or read Police status.',
        service_name='Police 105 reporting',
        provider_name='New Zealand Police',
        product_families=('motor', 'home', 'contents'),
        purpose='Provide the official non-emergency reporting channel.',
        requested_action='open_police_105_guidance',
        adapter_kind='official_link_or_phone',
        official_url='https://105.police.govt.nz/',
        official_phone='105',
        result_semantics='The Police website or phone service owns the report and its status.',
    ),
    ExternalServiceRegistryEntry(
        service_identity='police_traffic_crash_report_guidance',
        catalogue_reference='P3-NZP-TCR',
        provenance=ExternalCapabilityProvenance.MANUAL,
        access_form='official TCR request guidance or staff-mediated path',
        uses_external_task=False,
        projectable_statuses=(),
        limitation='Guidance/manual path; Northwind does not claim Police submission.',
        service_name='Traffic crash reporting guidance',
        provider_name='New Zealand Police',
        product_families=('motor',),
        purpose='Provide the official traffic crash reporting guidance.',
        requested_action='open_traffic_crash_guidance',
        adapter_kind='official_link_or_phone',
        official_url=(
            'https://www.police.govt.nz/advice/driving-and-road-safety/traffic-crash-reporting'
        ),
        official_phone='105',
        result_semantics=(
            'Police owns the report; Northwind records only the claimant-provided reference.'
        ),
    ),
)

SERVICE_REGISTRY: Final = MappingProxyType(
    {item.service_identity: item for item in REGISTRY_ENTRIES}
)


def capability_catalogue(
    product_family: str | None = None,
) -> tuple['ExternalCapabilityProjection', ...]:
    """Return the immutable, server-owned third-party capability catalogue."""

    from backend.domain.models import ExternalCapabilityProjection

    family = product_family.strip().lower() if isinstance(product_family, str) else None
    rows = []
    for entry in REGISTRY_ENTRIES:
        if family is not None and family not in entry.product_families:
            continue
        rows.append(
            ExternalCapabilityProjection(
                service_identity=entry.service_identity,
                catalogue_reference=entry.catalogue_reference,
                service_name=entry.service_name,
                provider_name=entry.provider_name,
                product_families=entry.product_families,
                purpose=entry.purpose,
                requested_action=entry.requested_action,
                access_form=entry.access_form,
                adapter_kind=entry.adapter_kind,
                uses_external_task=entry.uses_external_task,
                required_fields=entry.required_fields,
                disclosure_fields=entry.disclosure_fields,
                official_url=entry.official_url,
                official_phone=entry.official_phone,
                result_semantics=entry.result_semantics,
                limitation=entry.limitation,
            )
        )
    return tuple(rows)


def capability_context(
    product_family: str | None = None,
) -> tuple[ExternalServiceLifecycleProjection, ...]:
    """Return registered capabilities as non-executing Agent context."""

    family = product_family.strip().lower() if isinstance(product_family, str) else None
    definition = lifecycle_definition(ExternalLifecycleStatus.CONSENT_REQUIRED)
    metadata = projection_metadata(ExternalLifecycleStatus.CONSENT_REQUIRED)
    rows: list[ExternalServiceLifecycleProjection] = []
    for entry in REGISTRY_ENTRIES:
        if family is not None and family not in entry.product_families:
            continue
        rows.append(
            ExternalServiceLifecycleProjection(
                service_identity=entry.service_identity,
                catalogue_reference=entry.catalogue_reference,
                provenance=entry.provenance,
                access_form=entry.access_form,
                limitation=entry.limitation,
                service_name=entry.service_name,
                provider_name=entry.provider_name,
                purpose=entry.purpose,
                requested_action=entry.requested_action,
                product_families=entry.product_families,
                disclosure_fields=entry.disclosure_fields,
                official_url=entry.official_url,
                official_phone=entry.official_phone,
                uses_external_task=entry.uses_external_task,
                operation_status=ExternalLifecycleStatus.CONSENT_REQUIRED,
                status_label=metadata.label,
                status_detail=metadata.detail,
                verification_state=metadata.verification_state,
                claimant_meaning=definition.claimant_meaning,
                agent_meaning=definition.agent_meaning,
                state_invariants=definition.state_invariants,
                transition_preconditions=definition.transition_preconditions,
                pending_owner=metadata.pending_owner,
                next_action=metadata.next_action,
                needs_attention=metadata.needs_attention,
                requires_reconciliation=False,
                allowed_next=definition.allowed_next,
            )
        )
    return tuple(rows)


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
        ExternalLifecycleStatus.QUEUED: frozenset(
            {
                ExternalLifecycleStatus.RESULT_RECEIVED,
                ExternalLifecycleStatus.RESULT_VERIFIED,
            }
        ),
        ExternalLifecycleStatus.ASSIGNED: frozenset(
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
    """Canonical presentation metadata for one effective lifecycle status."""

    label: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=500)
    verification_state: str = Field(min_length=1, max_length=80)
    pending_owner: str = Field(min_length=1, max_length=80)
    next_action: str = Field(min_length=1, max_length=500)
    needs_attention: bool = False


_PROJECTION_METADATA: Final = MappingProxyType(
    {
        ExternalLifecycleStatus.CONSENT_REQUIRED: ExternalProjectionMetadata(
            label='Permission needed',
            detail='Claimant permission is required before any information is shared.',
            verification_state='not_started',
            pending_owner='claimant',
            next_action='Review and grant the task-specific permission before submission.',
        ),
        ExternalLifecycleStatus.AUTHORISED: ExternalProjectionMetadata(
            label='Ready to request',
            detail='Permission and Northwind authority are recorded; the request is not sent.',
            verification_state='not_started',
            pending_owner='claimant',
            next_action='Submit the authorised assessment request when ready.',
        ),
        ExternalLifecycleStatus.PREPARED: ExternalProjectionMetadata(
            label='Pending',
            detail='The request is prepared and has not been submitted.',
            verification_state='not_started',
            pending_owner='claims_professional',
            next_action=(
                'Review the projected disclosure, authority, and consent before submission.'
            ),
        ),
        ExternalLifecycleStatus.ACCEPTED: ExternalProjectionMetadata(
            label='Completion not confirmed',
            detail='The service acknowledged the request; no completed result is recorded.',
            verification_state='pending_verification',
            pending_owner='external_party',
            next_action='Track the provider result and verify it before reconciling Claim State.',
        ),
        ExternalLifecycleStatus.QUEUED: ExternalProjectionMetadata(
            label='Awaiting service assignment',
            detail='The request is queued with the service; no completed result is recorded.',
            verification_state='pending_verification',
            pending_owner='external_party',
            next_action='Track the queued operation by its operation identity.',
        ),
        ExternalLifecycleStatus.ASSIGNED: ExternalProjectionMetadata(
            label='Assessor assigned',
            detail='An assessor is assigned; the assessment itself is not complete.',
            verification_state='pending_verification',
            pending_owner='external_party',
            next_action='Await the assessor result and verify it against the Claim.',
        ),
        ExternalLifecycleStatus.RETRYABLE_FAILURE: ExternalProjectionMetadata(
            label='Failed',
            detail=(
                'The request failed before a verified result; the same operation may be retried.'
            ),
            verification_state='failed_unverified',
            pending_owner='claims_professional',
            next_action=(
                'Correct the dependency problem, then retry with the same operation identity.'
            ),
            needs_attention=True,
        ),
        ExternalLifecycleStatus.TERMINAL_FAILURE: ExternalProjectionMetadata(
            label='Failed',
            detail='The request failed and requires staff review.',
            verification_state='review_required',
            pending_owner='claims_professional',
            next_action='Review the failure before another request is attempted.',
            needs_attention=True,
        ),
        ExternalLifecycleStatus.UNKNOWN_OUTCOME: ExternalProjectionMetadata(
            label='Outcome not confirmed',
            detail='Submission may have occurred; the result remains unknown.',
            verification_state='reconciliation_required',
            pending_owner='claims_professional',
            next_action='Reconcile by operation or provider reference before any retry.',
            needs_attention=True,
        ),
    }
)

_RESULT_PROJECTION_METADATA: Final = MappingProxyType(
    {
        (
            ExternalLifecycleStatus.RESULT_RECEIVED,
            ExternalTaskResultVerification.UNVERIFIED,
        ): ExternalProjectionMetadata(
            label='Result awaiting verification',
            detail='A provider result is recorded but has not been checked against the Claim.',
            verification_state=ExternalTaskResultVerification.UNVERIFIED.value,
            pending_owner='claims_professional',
            next_action='Verify the returned result against its evidence and the current Claim.',
            needs_attention=True,
        ),
        (
            ExternalLifecycleStatus.RESULT_VERIFIED,
            ExternalTaskResultVerification.CONSISTENT,
        ): ExternalProjectionMetadata(
            label='Result checked',
            detail='The returned result was checked as consistent evidence; it is not Claim State.',
            verification_state=ExternalTaskResultVerification.CONSISTENT.value,
            pending_owner='claims_professional',
            next_action='Use the checked result only through an authorised Claim decision.',
        ),
        (
            ExternalLifecycleStatus.RESULT_VERIFIED,
            ExternalTaskResultVerification.INCONSISTENT,
        ): ExternalProjectionMetadata(
            label='Result conflicts with Claim',
            detail='The returned result was checked and conflicts with the Claim.',
            verification_state=ExternalTaskResultVerification.INCONSISTENT.value,
            pending_owner='claims_professional',
            next_action='Review the conflicting result and cited evidence before continuing.',
            needs_attention=True,
        ),
        (
            ExternalLifecycleStatus.RESULT_VERIFIED,
            ExternalTaskResultVerification.REVIEW_REQUIRED,
        ): ExternalProjectionMetadata(
            label='Result requires review',
            detail='The returned result needs professional review before it can be used.',
            verification_state=ExternalTaskResultVerification.REVIEW_REQUIRED.value,
            pending_owner='claims_professional',
            next_action='Review the result, evidence, and checked Claim revision.',
            needs_attention=True,
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


def project_operation_status(
    *,
    service_identity: str,
    operation_status: ExternalLifecycleStatus | str,
    provider_reference: str | None = None,
    service_progress_status: ExternalLifecycleStatus | str | None = None,
    service_progress_reference: str | None = None,
) -> ExternalLifecycleStatus:
    """Join a persisted task acknowledgement to authoritative service progress.

    The assessor adapter persists request delivery as ``accepted`` on the external task
    and stores its routing outcome on the Claim.  The registry owns the only permitted
    join between those records, including the reference check that prevents a routing
    result for another operation from changing this projection.
    """

    entry = service_registry_entry(service_identity)
    operation = lifecycle_definition(operation_status).status
    if service_progress_status is None:
        return operation
    if service_identity != 'vehicle_damage_assessment_routing':
        raise InvalidExternalLifecycleTransition(
            f'{service_identity} has no registered service-progress projection.'
        )
    progress = lifecycle_definition(service_progress_status).status
    if operation is not ExternalLifecycleStatus.ACCEPTED or progress not in {
        ExternalLifecycleStatus.QUEUED,
        ExternalLifecycleStatus.ASSIGNED,
    }:
        raise InvalidExternalLifecycleTransition(
            f'{operation.value} cannot be projected with service progress {progress.value}.'
        )
    if (
        not provider_reference
        or not service_progress_reference
        or provider_reference != service_progress_reference
    ):
        return operation
    if progress not in entry.projectable_statuses:
        raise InvalidExternalLifecycleTransition(
            f'{progress.value} is not projectable for {service_identity}.'
        )
    assert_lifecycle_transition(operation, progress)
    return progress


def assert_projection_provenance(*, service_identity: str, request_provenance: str) -> None:
    """Reject a persisted request source that contradicts the capability registry."""

    entry = service_registry_entry(service_identity)
    permitted = {
        ExternalCapabilityProvenance.SIMULATED: {'simulated'},
        ExternalCapabilityProvenance.CONFIGURED: {'configured', 'live_attempted'},
    }.get(entry.provenance, set())
    if request_provenance not in permitted:
        raise InvalidExternalLifecycleTransition(
            f'{service_identity} has registry provenance {entry.provenance.value} but request '
            f'provenance is {request_provenance}.'
        )


def assert_external_task_registry_compatible(
    *,
    service_identity: str,
    operation_status: ExternalLifecycleStatus | str,
    request_provenance: str,
) -> None:
    """Reject a new task write that contradicts the canonical service registry."""

    try:
        entry = service_registry_entry(service_identity)
    except KeyError as exc:
        raise InvalidExternalLifecycleTransition(
            f'{service_identity} is not registered for ExternalTask writes.'
        ) from exc
    status = lifecycle_definition(operation_status).status
    if not entry.uses_external_task:
        raise InvalidExternalLifecycleTransition(
            f'{service_identity} is a manual or guidance path and cannot create an ExternalTask.'
        )
    if status not in entry.projectable_statuses or status not in PERSISTED_OPERATION_STATUS_IDS:
        raise InvalidExternalLifecycleTransition(
            f'{status.value} is not a persisted ExternalTask status for {service_identity}.'
        )
    assert_projection_provenance(
        service_identity=service_identity,
        request_provenance=request_provenance,
    )


def build_lifecycle_projection(
    *,
    service_identity: str,
    operation_status: ExternalLifecycleStatus | str,
    result_status: ExternalLifecycleStatus | str | None = None,
    result_verification: ExternalTaskResultVerification | str | None = None,
    provider_reference: str | None = None,
    service_progress_status: ExternalLifecycleStatus | str | None = None,
    service_progress_reference: str | None = None,
) -> ExternalServiceLifecycleProjection:
    """Build one projection from the registered service and canonical status."""

    entry = service_registry_entry(service_identity)
    projected_operation_status = project_operation_status(
        service_identity=service_identity,
        operation_status=operation_status,
        provider_reference=provider_reference,
        service_progress_status=service_progress_status,
        service_progress_reference=service_progress_reference,
    )
    operation = lifecycle_definition(projected_operation_status)
    if not entry.uses_external_task or operation.status not in entry.projectable_statuses:
        raise InvalidExternalLifecycleTransition(
            f'{operation.status.value} is not projectable for {service_identity}.'
        )
    operation_metadata = projection_metadata(operation.status)
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
    if result is not None and verification is None:
        raise InvalidExternalLifecycleTransition(
            'A result lifecycle status requires a verification outcome.'
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
    result_definition = lifecycle_definition(result) if result is not None else None
    result_metadata = None
    if result is not None:
        assert verification is not None
        result_metadata = _RESULT_PROJECTION_METADATA.get((result, verification))
    if result is not None and result_metadata is None:
        raise InvalidExternalLifecycleTransition(
            f'{result.value} has no projection for verification {verification}.'
        )
    operation_requires_reconciliation = operation.requires_reconciliation
    effective_definition = (
        operation
        if operation_requires_reconciliation or result_definition is None
        else result_definition
    )
    effective_metadata = (
        operation_metadata
        if operation_requires_reconciliation or result_metadata is None
        else result_metadata
    )
    state_invariants = tuple(
        dict.fromkeys(
            operation.state_invariants
            + (result_definition.state_invariants if result_definition is not None else ())
        )
    )
    return ExternalServiceLifecycleProjection(
        service_identity=service_identity,
        catalogue_reference=entry.catalogue_reference,
        provenance=entry.provenance,
        access_form=entry.access_form,
        limitation=entry.limitation,
        service_name=entry.service_name,
        provider_name=entry.provider_name,
        purpose=entry.purpose,
        requested_action=entry.requested_action,
        product_families=entry.product_families,
        disclosure_fields=entry.disclosure_fields,
        official_url=entry.official_url,
        official_phone=entry.official_phone,
        uses_external_task=entry.uses_external_task,
        operation_status=operation.status,
        result_status=result,
        result_verification=verification,
        status_label=effective_metadata.label,
        status_detail=effective_metadata.detail,
        verification_state=effective_metadata.verification_state,
        claimant_meaning=effective_definition.claimant_meaning,
        agent_meaning=effective_definition.agent_meaning,
        state_invariants=state_invariants,
        transition_preconditions=effective_definition.transition_preconditions,
        pending_owner=effective_metadata.pending_owner,
        next_action=effective_metadata.next_action,
        needs_attention=effective_metadata.needs_attention,
        requires_reconciliation=operation_requires_reconciliation,
        allowed_next=effective_definition.allowed_next,
    )
