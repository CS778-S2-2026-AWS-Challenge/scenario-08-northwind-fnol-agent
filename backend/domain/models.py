from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class WorkingClaim(ContractModel):
    claim_id: str
    customer_id: str
    revision: int = Field(default=1, ge=1)
    channel: Channel
    locale: str
    incident_type: str | None = None
    claim_state: ClaimState = Field(default_factory=ClaimState)
    form: dict[str, StructuredFormField] = Field(default_factory=dict)
    route: str | None = None
    active_session_id: str | None = None
    external_claim: dict[str, Any] | None = None
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


class CreateClaimRequest(ContractModel):
    channel: Channel = Channel.WEB_AGENT
    locale: str = Field(default='en-NZ', min_length=2, max_length=35)
    incident_type: str | None = Field(default=None, max_length=100)


class StartSessionRequest(ContractModel):
    intent: str = Field(default='resume', min_length=1, max_length=50)


class FormUpdate(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    status: FormStatus = FormStatus.CONFIRMED
    correction_reason: str | None = Field(default=None, max_length=500)


class FormPatchRequest(ContractModel):
    updates: list[FormUpdate] = Field(min_length=1, max_length=50)


class ClaimantClaim(ContractModel):
    claim_id: str
    revision: int
    incident_type: str | None = None
    workflow_state: WorkflowState
    form: dict[str, StructuredFormField]
    evidence_summary: EvidenceSummary
    external_claim: dict[str, Any] | None = None
    customer_next_step: CustomerNextStep
    created_at: datetime
    updated_at: datetime


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
