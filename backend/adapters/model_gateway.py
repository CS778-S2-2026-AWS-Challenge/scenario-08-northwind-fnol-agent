import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelProfile,
    ModelProfileStatus,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelToolCall,
    ModelUsage,
)


@dataclass(frozen=True, slots=True)
class ModelGatewayConfig:
    base_url: str
    model: str
    credential_environment_variable: str | None
    timeout_seconds: float
    capabilities: ModelCapabilities
    profile: ModelProfile

    def __post_init__(self) -> None:
        try:
            url = httpx.URL(self.base_url)
        except httpx.InvalidURL:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
        if url.scheme not in {'http', 'https'} or not url.host or url.userinfo:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if not self.model.strip() or self.timeout_seconds <= 0:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if self.credential_environment_variable is not None and not re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_]*', self.credential_environment_variable
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if (
            self.profile.model_identifier != self.model
            or self.profile.credential_reference != self.credential_environment_variable
            or self.profile.capabilities != self.capabilities
            or self.profile.timeout_seconds != self.timeout_seconds
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)


ModelGatewayFactory = Callable[[ModelGatewayConfig], ModelGateway]


class ModelGatewayRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ModelGatewayFactory] = {}

    def register(self, protocol: str, factory: ModelGatewayFactory) -> None:
        normalized = protocol.strip().lower()
        if not normalized or normalized in self._factories:
            raise ValueError('Model protocol names must be non-empty and unique.')
        self._factories[normalized] = factory

    def create(self, protocol: str, config: ModelGatewayConfig) -> ModelGateway:
        normalized = protocol.strip().lower()
        if normalized != config.profile.protocol.strip().lower():
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        factory = self._factories.get(normalized)
        if factory is None:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return factory(config)


def _validate_request_profile(config: ModelGatewayConfig, request: ModelRequest) -> None:
    profile = config.profile
    if profile.evaluation_status is not ModelProfileStatus.CONFIGURED:
        raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
    if (
        request.purpose != profile.purpose
        or request.privacy_class != profile.privacy_class
        or request.prompt_version != profile.prompt_version
    ):
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    required = request.required_capabilities
    if required.structured_output and not profile.capabilities.structured_output:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    if required.tools and not profile.capabilities.tools:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)


class OpenAICompatibleModelGateway:
    def __init__(
        self,
        config: ModelGatewayConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._config.capabilities

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._validate_capabilities(request)
        headers = {'Accept': 'application/json'}
        credential_name = self._config.credential_environment_variable
        if credential_name:
            credential = os.getenv(credential_name)
            if not credential:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            headers['Authorization'] = f'Bearer {credential}'

        try:
            with httpx.Client(
                base_url=f'{self._config.base_url.rstrip("/")}/',
                timeout=self._config.timeout_seconds,
                transport=self._transport,
                headers=headers,
            ) as client:
                response = client.post('chat/completions', json=self._request_payload(request))
        except httpx.TimeoutException:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True) from None
        except httpx.RequestError:
            raise ModelGatewayError(ModelGatewayErrorCode.PROVIDER, retryable=True) from None

        self._raise_for_status(response.status_code)
        try:
            payload = response.json()
            return self._normalise_response(payload, request, response.headers)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None

    def _validate_capabilities(self, request: ModelRequest) -> None:
        _validate_request_profile(self._config, request)
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools and not self.capabilities.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        messages: list[dict[str, object]] = []
        for message in request.messages:
            item: dict[str, object] = {
                'role': message.role.value,
                'content': message.content,
            }
            if message.tool_calls:
                item['tool_calls'] = [
                    {
                        'id': tool.call_id,
                        'type': 'function',
                        'function': {
                            'name': tool.name,
                            'arguments': json.dumps(
                                tool.arguments,
                                separators=(',', ':'),
                            ),
                        },
                    }
                    for tool in message.tool_calls
                ]
            if message.tool_call_id is not None:
                item['tool_call_id'] = message.tool_call_id
            if message.name is not None:
                item['name'] = message.name
            messages.append(item)
        payload: dict[str, object] = {
            'model': self._config.model,
            'messages': messages,
        }
        if request.response_schema is not None:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'northwind_agent_proposal',
                    'strict': True,
                    'schema': self._strict_response_schema(request.response_schema),
                },
            }
        if request.tools:
            payload['tools'] = [
                {
                    'type': 'function',
                    'function': {
                        'name': tool.name,
                        'description': tool.description,
                        'parameters': tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
        return payload

    @classmethod
    def _strict_response_schema(cls, value: object) -> object:
        """Translate a domain JSON schema into the OpenAI strict-schema subset.

        Pydantic represents optional fields as nullable schemas with defaults and omits
        those fields from ``required``. OpenAI strict structured outputs instead require
        every declared property to be present while using ``null`` for optional values.
        This transport-only translation keeps the provider rule out of domain contracts.
        """

        if isinstance(value, list):
            return [cls._strict_response_schema(item) for item in value]
        if not isinstance(value, dict):
            return value

        normalised: dict[str, object] = {}
        for key, item in value.items():
            if key == 'default':
                continue
            if key in {'$defs', 'properties'} and isinstance(item, dict):
                normalised[key] = {
                    name: cls._strict_response_schema(member) for name, member in item.items()
                }
            else:
                normalised[key] = cls._strict_response_schema(item)
        schema_keywords = {
            '$ref',
            'allOf',
            'anyOf',
            'const',
            'enum',
            'oneOf',
            'type',
        }
        if not schema_keywords.intersection(normalised):
            normalised['anyOf'] = [
                {'type': 'string'},
                {'type': 'number'},
                {'type': 'boolean'},
                {'type': 'null'},
            ]
        properties = normalised.get('properties')
        if isinstance(properties, dict):
            normalised['required'] = list(properties)
            normalised['additionalProperties'] = False
        elif normalised.get('type') == 'object':
            normalised['properties'] = {}
            normalised['required'] = []
            normalised['additionalProperties'] = False
        return normalised

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ModelGatewayError(ModelGatewayErrorCode.AUTHENTICATION)
        if status_code == 429:
            raise ModelGatewayError(ModelGatewayErrorCode.RATE_LIMIT, retryable=True)
        raise ModelGatewayError(
            ModelGatewayErrorCode.PROVIDER,
            retryable=status_code >= 500,
        )

    @staticmethod
    def _normalise_response(
        payload: object,
        request: ModelRequest,
        headers: httpx.Headers,
    ) -> ModelResponse:
        if not isinstance(payload, dict):
            raise TypeError
        choices = payload['choices']
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise TypeError
        choice = choices[0]
        message = choice['message']
        if not isinstance(message, dict):
            raise TypeError
        content = message.get('content')
        if content is not None and not isinstance(content, str):
            raise TypeError

        refusal = message.get('refusal')
        if refusal is not None and not isinstance(refusal, str):
            raise TypeError
        finish_reason = choice.get('finish_reason')
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise TypeError
        completion_status = OpenAICompatibleModelGateway._completion_status(
            finish_reason,
            refused=refusal is not None,
        )

        structured_output: dict[str, object] | None = None
        if (
            request.response_schema is not None
            and completion_status is ModelCompletionStatus.COMPLETE
            and not message.get('tool_calls')
        ):
            if content is None:
                raise TypeError
            parsed_content = json.loads(content)
            if not isinstance(parsed_content, dict):
                raise TypeError
            structured_output = parsed_content

        tool_calls = OpenAICompatibleModelGateway._normalise_tool_calls(
            message.get('tool_calls', [])
        )
        usage = OpenAICompatibleModelGateway._normalise_usage(payload.get('usage'))
        model = payload.get('model')
        if model is not None and not isinstance(model, str):
            raise TypeError
        request_id = headers.get('x-request-id') or payload.get('id')
        if request_id is not None and not isinstance(request_id, str):
            raise TypeError
        return ModelResponse(
            text=content,
            structured_output=structured_output,
            tool_calls=tool_calls,
            completion_status=completion_status,
            finish_reason=finish_reason,
            usage=usage,
            provider_model=model,
            provider_request_id=request_id,
        )

    @staticmethod
    def _completion_status(
        finish_reason: str | None,
        *,
        refused: bool,
    ) -> ModelCompletionStatus:
        if refused or finish_reason == 'content_filter':
            return ModelCompletionStatus.REFUSED
        if finish_reason in {'stop', 'tool_calls'}:
            return ModelCompletionStatus.COMPLETE
        if finish_reason in {'length', 'max_tokens'}:
            return ModelCompletionStatus.INCOMPLETE
        return ModelCompletionStatus.UNKNOWN

    @staticmethod
    def _normalise_tool_calls(value: object) -> list[ModelToolCall]:
        if not isinstance(value, list):
            raise TypeError
        normalised: list[ModelToolCall] = []
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get('function'), dict):
                raise TypeError
            function = item['function']
            arguments = json.loads(function['arguments'])
            if not isinstance(arguments, dict):
                raise TypeError
            normalised.append(
                ModelToolCall(
                    call_id=item['id'],
                    name=function['name'],
                    arguments=arguments,
                )
            )
        return normalised

    @staticmethod
    def _normalise_usage(value: object) -> ModelUsage | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError
        return ModelUsage(
            input_tokens=value.get('prompt_tokens'),
            output_tokens=value.get('completion_tokens'),
            total_tokens=value.get('total_tokens'),
        )


class BedrockConverseModelGateway:
    """HTTP adapter for the Bedrock Runtime Converse API using a bearer token."""

    _STRUCTURED_OUTPUT_TOOL = 'northwind_agent_proposal'

    def __init__(
        self,
        config: ModelGatewayConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._config.capabilities

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._validate_capabilities(request)
        credential_name = self._config.credential_environment_variable
        if not credential_name:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        credential = os.getenv(credential_name)
        if not credential:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)

        system, messages = self._request_messages(request)
        payload: dict[str, object] = {'messages': messages}
        if system:
            payload['system'] = [{'text': system}]
        if request.response_schema is not None:
            payload['toolConfig'] = {
                'tools': [
                    {
                        'toolSpec': {
                            'name': self._STRUCTURED_OUTPUT_TOOL,
                            'description': (
                                'Return the structured Northwind Agent proposal for this turn.'
                            ),
                            'inputSchema': {'json': request.response_schema},
                        }
                    }
                ],
                'toolChoice': {'tool': {'name': self._STRUCTURED_OUTPUT_TOOL}},
            }
        try:
            with httpx.Client(
                base_url=f'{self._config.base_url.rstrip("/")}/',
                timeout=self._config.timeout_seconds,
                transport=self._transport,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {credential}',
                },
            ) as client:
                response = client.post(
                    f'model/{quote(self._config.model, safe="")}/converse',
                    json=payload,
                )
        except httpx.TimeoutException:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True) from None
        except httpx.RequestError:
            raise ModelGatewayError(ModelGatewayErrorCode.PROVIDER, retryable=True) from None

        self._raise_for_status(response.status_code)
        try:
            payload = response.json()
            return self._normalise_response(payload, request, response.headers)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None

    def _validate_capabilities(self, request: ModelRequest) -> None:
        _validate_request_profile(self._config, request)
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    @staticmethod
    def _request_messages(request: ModelRequest) -> tuple[str, list[dict[str, object]]]:
        system_parts: list[str] = []
        messages: list[dict[str, object]] = []
        for message in request.messages:
            if message.role is ModelRole.SYSTEM:
                system_parts.append(message.content or '')
                continue
            if message.role is ModelRole.TOOL:
                raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            messages.append(
                {
                    'role': message.role.value,
                    'content': [{'text': message.content}],
                }
            )
        if not messages:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return '\n\n'.join(system_parts), messages

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ModelGatewayError(ModelGatewayErrorCode.AUTHENTICATION)
        if status_code == 429:
            raise ModelGatewayError(ModelGatewayErrorCode.RATE_LIMIT, retryable=True)
        raise ModelGatewayError(
            ModelGatewayErrorCode.PROVIDER,
            retryable=status_code >= 500,
        )

    def _normalise_response(
        self,
        payload: object,
        request: ModelRequest,
        headers: httpx.Headers,
    ) -> ModelResponse:
        if not isinstance(payload, dict):
            raise TypeError
        output = payload['output']
        if not isinstance(output, dict) or not isinstance(output.get('message'), dict):
            raise TypeError
        message = output['message']
        content = message.get('content')
        if not isinstance(content, list):
            raise TypeError
        stop_reason = payload.get('stopReason')
        if stop_reason is not None and not isinstance(stop_reason, str):
            raise TypeError
        completion_status = self._completion_status(stop_reason)
        text_parts: list[str] = []
        structured_blocks: list[dict[str, object]] = []
        for block in content:
            if not isinstance(block, dict):
                raise TypeError
            if 'text' in block:
                if not isinstance(block['text'], str):
                    raise TypeError
                text_parts.append(block['text'])
                continue
            tool_use = block.get('toolUse')
            if not isinstance(tool_use, dict):
                raise TypeError
            structured_blocks.append(tool_use)
        text = ''.join(text_parts)
        structured_output: dict[str, object] | None = None
        if (
            request.response_schema is not None
            and completion_status is ModelCompletionStatus.COMPLETE
        ):
            if len(structured_blocks) != 1:
                raise TypeError
            tool_use = structured_blocks[0]
            structured_input = tool_use.get('input')
            if (
                tool_use.get('name') != self._STRUCTURED_OUTPUT_TOOL
                or not isinstance(tool_use.get('toolUseId'), str)
                or not isinstance(structured_input, dict)
            ):
                raise TypeError
            structured_output = structured_input
        elif request.response_schema is None and structured_blocks:
            raise TypeError
        usage_value = payload.get('usage')
        usage = None
        if usage_value is not None:
            if not isinstance(usage_value, dict):
                raise TypeError
            usage = ModelUsage(
                input_tokens=usage_value.get('inputTokens'),
                output_tokens=usage_value.get('outputTokens'),
                total_tokens=usage_value.get('totalTokens'),
            )
        metadata = payload.get('$metadata')
        request_id = headers.get('x-amzn-requestid')
        if request_id is None and isinstance(metadata, dict):
            candidate = metadata.get('requestId')
            if candidate is not None and not isinstance(candidate, str):
                raise TypeError
            request_id = candidate
        return ModelResponse(
            text=text or None,
            structured_output=structured_output,
            completion_status=completion_status,
            finish_reason=stop_reason,
            usage=usage,
            provider_model=self._config.model,
            provider_request_id=request_id,
        )

    @staticmethod
    def _completion_status(stop_reason: str | None) -> ModelCompletionStatus:
        if stop_reason in {'end_turn', 'stop_sequence', 'tool_use'}:
            return ModelCompletionStatus.COMPLETE
        if stop_reason in {'max_tokens', 'model_context_window_exceeded'}:
            return ModelCompletionStatus.INCOMPLETE
        if stop_reason in {'guardrail_intervened', 'content_filtered'}:
            return ModelCompletionStatus.REFUSED
        return ModelCompletionStatus.UNKNOWN


def default_model_gateway_registry() -> ModelGatewayRegistry:
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', OpenAICompatibleModelGateway)
    registry.register('bedrock_converse', BedrockConverseModelGateway)
    return registry
