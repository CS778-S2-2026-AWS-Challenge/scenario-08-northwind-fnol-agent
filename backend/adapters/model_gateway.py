import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3
import httpx

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelProfile,
    ModelRequest,
    ModelResponse,
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
    protocol: str = 'openai_compatible'
    region: str | None = None
    profile: ModelProfile | None = None

    def __post_init__(self) -> None:
        if self.protocol.strip().lower() != 'bedrock_converse':
            try:
                url = httpx.URL(self.base_url)
            except httpx.InvalidURL:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
            if url.scheme not in {'http', 'https'} or not url.host or url.userinfo:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        elif not self.region or not self.region.strip():
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if not self.model.strip() or self.timeout_seconds <= 0:
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
        factory = self._factories.get(protocol.strip().lower())
        if factory is None:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return factory(config)


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
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools and not self.capabilities.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            'model': self._config.model,
            'messages': [message.model_dump(mode='json') for message in request.messages],
        }
        if request.response_schema is not None:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'northwind_agent_proposal',
                    'strict': True,
                    'schema': request.response_schema,
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

        structured_output: dict[str, object] | None = None
        if request.response_schema is not None:
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
        finish_reason = choice.get('finish_reason')
        if model is not None and not isinstance(model, str):
            raise TypeError
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise TypeError
        request_id = headers.get('x-request-id') or payload.get('id')
        if request_id is not None and not isinstance(request_id, str):
            raise TypeError
        return ModelResponse(
            text=content,
            structured_output=structured_output,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            provider_model=model,
            provider_request_id=request_id,
            capabilities=self.capabilities,
        )

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
    """AWS Bedrock Converse adapter behind the provider-neutral gateway port.

    The adapter accepts only synthetic or already-authorised model context from the
    caller. AWS credentials are resolved by boto3's normal credential chain and are
    never part of the profile or request contract.
    """

    def __init__(self, config: ModelGatewayConfig, *, client: Any | None = None) -> None:
        self._config = config
        self._client = client or boto3.client('bedrock-runtime', region_name=config.region)

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._config.capabilities

    def complete(self, request: ModelRequest) -> ModelResponse:
        self._validate_capabilities(request)
        system, messages = self._messages(request)
        payload: dict[str, object] = {
            'modelId': self._config.model,
            'messages': messages,
        }
        if system:
            payload['system'] = system
        if request.token_budget is not None:
            payload['inferenceConfig'] = {'maxTokens': request.token_budget}
        if request.tools:
            payload['toolConfig'] = {
                'tools': [
                    {
                        'toolSpec': {
                            'name': tool.name,
                            'description': tool.description,
                            'inputSchema': {'json': tool.input_schema},
                        }
                    }
                    for tool in request.tools
                ]
            }
        try:
            response = self._client.converse(**payload)
        except Exception as error:  # boto3 providers expose several exception classes
            self._raise_provider_error(error)
            raise AssertionError('provider error mapping must raise') from error
        return self._normalise_response(response)

    def _validate_capabilities(self, request: ModelRequest) -> None:
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools and not self.capabilities.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    @staticmethod
    def _messages(request: ModelRequest) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
        system: list[dict[str, str]] = []
        messages: list[dict[str, object]] = []
        schema_instruction = ''
        if request.response_schema is not None:
            schema_instruction = '\nReturn only a JSON object matching this schema:\n' + json.dumps(
                request.response_schema, separators=(',', ':')
            )
        for message in request.messages:
            if message.role.value == 'system':
                system.append({'text': message.content + schema_instruction})
            else:
                messages.append(
                    {
                        'role': 'user' if message.role.value == 'user' else 'assistant',
                        'content': [{'text': message.content}],
                    }
                )
        if schema_instruction and not system:
            system.append({'text': schema_instruction.lstrip()})
        return system, messages

    def _normalise_response(self, payload: object) -> ModelResponse:
        if not isinstance(payload, dict):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        output = payload.get('output')
        if not isinstance(output, dict) or not isinstance(output.get('message'), dict):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        content = output['message'].get('content')
        if not isinstance(content, list):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        text_parts: list[str] = []
        tool_calls: list[ModelToolCall] = []
        for item in content:
            if not isinstance(item, dict):
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            if isinstance(item.get('text'), str):
                text_parts.append(item['text'])
            tool_use = item.get('toolUse')
            if tool_use is not None:
                if not isinstance(tool_use, dict) or not isinstance(tool_use.get('input'), dict):
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
                tool_calls.append(
                    ModelToolCall(
                        call_id=str(tool_use.get('toolUseId', '')),
                        name=str(tool_use.get('name', '')),
                        arguments=tool_use['input'],
                    )
                )
        text = ''.join(text_parts) or None
        structured_output: dict[str, object] | None = None
        if text is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                structured_output = parsed
        usage_value = payload.get('usage')
        usage = None
        if isinstance(usage_value, dict):
            usage = ModelUsage(
                input_tokens=usage_value.get('inputTokens'),
                output_tokens=usage_value.get('outputTokens'),
                total_tokens=usage_value.get('totalTokens'),
            )
        metadata = payload.get('ResponseMetadata')
        request_id = metadata.get('RequestId') if isinstance(metadata, dict) else None
        if request_id is not None and not isinstance(request_id, str):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        stop_reason = payload.get('stopReason')
        if stop_reason is not None and not isinstance(stop_reason, str):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        return ModelResponse(
            text=text,
            structured_output=structured_output,
            tool_calls=tool_calls,
            finish_reason=stop_reason,
            usage=usage,
            provider_model=self._config.model,
            provider_request_id=request_id,
            capabilities=self.capabilities,
        )

    @staticmethod
    def _raise_provider_error(error: Exception) -> None:
        response = getattr(error, 'response', None)
        metadata = response.get('ResponseMetadata', {}) if isinstance(response, dict) else {}
        status = metadata.get('HTTPStatusCode') if isinstance(metadata, dict) else None
        if status in {401, 403}:
            raise ModelGatewayError(ModelGatewayErrorCode.AUTHENTICATION) from None
        if status == 429:
            raise ModelGatewayError(ModelGatewayErrorCode.RATE_LIMIT, retryable=True) from None
        if isinstance(status, int) and status >= 500:
            raise ModelGatewayError(ModelGatewayErrorCode.PROVIDER, retryable=True) from None
        name = error.__class__.__name__.lower()
        if 'timeout' in name:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True) from None
        if 'credential' in name or 'auth' in name:
            raise ModelGatewayError(ModelGatewayErrorCode.AUTHENTICATION) from None
        raise ModelGatewayError(ModelGatewayErrorCode.PROVIDER, retryable=True) from None


class CustomHTTPModelGateway(OpenAICompatibleModelGateway):
    """Neutral HTTP extension point for non-compatible endpoints.

    A custom endpoint may reuse the transport and normalized response contract while
    its request mapping is supplied by a subclass or registry factory.
    """


def default_model_gateway_registry() -> ModelGatewayRegistry:
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', OpenAICompatibleModelGateway)
    registry.register('custom_http', CustomHTTPModelGateway)
    registry.register('bedrock_converse', BedrockConverseModelGateway)
    return registry
