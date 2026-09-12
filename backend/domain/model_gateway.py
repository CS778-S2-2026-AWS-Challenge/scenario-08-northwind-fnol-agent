from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.models import (
    AgentAction,
    AssertionRelation,
    Channel,
    ContentsLossType,
    ContentsOwnership,
    CustomerNextStep,
    CustomerSupport,
    EvidenceState,
    EvidenceSummary,
    FactPrecision,
    FactResolutionState,
    FieldSelectionState,
    FormSource,
    FormStatus,
    MoneyAmount,
    NeededFor,
    StateChange,
    Urgency,
    WorkflowState,
)

CLAIMANT_AGENT_PURPOSE = 'agent_turn'
CLAIMANT_AGENT_PRIVACY_CLASS = 'synthetic_fnol'
STAFF_AGENT_PURPOSE = 'staff_assistant'
STAFF_AGENT_PRIVACY_CLASS = 'staff_internal_fnol'


class ModelContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ModelRole(str, Enum):
    SYSTEM = 'system'
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'


class ModelMessage(ModelContract):
    role: ModelRole
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ModelTool(ModelContract):
    name: str
    description: str
    input_schema: dict[str, object]


class ModelToolCall(ModelContract):
    call_id: str
    name: str
    arguments: dict[str, object]


class ModelUsage(ModelContract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelCompletionStatus(str, Enum):
    COMPLETE = 'complete'
    INCOMPLETE = 'incomplete'
    REFUSED = 'refused'
    UNKNOWN = 'unknown'


class ModelCapabilities(ModelContract):
    structured_output: bool = False
    tools: bool = False


class ModelProfileStatus(str, Enum):
    CONFIGURED = 'configured'
    DEGRADED = 'degraded'
    UNAVAILABLE = 'unavailable'


class ModelProfile(ModelContract):
    """Provider-neutral model selection metadata.

    The profile contains references and capabilities only. Credentials and provider
    SDK configuration remain outside the domain contract.
    """

    profile_id: str = Field(min_length=1, max_length=100)
    protocol: str = Field(min_length=1, max_length=50)
    provider: str = Field(min_length=1, max_length=100)
    model_identifier: str = Field(min_length=1, max_length=300)
    credential_reference: str | None = Field(default=None, max_length=200)
    purpose: str = Field(min_length=1, max_length=100)
    privacy_class: str = Field(min_length=1, max_length=100)
    capabilities: ModelCapabilities
    timeout_seconds: float = Field(gt=0)
    prompt_version: str = Field(min_length=1, max_length=100)
    evaluation_status: ModelProfileStatus = ModelProfileStatus.CONFIGURED


class ModelRequest(ModelContract):
    model_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    messages: list[ModelMessage]
    response_schema: dict[str, object] | None = None
    tools: list[ModelTool] = Field(default_factory=list)
    required_tool_name: str | None = Field(default=None, min_length=1, max_length=100)
    purpose: str = Field(default=CLAIMANT_AGENT_PURPOSE, min_length=1, max_length=100)
    prompt_version: str = Field(default='current', min_length=1, max_length=100)
    privacy_class: str = Field(
        default=CLAIMANT_AGENT_PRIVACY_CLASS,
        min_length=1,
        max_length=100,
    )
    required_capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)


class ModelResponse(ModelContract):
    text: str | None = None
    structured_output: dict[str, object] | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    completion_status: ModelCompletionStatus = ModelCompletionStatus.UNKNOWN
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    provider_model: str | None = Field(default=None, max_length=300)
    provider_request_id: str | None = Field(default=None, max_length=500)


class ModelClaimStateContext(ModelContract):
    evidence: EvidenceState
    customer_support: CustomerSupport
    urgency: Urgency
    workflow_state: WorkflowState
    next_action: AgentAction


class ModelFormFieldContext(ModelContract):
    value: Any
    source: FormSource
    status: FormStatus
    needed_for: NeededFor
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: FactPrecision = FactPrecision.EXACT
    source_refs: list[str] = Field(default_factory=list)


class ModelClaimContext(ModelContract):
    channel: Channel
    locale: str
    incident_type: str | None = None
    claim_state: ModelClaimStateContext
    form: dict[str, ModelFormFieldContext] = Field(default_factory=dict)
    contents_items: list[ModelContentsItemContext] = Field(default_factory=list)
    known_field_codes: list[str] = Field(default_factory=list)
    evidence_summary: EvidenceSummary
    customer_next_step: CustomerNextStep


class ModelFieldSelectionContext(ModelContract):
    field_code: str
    selection_state: FieldSelectionState
    value_state: FormStatus


class ModelContentsItemContext(ModelContract):
    item_id: str
    description: str
    category: str
    quantity: int
    loss_type: ContentsLossType
    ownership: ContentsOwnership
    estimated_value: MoneyAmount | None = None
    source: FormSource
    source_refs: list[str] = Field(default_factory=list)
    status: FormStatus
    resolution_state: FactResolutionState


