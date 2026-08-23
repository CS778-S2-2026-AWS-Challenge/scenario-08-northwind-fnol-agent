from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


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
    provider_model: str | None = None
    provider_request_id: str | None = None


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
