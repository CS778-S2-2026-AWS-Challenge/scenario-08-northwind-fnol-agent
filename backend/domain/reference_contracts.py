from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReferenceContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceAuthorityClass(str, Enum):
    LEGISLATION = 'legislation'
    INDUSTRY_CODE = 'industry_code'
    GOVERNMENT_GUIDANCE = 'government_guidance'


class SourceVersionBasis(str, Enum):
    OFFICIAL_VERSION_DATE = 'official_version_date'
    PUBLISHER_DOCUMENT_VERSION = 'publisher_document_version'
    RETRIEVAL_DATE = 'retrieval_date'


class SourceSection(ReferenceContractModel):
    section_path: str = Field(min_length=1)
    printed_pages: list[int] | None = None
    pdf_page_indices: list[int] | None = None
    intended_use: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_page_locators(self) -> 'SourceSection':
        if (self.printed_pages is None) != (self.pdf_page_indices is None):
            raise ValueError('printed_pages and pdf_page_indices must be supplied together')
        if self.printed_pages is None or self.pdf_page_indices is None:
            return self
        if not self.printed_pages or not self.pdf_page_indices:
            raise ValueError('page locator lists must not be empty')
        if any(page < 1 for page in self.printed_pages):
            raise ValueError('printed_pages use one-based document page numbers')
        if any(page_index < 0 for page_index in self.pdf_page_indices):
            raise ValueError('pdf_page_indices use zero-based file page indices')
        if self.printed_pages != sorted(set(self.printed_pages)):
            raise ValueError('printed_pages must be unique and ordered')
        if self.pdf_page_indices != sorted(set(self.pdf_page_indices)):
            raise ValueError('pdf_page_indices must be unique and ordered')
        if len(self.printed_pages) != len(self.pdf_page_indices):
            raise ValueError('printed and PDF page locators must map one to one')
        return self


class RagSourceRecord(ReferenceContractModel):
    document_id: str = Field(pattern=r'^src_[a-z0-9_]+$')
    title: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    controlled_reference: str = Field(min_length=1)
    authority: SourceAuthorityClass
    issuer: str = Field(min_length=1)
    version: str = Field(min_length=1)
    version_basis: SourceVersionBasis
    retrieved_at: date
    jurisdiction: str = Field(min_length=1)
    insurer: str | None
    product: str | None
    scope_notes: str = Field(min_length=1)
    effective_from: date | None
    effective_to: date | None
    visibility: Literal['public']
    usage_boundary: str = Field(min_length=1)
    northwind_applicability: Literal['unverified']
    known_limitations: list[str] = Field(min_length=1)
    sections: list[SourceSection] = Field(min_length=1)
    ingestion_status: Literal['candidate_metadata_complete']
    checksum: None = None

    @field_validator('source_uri')
    @classmethod
    def require_https_source(cls, source_uri: str) -> str:
        if not source_uri.startswith('https://'):
            raise ValueError('public source_uri must use https')
        return source_uri

    @model_validator(mode='after')
    def validate_effective_period(self) -> 'RagSourceRecord':
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError('effective_to must be after effective_from')
        return self


class InventoryGovernance(ReferenceContractModel):
    public_sources_are_northwind_policy: Literal[False]
    unverified_northwind_facts: Literal['unknown']
    publication_requires_control_plane_approval: Literal[True]
    checksum_created_during_ingestion: Literal[True]


class RagSourceInventory(ReferenceContractModel):
    schema_version: Literal['1.0']
    inventory_id: str = Field(min_length=1)
    prepared_at: date
    publication_status: Literal['candidate_not_published']
    governance: InventoryGovernance
    sources: list[RagSourceRecord] = Field(min_length=1)

    @model_validator(mode='after')
    def require_unique_document_ids(self) -> 'RagSourceInventory':
        document_ids = [source.document_id for source in self.sources]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError('document_id values must be unique')
        return self


class RequirementReferenceStatus(str, Enum):
    CONFIRMED = 'confirmed'
    UNVERIFIED_EXTERNAL_BRIEF = 'unverified_external_brief'


class RequirementReference(ReferenceContractModel):
    reference: str = Field(min_length=1)
    status: RequirementReferenceStatus
    note: str = Field(min_length=1)


class ExternalParticipant(ReferenceContractModel):
    participant_role: str = Field(min_length=1)
    service_identity: str = Field(min_length=1)
    provider_identity: Literal['unverified']
    purpose: str = Field(min_length=1)


class ClaimantConsent(ReferenceContractModel):
    required: Literal[True]
    authorised_actor: str = Field(min_length=1)
    consent_record_field: str = Field(min_length=1)
    claimant_prompt: str = Field(min_length=1)
    withdrawal_boundary: 'ConsentWithdrawalBoundary'


class ConsentWithdrawalBoundary(ReferenceContractModel):
    before_provider_acceptance: str = Field(min_length=1)
    after_provider_acceptance: str = Field(min_length=1)
    provider_cancellation_status: Literal['requires_separately_approved_capability']