class ModelBranchContext(ModelContract):
    field_registry_version: str
    branch_rules_version: str
    selected_family: str | None = None
    unresolved_family_conflict: list[str] = Field(default_factory=list)
    active_branches: list[str] = Field(default_factory=list)
    candidate_branches: list[str] = Field(default_factory=list)
    allowed_field_codes: list[str] = Field(default_factory=list)
    field_selection: list[ModelFieldSelectionContext] = Field(default_factory=list)
    work_item_intents: list[dict[str, Any]] = Field(default_factory=list)
    interruption_result: dict[str, Any] = Field(default_factory=dict)
    permitted_actions: list[AgentAction] = Field(default_factory=list)
    permitted_tools: list[str] = Field(default_factory=list)
    satisfied_requirements: list[str] = Field(default_factory=list)
    missing_required_now: list[str] = Field(default_factory=list)
    pending_later: list[str] = Field(default_factory=list)
    next_required_item: str | None = None
    ready: bool = False


class ModelTurnContext(ModelContract):
    claim: ModelClaimContext
    message_text: str | None = None
    evidence_reference_count: int = Field(ge=0)
    professional_review_required: bool = False
    provenance_messages: list[ModelProvenanceMessage] = Field(default_factory=list)
    conversation_history: list[ModelProvenanceMessage] = Field(default_factory=list)
    field_value_contracts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    branch: ModelBranchContext | None = None
    knowledge_status: Literal[
        'not_requested', 'evidence_found', 'no_evidence', 'timeout', 'unavailable'
    ] = 'not_requested'
    knowledge_citations: list[ModelKnowledgeCitation] = Field(default_factory=list)
    knowledge_limitations: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class ModelKnowledgeCitation(ModelContract):
    document_id: str
    chunk_id: str
    title: str
    section_path: str
    source_uri: str
    version: str
    checksum: str
    text: str


class ModelProvenanceMessage(ModelContract):
    message_id: str
    content: str


class ModelProposedFormChange(ModelContract):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    needed_for: NeededFor = NeededFor.CURRENT_ACTION
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: FactPrecision = FactPrecision.EXACT
    relation: AssertionRelation | None = None
    reported_text: str | None = Field(default=None, max_length=5000)


class ModelProposedContentsItem(ModelContract):
    item_id: str | None = Field(default=None, min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1)
    loss_type: ContentsLossType
    ownership: ContentsOwnership
    estimated_value: MoneyAmount | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    relation: AssertionRelation | None = None
    reported_text: str | None = Field(default=None, max_length=5000)


class ModelAgentProposal(ModelContract):
    action: AgentAction
    reason_codes: list[str] = Field(min_length=1)
    customer_reason: str = Field(min_length=1, max_length=1000)
    customer_response: str = Field(min_length=1, max_length=5000)
    customer_next_step: CustomerNextStep
    form_changes: list[ModelProposedFormChange] = Field(default_factory=list)
    contents_item_changes: list[ModelProposedContentsItem] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    proposed_signals: list[dict[str, object]] = Field(default_factory=list, max_length=0)
    required_tools: list[dict[str, object]] = Field(default_factory=list)
    next_action_requirements: list[str] = Field(default_factory=list)
    handoff_priority: str | None = None


class ModelRuntimeProposal(ModelContract):
    """Strict target-runtime proposal returned after the staged tool call.

    The model may propose claimant-visible conversation content and registered fact
    candidates. Runtime remains responsible for resolution, authority, revision,
    persistence, and every side effect.
    """

    action_code: Literal['conversation.answer', 'human.create_handoff']
    runtime_action_code: Literal[
        'runtime.continue',
        'runtime.wait_for_user',
        'runtime.pause_for_review',
    ]
    reason_codes: list[str] = Field(min_length=1)
    customer_reason: str = Field(min_length=1, max_length=1000)
    customer_response: str = Field(min_length=1, max_length=5000)
    customer_next_step: CustomerNextStep
    form_changes: list[ModelProposedFormChange] = Field(default_factory=list)
    contents_item_changes: list[ModelProposedContentsItem] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    handoff_priority: str | None = None


class ModelGatewayErrorCode(str, Enum):
    TIMEOUT = 'timeout'
    AUTHENTICATION = 'authentication'
    RATE_LIMIT = 'rate_limit'
    PROVIDER = 'provider'
    INCOMPLETE_RESPONSE = 'incomplete_response'
    REFUSED_RESPONSE = 'refused_response'
    MALFORMED_RESPONSE = 'malformed_response'
    UNSUPPORTED_CAPABILITY = 'unsupported_capability'
    CONFIGURATION = 'configuration'


_ERROR_MESSAGES = {
    ModelGatewayErrorCode.TIMEOUT: 'The model endpoint timed out.',
    ModelGatewayErrorCode.AUTHENTICATION: 'The model endpoint rejected authentication.',
    ModelGatewayErrorCode.RATE_LIMIT: 'The model endpoint rate limit was reached.',
    ModelGatewayErrorCode.PROVIDER: 'The model endpoint could not complete the request.',
    ModelGatewayErrorCode.INCOMPLETE_RESPONSE: (
        'The model endpoint returned an incomplete response.'
    ),
    ModelGatewayErrorCode.REFUSED_RESPONSE: 'The model endpoint refused the request.',
    ModelGatewayErrorCode.MALFORMED_RESPONSE: 'The model endpoint returned an invalid response.',
    ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY: (
        'The selected model endpoint does not support a required capability.'
    ),
    ModelGatewayErrorCode.CONFIGURATION: 'The model gateway configuration is invalid.',
}


class ModelGatewayError(RuntimeError):
    def __init__(self, code: ModelGatewayErrorCode, *, retryable: bool = False) -> None:
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code
        self.retryable = retryable


class ModelGateway(Protocol):
    @property
    def capabilities(self) -> ModelCapabilities:
        raise NotImplementedError

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError
