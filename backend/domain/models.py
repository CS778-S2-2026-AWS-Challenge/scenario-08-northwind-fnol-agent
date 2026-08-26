from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AgentAction(str, Enum):
    ASK = 'ASK'
    CLARIFY = 'CLARIFY'
    CONFIRM = 'CONFIRM'
    PROCEED = 'PROCEED'
    UPDATE = 'UPDATE'
    HANDOFF = 'HANDOFF'
    URGENT_HANDOFF = 'URGENT_HANDOFF'
    CREATE_CLAIM = 'CREATE_CLAIM'


class AuthorityOutcome(str, Enum):
    AUTHORISED = 'authorised'
    BLOCKED = 'blocked'
    REVIEW_REQUIRED = 'review_required'


class AgentProposalSource(str, Enum):
    CONTROLLED_AGENT = 'controlled_agent'
    MODEL_GATEWAY = 'model_gateway'


class Severity(str, Enum):
    UNASSESSED = 'unassessed'
    FAST_TRACK = 'fast_track'
    STANDARD = 'standard'
    COMPLEX = 'complex'


class Coverage(str, Enum):
    NOT_ASSESSED = 'not_assessed'
    CLEAR = 'clear'
    AMBIGUOUS = 'ambiguous'
    REVIEW_REQUIRED = 'review_required'


class EvidenceState(str, Enum):
    NOT_STARTED = 'not_started'
    RECEIVED = 'received'
    UNOFFICIAL = 'unofficial'
    INCOMPLETE = 'incomplete'
    PENDING_GENERATION = 'pending_generation'
    INCONSISTENT = 'inconsistent'


class FraudSignal(str, Enum):
    NONE = 'none'
    REVIEW_REQUIRED = 'review_required'


class CustomerSupport(str, Enum):
    SELF_SERVICE = 'self_service'
    GUIDED = 'guided'
    HUMAN_REQUESTED = 'human_requested'
    ACCESSIBILITY_REQUIRED = 'accessibility_required'


class Urgency(str, Enum):
    NORMAL = 'normal'
    URGENT = 'urgent'
    IMMEDIATE_SAFETY_RISK = 'immediate_safety_risk'


class WorkflowState(str, Enum):
    COLLECTING = 'collecting'
    READY_FOR_NEXT = 'ready_for_next'
    AWAITING_EVIDENCE = 'awaiting_evidence'
    PROFESSIONAL_REVIEW = 'professional_review'
    CREATED = 'created'


class Channel(str, Enum):
    WEB_AGENT = 'web_agent'


class SessionStatus(str, Enum):
    ACTIVE = 'active'
    PAUSED = 'paused'
    CLOSED = 'closed'


class ActorType(str, Enum):
    CLAIMANT = 'claimant'
    AGENT = 'agent'
    STAFF = 'staff'
    SYSTEM = 'system'


class MessageVisibility(str, Enum):
    CLAIMANT_VISIBLE = 'claimant_visible'
    SHARED = 'shared'
    INTERNAL_ONLY = 'internal_only'


class EvidenceStatus(str, Enum):
    RECEIVED = 'received'
    UNOFFICIAL = 'unofficial'
    INCOMPLETE = 'incomplete'
    PENDING_GENERATION = 'pending_generation'
    INCONSISTENT = 'inconsistent'


class EvidenceFileStatus(str, Enum):
    NOT_AVAILABLE = 'not_available'
    AWAITING_UPLOAD = 'awaiting_upload'
    UPLOADING = 'uploading'
    UPLOADED = 'uploaded'
    PROCESSING = 'processing'
    READY = 'ready'
    FAILED = 'failed'


class EvidenceSource(str, Enum):
    CLAIMANT = 'claimant'
    STAFF = 'staff'
    EXTERNAL_SYSTEM = 'external_system'


class FormSource(str, Enum):
    CLAIMANT = 'claimant'
    IMAGE = 'image'
    DOCUMENT = 'document'
    POLICY = 'policy'
    CLAIM_HISTORY = 'claim_history'
    INFERENCE = 'inference'
    STAFF = 'staff'


