from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.models import (
    AgentAction,
    Channel,
    CustomerNextStep,
    CustomerSupport,
    EvidenceState,
    EvidenceSummary,
    FormSource,
    FormStatus,
    NeededFor,
    StateChange,
    Urgency,
    WorkflowState,
)


class ModelContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ModelRole(str, Enum):
    SYSTEM = 'system'
    USER = 'user'
    ASSISTANT = 'assistant'
    TOOL = 'tool'


class ModelMessage(ModelContract):
    role: ModelRole
    content: str


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


class ModelCapabilities(ModelContract):
    structured_output: bool = False
    tools: bool = False


class ModelRequest(ModelContract):
    messages: list[ModelMessage]
    response_schema: dict[str, object] | None = None
    tools: list[ModelTool] = Field(default_factory=list)


class ModelResponse(ModelContract):
    text: str | None = None
    structured_output: dict[str, object] | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
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


class ModelClaimContext(ModelContract):
    channel: Channel
    locale: str
    incident_type: str | None = None
    claim_state: ModelClaimStateContext
    form: dict[str, ModelFormFieldContext] = Field(default_factory=dict)
    known_field_codes: list[str] = Field(default_factory=list)
    evidence_summary: EvidenceSummary
    customer_next_step: CustomerNextStep


class ModelTurnContext(ModelContract):
    claim: ModelClaimContext
    message_text: str | None = None
    evidence_reference_count: int = Field(ge=0)
    professional_review_required: bool = False


class ModelProposedFormChange(ModelContract):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    needed_for: NeededFor = NeededFor.CURRENT_ACTION
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ModelAgentProposal(ModelContract):
    action: AgentAction
    reason_codes: list[str] = Field(min_length=1)
    customer_reason: str = Field(min_length=1, max_length=1000)
    customer_response: str = Field(min_length=1, max_length=5000)
    customer_next_step: CustomerNextStep
    form_changes: list[ModelProposedFormChange] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    proposed_signals: list[dict[str, object]] = Field(default_factory=list, max_length=0)
    required_tools: list[dict[str, object]] = Field(default_factory=list)
    next_action_requirements: list[str] = Field(default_factory=list)
    handoff_priority: str | None = None


class ModelGatewayErrorCode(str, Enum):
    TIMEOUT = 'timeout'
    AUTHENTICATION = 'authentication'
    RATE_LIMIT = 'rate_limit'
    PROVIDER = 'provider'
    MALFORMED_RESPONSE = 'malformed_response'
    UNSUPPORTED_CAPABILITY = 'unsupported_capability'
    CONFIGURATION = 'configuration'


_ERROR_MESSAGES = {
    ModelGatewayErrorCode.TIMEOUT: 'The model endpoint timed out.',
    ModelGatewayErrorCode.AUTHENTICATION: 'The model endpoint rejected authentication.',
    ModelGatewayErrorCode.RATE_LIMIT: 'The model endpoint rate limit was reached.',
    ModelGatewayErrorCode.PROVIDER: 'The model endpoint could not complete the request.',
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
