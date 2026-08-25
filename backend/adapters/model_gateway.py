import json
import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
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

    def __post_init__(self) -> None:
        try:
            url = httpx.URL(self.base_url)
        except httpx.InvalidURL:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
        if url.scheme not in {'http', 'https'} or not url.host or url.userinfo:
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


def default_model_gateway_registry() -> ModelGatewayRegistry:
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', OpenAICompatibleModelGateway)
    return registry