class ServiceContractField(ReferenceContractModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    source: str = Field(min_length=1)
    current_boundary_support: Literal['supported', 'gap_for_issue_252']


class ServiceLifecycleStatus(str, Enum):
    CONSENT_REQUIRED = 'consent_required'
    AUTHORISED = 'authorised'
    SUBMITTING = 'submitting'
    QUEUED = 'queued'
    ASSIGNED = 'assigned'
    RETRYABLE_FAILURE = 'retryable_failure'
    TERMINAL_FAILURE = 'terminal_failure'


class ServiceStatus(ReferenceContractModel):
    status: ServiceLifecycleStatus
    terminal: bool
    claimant_meaning: str = Field(min_length=1)


class FailureOutcomeCode(str, Enum):
    TIMEOUT = 'timeout'
    UNAVAILABLE = 'unavailable'
    ACCESS_DENIED = 'access_denied'
    MALFORMED = 'malformed'


class FailureOutcome(ReferenceContractModel):
    code: FailureOutcomeCode
    retryable: bool
    lifecycle_status: Literal[
        ServiceLifecycleStatus.RETRYABLE_FAILURE,
        ServiceLifecycleStatus.TERMINAL_FAILURE,
    ]
    claimant_wording: str = Field(min_length=1)
    claim_state_effect: Literal['preserve_current_claim']
    retry_expectation: str = Field(min_length=1)


class IdempotencyExpectation(ReferenceContractModel):
    identity_fields: list[str] = Field(min_length=1)
    identical_retry: str = Field(min_length=1)
    changed_payload: str = Field(min_length=1)
    automatic_retry_limit: Literal['not_yet_approved']


class ClaimStateEffects(ReferenceContractModel):
    success_may_change: list[str] = Field(min_length=1)
    failure_may_change: list[str]
    must_not_change: list[str] = Field(min_length=1)


class ExternalServiceScenario(ReferenceContractModel):
    schema_version: Literal['1.0']
    scenario_id: str = Field(min_length=1)
    implementation_status: Literal['contract_only', 'fixture_implemented']
    existing_boundary: Literal['POST /internal/v1/assessors/route']
    requirement_references: list[RequirementReference] = Field(min_length=1)
    participant: ExternalParticipant
    consent: ClaimantConsent
    minimum_input: list[ServiceContractField] = Field(min_length=1)
    provider_neutral_output: list[str] = Field(min_length=1)
    excluded_input: list[str] = Field(min_length=1)
    status_lifecycle: list[ServiceStatus] = Field(min_length=1)
    failure_outcomes: list[FailureOutcome] = Field(min_length=1)
    idempotency: IdempotencyExpectation
    claimant_success_wording: str = Field(min_length=1)
    claim_state_effects: ClaimStateEffects
    known_limitations: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_scenario_completeness(self) -> 'ExternalServiceScenario':
        input_names = [field.name for field in self.minimum_input]
        if len(input_names) != len(set(input_names)):
            raise ValueError('minimum_input field names must be unique')

        failure_codes = {outcome.code for outcome in self.failure_outcomes}
        if failure_codes != set(FailureOutcomeCode):
            raise ValueError('all required failure outcomes must be present exactly once')

        statuses = [status.status for status in self.status_lifecycle]
        if len(statuses) != len(set(statuses)):
            raise ValueError('status lifecycle values must be unique')
        if set(statuses) != set(ServiceLifecycleStatus):
            raise ValueError('all required lifecycle statuses must be present exactly once')

        status_terminality = {status.status: status.terminal for status in self.status_lifecycle}
        expected_terminality = {
            ServiceLifecycleStatus.CONSENT_REQUIRED: False,
            ServiceLifecycleStatus.AUTHORISED: False,
            ServiceLifecycleStatus.SUBMITTING: False,
            ServiceLifecycleStatus.QUEUED: False,
            ServiceLifecycleStatus.ASSIGNED: True,
            ServiceLifecycleStatus.RETRYABLE_FAILURE: False,
            ServiceLifecycleStatus.TERMINAL_FAILURE: True,
        }
        if status_terminality != expected_terminality:
            raise ValueError('lifecycle terminality does not match the retry contract')

        expected_retryability = {
            FailureOutcomeCode.TIMEOUT: True,
            FailureOutcomeCode.UNAVAILABLE: True,
            FailureOutcomeCode.ACCESS_DENIED: False,
            FailureOutcomeCode.MALFORMED: False,
        }
        for outcome in self.failure_outcomes:
            if outcome.retryable is not expected_retryability[outcome.code]:
                raise ValueError(f'{outcome.code.value} has invalid retryability')
            expected_status = (
                ServiceLifecycleStatus.RETRYABLE_FAILURE
                if outcome.retryable
                else ServiceLifecycleStatus.TERMINAL_FAILURE
            )
            if outcome.lifecycle_status != expected_status:
                raise ValueError(f'{outcome.code.value} must use {expected_status.value}')
        return self
