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


class ClaimCreationStatus(str, Enum):
    CREATED = 'created'
    PENDING = 'pending'
    FAILED = 'failed'


class AssessorRoutingStatus(str, Enum):
    ASSIGNED = 'assigned'
    QUEUED = 'queued'
    NOT_REQUIRED = 'not_required'
    FAILED = 'failed'


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


class AgentDecisionRecord(ContractModel):
    decision_id: str
    claim_id: str
    session_id: str
    trigger_message_id: str
    action: AgentAction
    reason_codes: list[str] = Field(min_length=1)
    customer_reason: str = Field(min_length=1, max_length=1000)
    state_changes: list[StateChange] = Field(default_factory=list)
    proposed_signals: list[dict[str, Any]] = Field(default_factory=list)
    required_tools: list[dict[str, Any]] = Field(default_factory=list)
    next_action_requirements: list[str] = Field(default_factory=list)
    handoff_priority: str | None = None
    customer_next_step: CustomerNextStep
    authority: AgentAuthority
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
    created_at: datetime
    updated_at: datetime


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


class PageInfo(ContractModel):
    next_cursor: str | None = None


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
    agent_message: ClaimantMessage
    form_changes: list[FormChange]
    decision: ClaimantDecision
    handoff: dict[str, Any] | None = None


class MessageListResponse(ContractModel):
    items: list[ClaimantMessage]
    page: PageInfo


class FormConfirmationResponse(ContractModel):
    claim_id: str
    revision: int
    confirmed_fields: dict[str, StructuredFormField]
    decision: ClaimantDecision | None = None
    customer_next_step: CustomerNextStep
