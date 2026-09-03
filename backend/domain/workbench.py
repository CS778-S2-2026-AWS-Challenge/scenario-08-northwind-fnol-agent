"""Typed staff-only projections for the Claims Workbench."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import Field

from backend.domain.external_services import ExternalTaskRecord, ExternalTaskRequest
from backend.domain.models import (
    ClaimCollaborationRequest,
    ClaimState,
    ContractModel,
    CustomerNextStep,
    CustomerUpdateRecord,
    EvidenceRecord,
    MessageRecord,
    PageInfo,
    StaffActionRecord,
    StructuredFormField,
    WorkbenchHandoff,
    WorkbenchSession,
    WorkflowState,
)
from backend.domain.retrieval import RetrievalRecord
from backend.domain.tag_registry import StaffTag


class ClaimLifecycleState(StrEnum):
    DRAFT_ACTIVE = 'draft_active'
    WAITING_CUSTOMER = 'waiting_customer'
    WAITING_EXTERNAL = 'waiting_external'
    STAFF_SUPPORT = 'staff_support'
    PROFESSIONAL_REVIEW = 'professional_review'
    READY_TO_CREATE = 'ready_to_create'
    CREATING = 'creating'
    CREATED = 'created'
    WITHDRAWN = 'withdrawn'
    EXPIRED = 'expired'
    PURGED_OR_ANONYMISED = 'purged_or_anonymised'


class OwnershipState(StrEnum):
    UNASSIGNED = 'unassigned'
    RESERVED = 'reserved'
    ASSIGNED = 'assigned'


class CurrentStaffAccess(StrEnum):
    READ_ONLY = 'read_only'
    PRIMARY = 'primary'
    COWORKER = 'coworker'
    DISPATCHER = 'dispatcher'


class WorkPriorityLevel(StrEnum):
    ROUTINE = 'routine'
    STANDARD = 'standard'
    HIGH = 'high'
    URGENT = 'urgent'
    IMMEDIATE = 'immediate'


class MissingInformationAttention(StrEnum):
    REQUIRED_NOW = 'required_now'
    NEEDED_NEXT = 'needed_next'
    FOLLOW_UP = 'follow_up'


class RiskAttentionLevel(StrEnum):
    NOTICE = 'notice'
    REVIEW_REQUIRED = 'review_required'
    URGENT_REVIEW = 'urgent_review'
    IMMEDIATE_ACTION = 'immediate_action'


class SignalReviewStatus(StrEnum):
    OPEN = 'open'
    UNDER_REVIEW = 'under_review'
    DISMISSED = 'dismissed'
    RESOLVED = 'resolved'


class ActionAvailability(StrEnum):
    AVAILABLE = 'available'
    CONFIRMATION_REQUIRED = 'confirmation_required'
    BLOCKED = 'blocked'


class ConfirmationLevel(StrEnum):
    NONE = 'none'
    EXPLICIT = 'explicit'
    HIGH_IMPACT = 'high_impact'


class WorkbenchResponsibility(StrEnum):
    CLAIMANT = 'claimant'
    CLAIMS_PROFESSIONAL = 'claims_professional'
    EXTERNAL_PARTY = 'external_party'
    SYSTEM = 'system'


class ResourceAvailability(StrEnum):
    AVAILABLE = 'available'
    UNAVAILABLE = 'unavailable'


class WorkbenchConversationKind(StrEnum):
    CLAIM = 'claim'
    STAFF_AGENT = 'staff_agent'


class WorkbenchClaimantSummary(ContractModel):
    customer_id: str
    display_name: str | None = None
    preferred_contact_channel: str | None = None


class WorkbenchIncidentSummary(ContractModel):
    family: str | None = None
    summary: str


class WorkbenchStaffSummary(ContractModel):
    staff_id: str
    display_name: str | None = None


class WorkbenchReservation(ContractModel):
    reserved_by: WorkbenchStaffSummary
    expires_at: datetime


class WorkbenchOwnershipProjection(ContractModel):
    state: OwnershipState
    primary_assignee: WorkbenchStaffSummary | None = None
    coworkers: list[WorkbenchStaffSummary] = Field(default_factory=list)
    coworker_count: int = Field(default=0, ge=0)
    reservation: WorkbenchReservation | None = None
    accepted_at: datetime | None = None
    last_owner_activity_at: datetime | None = None
    requeue_eligible_at: datetime | None = None
    current_staff_access: CurrentStaffAccess
    pending_cowork_requests: int = Field(default=0, ge=0)
    pending_transfer_requests: int = Field(default=0, ge=0)


class WorkbenchPriorityReason(ContractModel):
    code: str
    summary: str
    source_refs: list[str] = Field(default_factory=list)


class WorkbenchPriorityProjection(ContractModel):
    level: WorkPriorityLevel
    rank: int = Field(ge=0)
    reasons: list[WorkbenchPriorityReason] = Field(default_factory=list)
    due_at: datetime | None = None
    is_overdue: bool = False
    computed_at: datetime


class WorkbenchCurrentWorkItem(ContractModel):
    work_item_id: str
    type: str
    status: str
    owner_role: WorkbenchResponsibility
    requested_outcome: str
    blocked_action: str | None = None
    due_at: datetime | None = None
    source_refs: list[str] = Field(default_factory=list)


class WorkbenchMissingInformation(ContractModel):
    kind: str
    code: str
    label: str
    attention: MissingInformationAttention
    blocked_action: str | None = None
    responsible_party: WorkbenchResponsibility
    source_refs: list[str] = Field(default_factory=list)


class WorkbenchRiskSignal(ContractModel):
    signal_id: str
    category: str
    code: str
    label: str
    attention_level: RiskAttentionLevel
    status: SignalReviewStatus
    summary: str
    source_refs: list[str] = Field(default_factory=list)


class WorkbenchIncompleteContext(ContractModel):
    interrupted_at: datetime
    last_meaningful_activity_at: datetime
    resume_point: str
    follow_up_due_at: datetime | None = None
    follow_up_status: str
    follow_up_attempts: int = Field(default=0, ge=0)
    expires_at: datetime | None = None
    retention_hold: bool = False


class WorkbenchWorkSummary(ContractModel):
    queue_key: str
    current_work_item: WorkbenchCurrentWorkItem | None = None
    primary_action_code: str | None = None
    primary_blocker: str | None = None
    missing_information: list[WorkbenchMissingInformation] = Field(default_factory=list)
    risk_signals: list[WorkbenchRiskSignal] = Field(default_factory=list)
    incomplete_context: WorkbenchIncompleteContext | None = None
    unread_claimant_messages: int = Field(default=0, ge=0)
    last_claimant_activity_at: datetime | None = None
    external_wait_count: int = Field(default=0, ge=0)


class WorkbenchWaitingExternalService(ContractModel):
    task_id: str
    service_identity: str
    requested_action: str
    status: str


class WorkbenchIntegrationSummary(ContractModel):
    claim_creation_status: str | None = None
    assessor_routing_status: str | None = None
    waiting_external_services: list[WorkbenchWaitingExternalService] = Field(default_factory=list)


class WorkbenchActionConfirmation(ContractModel):
    level: ConfirmationLevel
    message: str | None = None


class WorkbenchAllowedAction(ContractModel):
    action_code: str
    target_ref: str
    label: str
    purpose: str
    availability: ActionAvailability
    blocked_reason: str | None = None
    confirmation: WorkbenchActionConfirmation
    expected_effects: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    based_on_revision: int = Field(ge=1)


class WorkbenchSectionSummary(ContractModel):
    status: ResourceAvailability
    total: int = Field(default=0, ge=0)
    needs_attention: int = Field(default=0, ge=0)
    unread_count: int = Field(default=0, ge=0)
    session_count: int = Field(default=0, ge=0)
    limitation: str | None = None


class WorkbenchSectionSummaries(ContractModel):
    fields: WorkbenchSectionSummary
    conversation: WorkbenchSectionSummary
    evidence: WorkbenchSectionSummary
    reference_checks: WorkbenchSectionSummary
    external_services: WorkbenchSectionSummary
    activity: WorkbenchSectionSummary


class WorkbenchClaimListItem(ContractModel):
    claim_id: str
    display_reference: str
    revision: int = Field(ge=1)
    claimant: WorkbenchClaimantSummary
    incident: WorkbenchIncidentSummary
    lifecycle_state: ClaimLifecycleState
    workflow_state: WorkflowState
    ownership: WorkbenchOwnershipProjection
    priority_projection: WorkbenchPriorityProjection
    work_summary: WorkbenchWorkSummary
    integration_summary: WorkbenchIntegrationSummary
    tags: list[StaffTag] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkbenchClaimListResponse(ContractModel):
    items: list[WorkbenchClaimListItem]
    page: PageInfo


class WorkbenchClaimDetail(WorkbenchClaimListItem):
    claim_state: ClaimState
    allowed_actions: list[WorkbenchAllowedAction] = Field(default_factory=list)
    section_summaries: WorkbenchSectionSummaries
    customer_next_step: CustomerNextStep


class WorkbenchFieldItem(ContractModel):
    code: str
    field: StructuredFormField


class WorkbenchSignalDetail(WorkbenchRiskSignal):
    reason_codes: list[str] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


class WorkbenchExternalRequest(ContractModel):
    request: ExternalTaskRequest | None = None
    task: ExternalTaskRecord


class WorkbenchActivityEvent(ContractModel):
    event_id: str
    event_type: str
    actor_id: str | None = None
    summary: str
    source_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    resulting_revision: int | None = Field(default=None, ge=1)


class WorkbenchConversationSummary(ContractModel):
    conversation_id: str
    kind: WorkbenchConversationKind
    claim_id: str | None = None
    display_reference: str | None = None
    session_id: str
    status: str
    title: str
    summary: str | None = None
    unread_count: int = Field(default=0, ge=0)
    updated_at: datetime


ResourceItemT = TypeVar('ResourceItemT')


class WorkbenchResourcePage(ContractModel, Generic[ResourceItemT]):
    items: list[ResourceItemT]
    page: PageInfo
    status: ResourceAvailability = ResourceAvailability.AVAILABLE
    limitation: str | None = None


WorkbenchFieldsResponse = WorkbenchResourcePage[WorkbenchFieldItem]
WorkbenchSessionsResponse = WorkbenchResourcePage[WorkbenchSession]
WorkbenchMessagesResponse = WorkbenchResourcePage[MessageRecord]
WorkbenchEvidenceResponse = WorkbenchResourcePage[EvidenceRecord]
WorkbenchRetrievalsResponse = WorkbenchResourcePage[RetrievalRecord]
WorkbenchSignalsResponse = WorkbenchResourcePage[WorkbenchSignalDetail]
WorkbenchHandoffsResponse = WorkbenchResourcePage[WorkbenchHandoff]
WorkbenchWorkItemsResponse = WorkbenchResourcePage[StaffActionRecord]
WorkbenchCustomerUpdatesResponse = WorkbenchResourcePage[CustomerUpdateRecord]
WorkbenchExternalRequestsResponse = WorkbenchResourcePage[WorkbenchExternalRequest]
WorkbenchEventsResponse = WorkbenchResourcePage[WorkbenchActivityEvent]
WorkbenchCollaborationRequestsResponse = WorkbenchResourcePage[ClaimCollaborationRequest]
WorkbenchConversationsResponse = WorkbenchResourcePage[WorkbenchConversationSummary]


__all__ = [name for name in globals() if name.startswith('Workbench')]