class FormStatus(str, Enum):
    PROPOSED = 'proposed'
    CONFIRMED = 'confirmed'
    DISPUTED = 'disputed'
    MISSING = 'missing'
    PENDING_GENERATION = 'pending_generation'


class NeededFor(str, Enum):
    CURRENT_ACTION = 'current_action'
    LATER_ACTION = 'later_action'


class ResponsibleParty(str, Enum):
    CLAIMANT = 'claimant'
    NORTHWIND = 'northwind'
    CLAIMS_PROFESSIONAL = 'claims_professional'
    EXTERNAL_PARTY = 'external_party'


class EvidenceWaitType(str, Enum):
    CLAIMANT = 'claimant'
    EXTERNAL_AGENCY = 'external_agency'
    INTERNAL = 'internal'


class ClaimCreationStatus(str, Enum):
    CREATED = 'created'
    PENDING = 'pending'
    FAILED = 'failed'


class IntegrationSource(str, Enum):
    FIXTURE = 'fixture'
    CONFIGURED_SERVICE = 'configured_service'


class AssessorRoutingStatus(str, Enum):
    ASSIGNED = 'assigned'
    QUEUED = 'queued'
    NOT_REQUIRED = 'not_required'
    FAILED = 'failed'


class SupportNeed(str, Enum):
    """Claimant-requested support need, used only by claimant support APIs."""

    HUMAN_REQUESTED = 'human_requested'
    ACCESSIBILITY_REQUIRED = 'accessibility_required'
    DISTRESS = 'distress'
    URGENT = 'urgent'


class HandoffTrigger(str, Enum):
    """Staff-visible reason an internal handoff was created."""

    CLAIMANT_SUPPORT_REQUEST = 'claimant_support_request'
    ACCESSIBILITY_NEED = 'accessibility_need'
    DISTRESS_SIGNAL = 'distress_signal'
    URGENT_SAFETY_RISK = 'urgent_safety_risk'
    PROFESSIONAL_REVIEW_REQUIRED = 'professional_review_required'


class PreferredChannel(str, Enum):
    IN_APP = 'in_app'
    EMAIL = 'email'
    PHONE = 'phone'
    SMS = 'sms'


class HandoffType(str, Enum):
    HUMAN_SUPPORT = 'human_support'
    URGENT_SUPPORT = 'urgent_support'
    PROFESSIONAL_REVIEW = 'professional_review'


class HandoffStatus(str, Enum):
    REQUESTED = 'requested'
    QUEUED = 'queued'
    ACCEPTED = 'accepted'
    IN_PROGRESS = 'in_progress'
    RESOLVED = 'resolved'
    CANCELLED = 'cancelled'


class HandoffPriority(str, Enum):
    STANDARD = 'standard'
    HIGH = 'high'
    URGENT = 'urgent'
    IMMEDIATE = 'immediate'


class ClaimState(ContractModel):
    severity: Severity = Severity.UNASSESSED
    coverage: Coverage = Coverage.NOT_ASSESSED
    evidence: EvidenceState = EvidenceState.NOT_STARTED
    fraud_signal: FraudSignal = FraudSignal.NONE
    customer_support: CustomerSupport = CustomerSupport.GUIDED
    urgency: Urgency = Urgency.NORMAL
    workflow_state: WorkflowState = WorkflowState.COLLECTING
    next_action: AgentAction = AgentAction.ASK


class ActorReference(ContractModel):
    actor_type: ActorType
    actor_id: str


class CustomerNextStep(ContractModel):
    status: str
    summary: str
    responsible_party: ResponsibleParty
    expected_by: datetime | None = None
    can_resume: bool = True
    required_items: list[str] = Field(default_factory=list)


class StructuredFormField(ContractModel):
    value: Any
    source: FormSource
    source_refs: list[str] = Field(default_factory=list)
    status: FormStatus
    needed_for: NeededFor
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    updated_at: datetime
    updated_by: ActorReference


class EvidenceSummary(ContractModel):
    received: int = 0
    pending: int = 0
    needs_attention: int = 0


class ExternalClaimResult(ContractModel):
    external_claim_id: str | None = None
    claim_number: str | None = None
    creation_status: ClaimCreationStatus
    route: str
    next_step: str
    source: IntegrationSource
    expected_by: datetime | None = None
    created_at: datetime


class AssessorRoutingResult(ContractModel):
    routing_status: AssessorRoutingStatus
    assessor_reference: str | None = None
    queue_reference: str | None = None
    next_step: str
    expected_by: datetime | None = None
    limitations: list[str] = Field(default_factory=list)


class WorkingClaim(ContractModel):
    claim_id: str
    customer_id: str
    revision: int = Field(default=1, ge=1)
    channel: Channel
    locale: str
    incident_type: str | None = None
    claim_state: ClaimState = Field(default_factory=ClaimState)
    form: dict[str, StructuredFormField] = Field(default_factory=dict)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    route: str | None = None
    assignee_id: str | None = Field(default=None, min_length=1, max_length=100)
    active_session_id: str | None = None
    external_claim: ExternalClaimResult | None = None
    external_claim_source_revision: int | None = Field(default=None, ge=1)
    external_claim_fingerprint: str | None = None
    assessor_routing: AssessorRoutingResult | None = None
    assessor_routing_fingerprint: str | None = None
    customer_next_step: CustomerNextStep
    created_at: datetime
    updated_at: datetime


class ResumePackage(ContractModel):
    summary: str | None = None
    unresolved_questions: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    prior_commitments: list[str] = Field(default_factory=list)
    customer_next_step: CustomerNextStep


class SessionRecord(ContractModel):
    session_id: str
    claim_id: str
    customer_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    summary: str | None = None
    unresolved_questions: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    prior_commitments: list[str] = Field(default_factory=list)
    context_revision: int = Field(default=1, ge=1)
    started_at: datetime
    last_active_at: datetime
    closed_at: datetime | None = None


class MessageRecord(ContractModel):
    """Durable message record; visibility is enforced before claimant projection."""

    message_id: str
    claim_id: str
    session_id: str
    client_message_id: str | None = None
    actor: ActorType
    visibility: MessageVisibility
    content: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None
    created_at: datetime


class StateChange(ContractModel):
    path: str = Field(min_length=1, max_length=200)
    to: Any


class ProposedFormChange(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    source: FormSource = FormSource.INFERENCE
    status: FormStatus = FormStatus.PROPOSED
    needed_for: NeededFor = NeededFor.CURRENT_ACTION
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AgentAuthority(ContractModel):
    proposed_by: str
    validated_by: str
    outcome: AuthorityOutcome


class ModelDecisionProvenance(ContractModel):
    runtime_profile: Literal['model_gateway'] = 'model_gateway'
    provider_model: str | None = Field(default=None, max_length=300)
    provider_request_id: str | None = Field(default=None, max_length=500)


class AgentDecisionRecord(ContractModel):
    decision_id: str
    claim_id: str
    session_id: str
    trigger_message_id: str
    action: AgentAction
    reason_codes: list[str] = Field(min_length=1)
    customer_reason: str = Field(min_length=1, max_length=1000)
    customer_response: str = Field(min_length=1, max_length=5000)
    state_changes: list[StateChange] = Field(default_factory=list)
    proposed_signals: list[dict[str, Any]] = Field(default_factory=list)
    required_tools: list[dict[str, Any]] = Field(default_factory=list)
    next_action_requirements: list[str] = Field(default_factory=list)
    handoff_priority: str | None = None
    handoff_id: str | None = None
    customer_next_step: CustomerNextStep
    authority: AgentAuthority
    proposal_source: AgentProposalSource = AgentProposalSource.CONTROLLED_AGENT
    model_provenance: ModelDecisionProvenance | None = None
    form_changes: dict[str, StructuredFormField] = Field(default_factory=dict)
    resulting_revision: int = Field(ge=1)
    created_at: datetime


class EvidenceRecord(ContractModel):
    evidence_id: str
    claim_id: str
    kind: str
    status: EvidenceStatus
    file_status: EvidenceFileStatus
    original_filename: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    source: EvidenceSource
    related_fields: list[str] = Field(default_factory=list)
    needed_for: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    claimant_note: str | None = None
    wait_type: EvidenceWaitType | None = None
    responsible_party: ResponsibleParty | None = None
    expected_by: datetime | None = None
    expected_timing: str | None = Field(default=None, max_length=200)
    context_summary: str | None = Field(default=None, max_length=1000)
    created_at: datetime
    updated_at: datetime


class HandoffEvidenceItem(ContractModel):
    """Staff handoff projection of evidence without copying storage provenance."""

    evidence_id: str
    kind: str
    status: EvidenceStatus
    file_status: EvidenceFileStatus
    source: EvidenceSource
    visibility: MessageVisibility
    original_filename: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    related_fields: list[str] = Field(default_factory=list)
    needed_for: list[str] = Field(default_factory=list)
    claimant_note: str | None = None


class HandoffPacket(ContractModel):
    """Staff-only transfer context built from the authoritative working claim."""

    incident_summary: str | None = None
    form_revision: int = Field(ge=1)
    form_snapshot: dict[str, StructuredFormField] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence: list[HandoffEvidenceItem] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    low_confidence_items: list[str] = Field(default_factory=list)
    policy_citation_refs: list[str] = Field(default_factory=list)
    history_evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    prior_customer_updates: list[str] = Field(default_factory=list)
    promised_next_step: str


class HandoffRecord(ContractModel):
    handoff_id: str
    claim_id: str
    type: HandoffType
    status: HandoffStatus
    priority: HandoffPriority
    queue: str
    # This is populated only for claimant-created support requests. Internal
    # professional-review handoffs use ``trigger`` without asserting claimant intent.
    support_need: SupportNeed | None = None
    trigger: HandoffTrigger
    preferred_channel: PreferredChannel | None = None
    reason_codes: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    requested_action: str = Field(min_length=1, max_length=1000)
    applied_rule: str = Field(min_length=1, max_length=100)
    packet: HandoffPacket
    source_message_id: str | None = None
    assigned_to: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    resolved_at: datetime | None = None


class ClaimantHandoff(ContractModel):
    """Customer-safe projection; staff routing reasons and packet details are excluded."""

    handoff_id: str
    status: HandoffStatus
    priority: HandoffPriority
    support_need: SupportNeed
    summary: str
    created_at: datetime


class WorkbenchSession(ContractModel):
    """Staff projection of saved resume context without repository ownership fields."""

    session_id: str
    claim_id: str
    status: SessionStatus
    summary: str | None = None
    unresolved_questions: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    prior_commitments: list[str] = Field(default_factory=list)
    context_revision: int = Field(ge=1)
    started_at: datetime
    last_active_at: datetime
    closed_at: datetime | None = None


class StaffActionStatus(str, Enum):
    OPEN = 'open'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'


class SignalDecisionValue(str, Enum):
    CONFIRMED = 'confirmed'
    DISMISSED = 'dismissed'
    OVERRIDDEN = 'overridden'
    RESOLVED = 'resolved'


class StaffActionResult(ContractModel):
    outcome: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    reason_codes: list[str] = Field(min_length=1, max_length=20)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class CustomerUpdateInput(ContractModel):
    summary: str = Field(min_length=1, max_length=1000)
    responsible_party: ResponsibleParty
    related_refs: list[str] = Field(default_factory=list, max_length=100)


class CustomerUpdateRecord(CustomerUpdateInput):
    update_id: str
    claim_id: str
    created_by: str
    created_at: datetime


class StaffActionRecord(ContractModel):
    action_id: str
    claim_id: str
    action_type: str = Field(min_length=1, max_length=100)
    status: StaffActionStatus
    assigned_to: str
    requested_outcome: str = Field(min_length=1, max_length=1000)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    result: StaffActionResult | None = None
    completed_by: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CreateStaffActionRequest(ContractModel):
    action_type: str = Field(min_length=1, max_length=100)
    assigned_to: str | None = Field(default=None, min_length=1, max_length=100)
    requested_outcome: str = Field(min_length=1, max_length=1000)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class UpdateStaffActionRequest(ContractModel):
    status: StaffActionStatus
    result: StaffActionResult | None = None
    state_changes: list[StateChange] = Field(default_factory=list, max_length=20)
    customer_update: CustomerUpdateInput | None = None


class StaffActionMutationResponse(ContractModel):
    action: StaffActionRecord
    revision: int = Field(ge=1)
    customer_update: CustomerUpdateRecord | None = None


class SignalDecisionRequest(ContractModel):
    decision: SignalDecisionValue
    reason_codes: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class SignalDecisionRecord(SignalDecisionRequest):
    signal_decision_id: str
    claim_id: str
    signal_id: str
    actor_id: str
    created_at: datetime


class SignalDecisionResponse(ContractModel):
    signal_decision: SignalDecisionRecord
    revision: int = Field(ge=1)


class WorkbenchHandoff(ContractModel):
    """Staff-only handoff projection including the complete transfer packet."""

    handoff_id: str
    claim_id: str
    type: HandoffType
    status: HandoffStatus
    priority: HandoffPriority
    queue: str
    support_need: SupportNeed | None = None
    trigger: HandoffTrigger
    preferred_channel: PreferredChannel | None = None
    reason_codes: list[str]
    reason: str
    requested_action: str
    applied_rule: str
    packet: HandoffPacket
    source_message_id: str | None = None
    assigned_to: str | None = None
    created_at: datetime
    accepted_at: datetime | None = None
    resolved_at: datetime | None = None


class AcceptHandoffRequest(ContractModel):
    assignee_id: str | None = Field(default=None, min_length=1, max_length=100)


class ResolveHandoffRequest(ContractModel):
    result: StaffActionResult
    state_changes: list[StateChange] = Field(default_factory=list, max_length=20)
    customer_update: CustomerUpdateInput


class HandoffMutationResponse(ContractModel):
    handoff: WorkbenchHandoff
    revision: int = Field(ge=1)
    staff_action: StaffActionRecord | None = None
    customer_update: CustomerUpdateRecord | None = None


class WorkbenchClaimDetail(ContractModel):
    """Authorised internal projection assembled from the shared claim repository."""

    claim_id: str
    revision: int = Field(ge=1)
    customer_reference: str
    channel: Channel
    locale: str
    incident_type: str | None = None
    claim_state: ClaimState
    form: dict[str, StructuredFormField]
    route: str | None = None
    active_session_id: str | None = None
    evidence_summary: EvidenceSummary
    evidence: list[EvidenceRecord]
    sessions: list[WorkbenchSession]
    messages: list[MessageRecord]
    decisions: list[AgentDecisionRecord]
    retrievals: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    handoffs: list[WorkbenchHandoff]
    staff_actions: list[dict[str, Any]]
    customer_updates: list[dict[str, Any]]
    external_claim: ExternalClaimResult | None = None
    assessor_routing: AssessorRoutingResult | None = None
    customer_next_step: CustomerNextStep
    created_at: datetime
    updated_at: datetime


class PageInfo(ContractModel):
    next_cursor: str | None = None


class WorkbenchClaimListItem(ContractModel):
    """Compact staff projection used to populate the workbench queue."""

    claim_id: str
    revision: int = Field(ge=1)
    customer_reference: str
    incident_type: str | None = None
    workflow_state: WorkflowState
    queue: str
    priority: HandoffPriority
    next_action: AgentAction
    route: str | None = None
    evidence_state: EvidenceState
    evidence_summary: EvidenceSummary
    pending_evidence: list[EvidenceRecord] = Field(default_factory=list)
    pending_evidence_count: int = Field(default=0, ge=0)
    pending_wait_types: list[EvidenceWaitType] = Field(default_factory=list)
    next_action_summary: str
    responsible_party: ResponsibleParty
    claim_creation_status: ClaimCreationStatus | None = None
    assessor_routing_status: AssessorRoutingStatus | None = None
    open_handoff_count: int = Field(ge=0)
    assignee_id: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkbenchClaimListResponse(ContractModel):
    items: list[WorkbenchClaimListItem]
    page: PageInfo


class PendingEvidenceReference(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=100)
    needed_for: list[str] = Field(default_factory=list, max_length=20)


class CreateExternalClaimRequest(ContractModel):
    working_claim_id: str = Field(min_length=1, max_length=100)
    claim_revision: int = Field(ge=1)
    authorised_decision_id: str = Field(min_length=1, max_length=100)
    confirmed_form: dict[str, StructuredFormField] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    pending_evidence: list[PendingEvidenceReference] = Field(
        default_factory=list,
        max_length=100,
    )
    route: str = Field(min_length=1, max_length=100)


class AssessorLocation(ContractModel):
    region: str = Field(min_length=1, max_length=100)


class RouteAssessorRequest(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    external_claim_id: str = Field(min_length=1, max_length=100)
    authorisation_ref: str = Field(min_length=1, max_length=100)
    requested_action: str = Field(min_length=1, max_length=100)
    location: AssessorLocation


class ClaimantEvidence(ContractModel):
    """Claimant-safe evidence projection with storage and extraction details removed."""

    evidence_id: str
    claim_id: str
    kind: str
    status: EvidenceStatus
    file_status: EvidenceFileStatus
    original_filename: str | None = None
    media_type: str | None = None
    size_bytes: int | None = None
    source: EvidenceSource
    related_fields: list[str] = Field(default_factory=list)
    needed_for: list[str] = Field(default_factory=list)
    claimant_note: str | None = None
    created_at: datetime
    updated_at: datetime


class RegisterEvidenceRequest(ContractModel):
    kind: str = Field(min_length=1, max_length=100)
    status: EvidenceStatus
    related_fields: list[str] = Field(default_factory=list, max_length=50)
    needed_for: list[str] = Field(default_factory=list, max_length=20)
    claimant_note: str | None = Field(default=None, max_length=1000)


class RequestEvidenceUploadRequest(ContractModel):
    kind: str = Field(min_length=1, max_length=100)
    original_filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)


class CompleteEvidenceUploadRequest(ContractModel):
    upload_checksum: str = Field(pattern=r'^sha256:[0-9a-fA-F]{64}$')


class EvidenceFactProposal(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class CompleteEvidenceProcessingRequest(ContractModel):
    facts: list[EvidenceFactProposal] = Field(min_length=1, max_length=50)


class EvidenceFactDecisionRequest(ContractModel):
    field_codes: list[str] = Field(min_length=1, max_length=50)
    decision: Literal['confirmed', 'rejected']


class CreateSupportRequest(ContractModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    support_need: SupportNeed
    preferred_channel: PreferredChannel | None = None


class HandoffDeliveryState(str, Enum):
    DELIVERED = 'delivered'
    QUEUED_LOCALLY = 'queued_locally'


class HandoffDelivery(ContractModel):
    """Claimant-safe statement of whether the staff queue system was notified.

    `queued_locally` means the notification service could not be reached. The
    handoff is still saved and still in the staff queue, so the request is not
    lost; only the push notification is missing.
    """

    state: HandoffDeliveryState
    limitations: list[str] = Field(default_factory=list, max_length=10)


class SupportRequestResponse(ContractModel):
    handoff: ClaimantHandoff
    revision: int
    customer_next_step: CustomerNextStep
    delivery: HandoffDelivery


class EvidenceListResponse(ContractModel):
    claim_id: str
    revision: int
    items: list[ClaimantEvidence]
    customer_next_step: CustomerNextStep


class EvidenceMutationResponse(ContractModel):
    evidence: ClaimantEvidence
    revision: int
    customer_next_step: CustomerNextStep


class UploadTarget(ContractModel):
    method: Literal['PUT'] = 'PUT'
    url: str
    headers: dict[str, str]
    expires_at: datetime


class UploadConstraints(ContractModel):
    max_size_bytes: int
    allowed_media_types: list[str]


class EvidenceUploadResponse(ContractModel):
    evidence_id: str
    revision: int
    upload: UploadTarget
    constraints: UploadConstraints
    customer_next_step: CustomerNextStep


class EvidenceCompleteResponse(ContractModel):
    evidence: ClaimantEvidence
    revision: int
    status_url: str
    customer_next_step: CustomerNextStep


class EvidenceProcessingResponse(ContractModel):
    evidence_id: str
    revision: int
    file_status: EvidenceFileStatus
    proposed_fields: dict[str, StructuredFormField]


class EvidenceFactDecisionResponse(ContractModel):
    evidence_id: str
    revision: int
    decision: Literal['confirmed', 'rejected']
    updated_fields: dict[str, StructuredFormField]


class CreateClaimRequest(ContractModel):
    channel: Channel = Channel.WEB_AGENT
    locale: str = Field(default='en-NZ', min_length=2, max_length=35)
    incident_type: str | None = Field(default=None, max_length=100)


class StartSessionRequest(ContractModel):
    intent: str = Field(default='resume', min_length=1, max_length=50)


NonEmptyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]


class TextMessageContent(ContractModel):
    type: Literal['text'] = 'text'
    text: NonEmptyText


class CreateMessageRequest(ContractModel):
    client_message_id: str = Field(min_length=1, max_length=200)
    content: TextMessageContent | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def require_content_or_evidence(self) -> 'CreateMessageRequest':
        if self.content is None and not self.evidence_refs:
            raise ValueError('A text message or evidence reference is required.')
        return self


class CreateStaffMessageRequest(ContractModel):
    content: TextMessageContent
    in_reply_to: str | None = None


class FormUpdate(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    status: FormStatus = FormStatus.CONFIRMED
    correction_reason: str | None = Field(default=None, max_length=500)


class FormPatchRequest(ContractModel):
    updates: list[FormUpdate] = Field(min_length=1, max_length=50)


class FormConfirmationRequest(ContractModel):
    field_codes: list[str] = Field(min_length=1, max_length=50)


class ClaimantClaim(ContractModel):
    claim_id: str
    revision: int
    incident_type: str | None = None
    workflow_state: WorkflowState
    form: dict[str, StructuredFormField]
    evidence_summary: EvidenceSummary
    external_claim: ExternalClaimResult | None = None
    customer_next_step: CustomerNextStep
    handoff: ClaimantHandoff | None = None
    created_at: datetime
    updated_at: datetime


class ClaimListItem(ContractModel):
    claim_id: str
    revision: int
    incident_type: str | None = None
    workflow_state: WorkflowState
    external_claim: ExternalClaimResult | None = None
    customer_next_step: CustomerNextStep
    created_at: datetime
    updated_at: datetime
    can_resume: bool


class ClaimListResponse(ContractModel):
    items: list[ClaimListItem]
    page: PageInfo


class ClaimantSession(ContractModel):
    session_id: str
    claim_id: str
    status: SessionStatus
    resume: ResumePackage
    started_at: datetime
    last_active_at: datetime
    closed_at: datetime | None = None


class CreateClaimResponse(ContractModel):
    claim: ClaimantClaim
    session: ClaimantSession


class FormPatchResponse(ContractModel):
    claim_id: str
    revision: int
    updated_fields: dict[str, StructuredFormField]
    customer_next_step: CustomerNextStep


class ClaimantMessage(ContractModel):
    message_id: str
    actor: ActorType
    content: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None
    created_at: datetime


class FormChange(ContractModel):
    field_code: str
    field: StructuredFormField


class ClaimantDecision(ContractModel):
    decision_id: str
    action: AgentAction
    reason_codes: list[str]
    customer_reason: str
    customer_next_step: CustomerNextStep


class MessageTurnResponse(ContractModel):
    claim_id: str
    session_id: str
    claim_revision: int
    claimant_message: ClaimantMessage
    agent_message: ClaimantMessage | None = None
    form_changes: list[FormChange]
    decision: ClaimantDecision | None = None
    handoff: dict[str, Any] | None = None


class MessageListResponse(ContractModel):
    items: list[ClaimantMessage]
    page: PageInfo


class StaffMessageResponse(ContractModel):
    claim_id: str
    session_id: str
    claim_revision: int
    message: MessageRecord


class FormConfirmationResponse(ContractModel):
    claim_id: str
    revision: int
    confirmed_fields: dict[str, StructuredFormField]
    decision: ClaimantDecision | None = None
    customer_next_step: CustomerNextStep


class ClaimCreationResponse(ContractModel):
    claim_id: str
    revision: int = Field(ge=1)
    decision: ClaimantDecision
    external_claim: ExternalClaimResult
    customer_next_step: CustomerNextStep


class DemoResetResponse(ContractModel):
    status: Literal['reset']
    cleared: dict[str, int]


class DemoSeedResponse(ContractModel):
    status: Literal['seeded']
    scenario_ids: list[str]
    claim_ids: list[str]
