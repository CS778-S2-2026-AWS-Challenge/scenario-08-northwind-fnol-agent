import base64
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote
from uuid import uuid4

import httpx

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelContentBlock,
    ModelEvidenceContent,
    ModelEvidenceContentResolver,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelProfile,
    ModelProfileStatus,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTextContent,
    ModelToolCall,
    ModelUsage,
)

_GOOGLE_PROVIDER_SCHEMA_CONSTRAINTS = frozenset(
    {
        'additionalProperties',
        'maxItems',
        'maxLength',
        'maximum',
        'minItems',
        'minLength',
        'minimum',
        'pattern',
    }
)


def _google_provider_schema(value: object) -> object:
    if isinstance(value, list):
        return [_google_provider_schema(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _google_provider_schema(item)
            for key, item in value.items()
            if key not in _GOOGLE_PROVIDER_SCHEMA_CONSTRAINTS
        }
    return value


@dataclass(frozen=True, slots=True)
class ModelGatewayConfig:
    base_url: str
    model: str
    credential_environment_variable: str | None
    timeout_seconds: float
    capabilities: ModelCapabilities
    profile: ModelProfile
    structured_output_method: str = 'json_schema'
    reasoning_mode: str = 'provider_default'
    evidence_resolver: ModelEvidenceContentResolver | None = None

    def __post_init__(self) -> None:
        try:
            url = httpx.URL(self.base_url)
        except httpx.InvalidURL:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
        if url.scheme not in {'http', 'https'} or not url.host or url.userinfo:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if not self.model.strip() or self.timeout_seconds <= 0:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if self.reasoning_mode not in {'provider_default', 'disabled'}:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if self.structured_output_method not in {'json_schema', 'json_object'}:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if self.credential_environment_variable is not None and not re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_]*', self.credential_environment_variable
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        if (
            self.profile.model_identifier != self.model
            or self.profile.credential_reference != self.credential_environment_variable
            or self.profile.capabilities != self.capabilities
            or self.profile.structured_output_method != self.structured_output_method
            or self.profile.timeout_seconds != self.timeout_seconds
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)


@dataclass(frozen=True, slots=True)
class _GoogleToolContinuation:
    """Provider-only state retained for one turn-scoped model exchange."""

    provider_call_id: str | None
    thought_signature: str | None


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
    if required.image_input and not profile.capabilities.image_input:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    if required.document_input and not profile.capabilities.document_input:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)


def _content_blocks(message: ModelMessage) -> list[ModelContentBlock]:
    content_blocks = message.content_blocks
    if content_blocks:
        return content_blocks
    if message.content is None:
        return []
    return [ModelTextContent(text=message.content)]


def _resolve_evidence(
    block: ModelEvidenceContent,
    resolver: ModelEvidenceContentResolver | None,
) -> bytes:
    if resolver is None:
        raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
    try:
        content = resolver.resolve(block.evidence_id, block.media_type)
    except (TypeError, ValueError, KeyError):
        raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE) from None
    if content is None:
        raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
    return content


def _require_media_capability(
    block: ModelEvidenceContent,
    capabilities: ModelCapabilities,
) -> None:
    if block.media_type in {'image/jpeg', 'image/png'} and not capabilities.image_input:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    if block.media_type == 'application/pdf' and not capabilities.document_input:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    if block.media_type not in {'image/jpeg', 'image/png', 'application/pdf'}:
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
            raise ModelGatewayError(
                ModelGatewayErrorCode.TIMEOUT,
                retryable=True,
                provider_model=self._config.model,
            ) from None
        except httpx.RequestError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.PROVIDER,
                retryable=True,
                provider_model=self._config.model,
            ) from None

        self._raise_for_status(response.status_code)
        try:
            payload = response.json()
            return self._normalise_response(payload, request, response.headers)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ModelGatewayError(
                ModelGatewayErrorCode.MALFORMED_RESPONSE,
                provider_model=self._config.model,
            ) from None

    def _validate_capabilities(self, request: ModelRequest) -> None:
        _validate_request_profile(self._config, request)
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools and not self.capabilities.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        provider_tool_names = self._provider_tool_names(request)
        messages: list[dict[str, object]] = []
        flatten_tool_history = (
            self._config.structured_output_method == 'json_object'
            and not request.tools
            and any(
                message.tool_calls or message.role is ModelRole.TOOL for message in request.messages
            )
        )
        for message in request.messages:
            # Preserve the legacy OpenAI-compatible string payload unless the
            # caller explicitly supplied multimodal content blocks.
            blocks = message.content_blocks
            provider_content: str | None | list[dict[str, object]]
            if not blocks:
                provider_content = message.content
            else:
                provider_blocks: list[dict[str, object]] = []
                for block in blocks:
                    if isinstance(block, ModelTextContent):
                        provider_blocks.append({'type': 'text', 'text': block.text})
                    else:
                        _require_media_capability(block, self.capabilities)
                        encoded = base64.b64encode(
                            _resolve_evidence(block, self._config.evidence_resolver)
                        ).decode('ascii')
                        data_url = f'data:{block.media_type};base64,{encoded}'
                        if block.media_type.startswith('image/'):
                            provider_blocks.append(
                                {'type': 'image_url', 'image_url': {'url': data_url}}
                            )
                        else:
                            provider_blocks.append(
                                {
                                    'type': 'file',
                                    'file': {'file_data': data_url, 'filename': block.evidence_id},
                                }
                            )
                provider_content = provider_blocks
            role = message.role.value
            if flatten_tool_history and message.role is ModelRole.TOOL:
                role = ModelRole.USER.value
                provider_content = (
                    f'Tool result ({message.name or "tool"}): {message.content or ""}'
                )
            item: dict[str, object] = {'role': role, 'content': provider_content}
            if message.tool_calls and not flatten_tool_history:
                item['tool_calls'] = [
                    {
                        'id': tool.call_id,
                        'type': 'function',
                        'function': {
                            'name': provider_tool_names.get(
                                tool.name, self._provider_tool_name(tool.name)
                            ),
                            'arguments': json.dumps(
                                tool.arguments,
                                separators=(',', ':'),
                            ),
                        },
                    }
                    for tool in message.tool_calls
                ]
            if message.tool_call_id is not None and not flatten_tool_history:
                item['tool_call_id'] = message.tool_call_id
            if message.name is not None and not flatten_tool_history:
                item['name'] = provider_tool_names.get(
                    message.name, self._provider_tool_name(message.name)
                )
            messages.append(item)
        if (
            request.response_schema is not None
            and self._config.structured_output_method == 'json_object'
        ):
            schema_instruction = (
                'Return only one JSON object that matches this JSON Schema exactly: '
                + json.dumps(request.response_schema, separators=(',', ':'), sort_keys=True)
            )
            system_message = next(
                (
                    item
                    for item in messages
                    if item.get('role') == ModelRole.SYSTEM.value
                    and isinstance(item.get('content'), str)
                ),
                None,
            )
            if system_message is None:
                messages.insert(
                    0,
                    {'role': ModelRole.SYSTEM.value, 'content': schema_instruction},
                )
            else:
                system_message['content'] = f'{system_message["content"]}\n\n{schema_instruction}'
        payload: dict[str, object] = {
            'model': self._config.model,
            'messages': messages,
        }
        if request.max_output_tokens is not None:
            payload['max_tokens'] = request.max_output_tokens
        if self._config.reasoning_mode == 'disabled':
            payload['chat_template_kwargs'] = {'enable_thinking': False}
        if request.response_schema is not None:
            if self._config.structured_output_method == 'json_object':
                payload['response_format'] = {'type': 'json_object'}
            else:
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
                        'name': provider_tool_names[tool.name],
                        'description': tool.description,
                        'parameters': tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
        if request.required_tool_name is not None:
            if request.required_tool_name not in {tool.name for tool in request.tools}:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            payload['tool_choice'] = {
                'type': 'function',
                'function': {'name': provider_tool_names[request.required_tool_name]},
            }
            payload['parallel_tool_calls'] = False
        return payload

    @staticmethod
    def _provider_tool_name(name: str) -> str:
        return name.replace('.', '_')

    @classmethod
    def _provider_tool_names(cls, request: ModelRequest) -> dict[str, str]:
        domain_names = {tool.name for tool in request.tools} | {
            call.name for message in request.messages for call in message.tool_calls
        }
        if request.required_tool_name is not None:
            domain_names.add(request.required_tool_name)
        provider_names = {name: cls._provider_tool_name(name) for name in domain_names}
        if len(set(provider_names.values())) != len(provider_names):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return provider_names

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

    def _raise_for_status(self, status_code: int) -> None:
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ModelGatewayError(
                ModelGatewayErrorCode.AUTHENTICATION,
                provider_model=self._config.model,
            )
        if status_code == 429:
            raise ModelGatewayError(
                ModelGatewayErrorCode.RATE_LIMIT,
                retryable=True,
                provider_model=self._config.model,
            )
        raise ModelGatewayError(
            ModelGatewayErrorCode.PROVIDER,
            retryable=status_code >= 500,
            provider_model=self._config.model,
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

        provider_to_domain = {
            OpenAICompatibleModelGateway._provider_tool_name(tool.name): tool.name
            for tool in request.tools
        }
        tool_calls = OpenAICompatibleModelGateway._normalise_tool_calls(
            message.get('tool_calls', []),
            provider_to_domain,
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
    def _normalise_tool_calls(
        value: object,
        provider_to_domain: dict[str, str] | None = None,
    ) -> list[ModelToolCall]:
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
                    name=(provider_to_domain or {}).get(function['name'], function['name']),
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
        prompt_details = value.get('prompt_tokens_details')
        if prompt_details is not None and not isinstance(prompt_details, dict):
            raise TypeError
        cache_read_input_tokens = value.get('cache_read_input_tokens')
        if cache_read_input_tokens is None and prompt_details is not None:
            cache_read_input_tokens = prompt_details.get('cached_tokens')
        cache_write_input_tokens = value.get('cache_write_input_tokens')
        if cache_write_input_tokens is None:
            cache_write_input_tokens = value.get('cache_creation_input_tokens')
        return ModelUsage(
            input_tokens=value.get('prompt_tokens'),
            output_tokens=value.get('completion_tokens'),
            total_tokens=value.get('total_tokens'),
            cache_read_input_tokens=cache_read_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
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
        if request.max_output_tokens is not None:
            payload['inferenceConfig'] = {'maxTokens': request.max_output_tokens}
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
            raise ModelGatewayError(
                ModelGatewayErrorCode.TIMEOUT,
                retryable=True,
                provider_model=self._config.model,
            ) from None
        except httpx.RequestError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.PROVIDER,
                retryable=True,
                provider_model=self._config.model,
            ) from None

        self._raise_for_status(response.status_code)
        try:
            payload = response.json()
            return self._normalise_response(payload, request, response.headers)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ModelGatewayError(
                ModelGatewayErrorCode.MALFORMED_RESPONSE,
                provider_model=self._config.model,
            ) from None

    def _validate_capabilities(self, request: ModelRequest) -> None:
        _validate_request_profile(self._config, request)
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    def _request_messages(self, request: ModelRequest) -> tuple[str, list[dict[str, object]]]:
        system_parts: list[str] = []
        messages: list[dict[str, object]] = []
        for message in request.messages:
            if message.role is ModelRole.SYSTEM:
                if message.content_blocks:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                system_parts.append(message.content or '')
                continue
            if message.role is ModelRole.TOOL:
                raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            content: list[dict[str, object]] = []
            for block in _content_blocks(message):
                if isinstance(block, ModelTextContent):
                    content.append({'text': block.text})
                    continue
                _require_media_capability(block, self.capabilities)
                encoded = base64.b64encode(
                    _resolve_evidence(block, self._config.evidence_resolver)
                ).decode('ascii')
                if block.media_type.startswith('image/'):
                    image_format = block.media_type.removeprefix('image/')
                    content.append(
                        {'image': {'format': image_format, 'source': {'bytes': encoded}}}
                    )
                else:
                    content.append(
                        {
                            'document': {
                                'format': 'pdf',
                                'name': block.evidence_id,
                                'source': {'bytes': encoded},
                            }
                        }
                    )
            messages.append({'role': message.role.value, 'content': content})
        if not messages:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return '\n\n'.join(system_parts), messages

    def _raise_for_status(self, status_code: int) -> None:
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ModelGatewayError(
                ModelGatewayErrorCode.AUTHENTICATION,
                provider_model=self._config.model,
            )
        if status_code == 429:
            raise ModelGatewayError(
                ModelGatewayErrorCode.RATE_LIMIT,
                retryable=True,
                provider_model=self._config.model,
            )
        raise ModelGatewayError(
            ModelGatewayErrorCode.PROVIDER,
            retryable=status_code >= 500,
            provider_model=self._config.model,
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
                cache_read_input_tokens=usage_value.get('cacheReadInputTokens'),
                cache_write_input_tokens=usage_value.get('cacheWriteInputTokens'),
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


class GoogleGenerateContentModelGateway:
    """HTTP adapter for the native Google Gemini GenerateContent API."""

    def __init__(
        self,
        config: ModelGatewayConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._tool_continuations: dict[str, _GoogleToolContinuation] = {}

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

        consumed_call_ids = self._continuation_call_ids(request)
        try:
            with httpx.Client(
                base_url=f'{self._config.base_url.rstrip("/")}/',
                timeout=self._config.timeout_seconds,
                transport=self._transport,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'x-goog-api-key': credential,
                },
            ) as client:
                response = client.post(
                    f'models/{quote(self._config.model, safe="")}:generateContent',
                    json=self._request_payload(request),
                )
        except httpx.TimeoutException:
            raise ModelGatewayError(
                ModelGatewayErrorCode.TIMEOUT,
                retryable=True,
                provider_model=self._config.model,
            ) from None
        except httpx.RequestError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.PROVIDER,
                retryable=True,
                provider_model=self._config.model,
            ) from None
        finally:
            for call_id in consumed_call_ids:
                self._tool_continuations.pop(call_id, None)

        self._raise_for_status(response.status_code)
        try:
            payload = response.json()
            return self._normalise_response(payload, request, response.headers)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ModelGatewayError(
                ModelGatewayErrorCode.MALFORMED_RESPONSE,
                provider_model=self._config.model,
            ) from None

    def _validate_capabilities(self, request: ModelRequest) -> None:
        _validate_request_profile(self._config, request)
        if request.response_schema is not None and not self.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if request.tools and not self.capabilities.tools:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        provider_tool_names = self._provider_tool_names(request)
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, object]] = []
        for message in request.messages:
            if message.role is ModelRole.SYSTEM:
                if message.tool_calls or message.tool_call_id or message.name:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                for block in _content_blocks(message):
                    if not isinstance(block, ModelTextContent):
                        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                    system_parts.append({'text': block.text})
                continue
            if message.role is ModelRole.TOOL:
                contents.append(self._tool_result_content(message, provider_tool_names))
                continue

            role = 'model' if message.role is ModelRole.ASSISTANT else 'user'
            parts = self._message_parts(message)
            if message.tool_calls:
                if message.role is not ModelRole.ASSISTANT:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                parts.extend(
                    self._function_call_part(call, provider_tool_names)
                    for call in message.tool_calls
                )
            if not parts:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            contents.append({'role': role, 'parts': parts})

        if not contents:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        payload: dict[str, object] = {'contents': contents}
        if system_parts:
            payload['systemInstruction'] = {'parts': system_parts}
        generation_config: dict[str, object] = {}
        if request.max_output_tokens is not None:
            generation_config['maxOutputTokens'] = request.max_output_tokens
        if request.response_schema is not None:
            generation_config.update(
                {
                    'responseMimeType': 'application/json',
                    'responseJsonSchema': _google_provider_schema(request.response_schema),
                }
            )
        if generation_config:
            payload['generationConfig'] = generation_config
        if request.tools:
            payload['tools'] = [
                {
                    'functionDeclarations': [
                        {
                            'name': provider_tool_names[tool.name],
                            'description': tool.description,
                            'parametersJsonSchema': tool.input_schema,
                        }
                        for tool in request.tools
                    ]
                }
            ]
            function_calling_config: dict[str, object] = {'mode': 'AUTO'}
            if request.required_tool_name is not None:
                if request.required_tool_name not in provider_tool_names:
                    raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
                function_calling_config = {
                    'mode': 'ANY',
                    'allowedFunctionNames': [provider_tool_names[request.required_tool_name]],
                }
            payload['toolConfig'] = {'functionCallingConfig': function_calling_config}
        elif request.required_tool_name is not None:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return payload

    def _message_parts(self, message: ModelMessage) -> list[dict[str, object]]:
        if message.tool_call_id is not None or message.name is not None:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        parts: list[dict[str, object]] = []
        for block in _content_blocks(message):
            if isinstance(block, ModelTextContent):
                parts.append({'text': block.text})
                continue
            _require_media_capability(block, self.capabilities)
            encoded = base64.b64encode(
                _resolve_evidence(block, self._config.evidence_resolver)
            ).decode('ascii')
            parts.append(
                {
                    'inlineData': {
                        'mimeType': block.media_type,
                        'data': encoded,
                    }
                }
            )
        return parts

    def _tool_result_content(
        self,
        message: ModelMessage,
        provider_tool_names: dict[str, str],
    ) -> dict[str, object]:
        if (
            message.name is None
            or message.tool_call_id is None
            or message.content is None
            or message.content_blocks
            or message.tool_calls
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        try:
            result = json.loads(message.content)
        except json.JSONDecodeError:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
        if not isinstance(result, dict):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        continuation = self._continuation(message.tool_call_id)
        function_response: dict[str, object] = {
            'name': provider_tool_names.get(message.name, self._provider_tool_name(message.name)),
            'response': result,
        }
        if continuation.provider_call_id is not None:
            function_response['id'] = continuation.provider_call_id
        return {
            'role': 'user',
            'parts': [
                {
                    'functionResponse': function_response,
                }
            ],
        }

    def _continuation_call_ids(self, request: ModelRequest) -> set[str]:
        call_ids: set[str] = set()
        for message in request.messages:
            tool_call_id = message.tool_call_id
            if tool_call_id is not None and tool_call_id in self._tool_continuations:
                call_ids.add(tool_call_id)
            call_ids.update(
                call.call_id
                for call in message.tool_calls
                if call.call_id in self._tool_continuations
            )
        return call_ids

    def _continuation(self, call_id: str) -> _GoogleToolContinuation:
        continuation = self._tool_continuations.get(call_id)
        if continuation is None:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return continuation

    def _function_call_part(
        self,
        call: ModelToolCall,
        provider_tool_names: dict[str, str],
    ) -> dict[str, object]:
        continuation = self._continuation(call.call_id)
        function_call: dict[str, object] = {
            'name': provider_tool_names.get(call.name, self._provider_tool_name(call.name)),
            'args': call.arguments,
        }
        if continuation.provider_call_id is not None:
            function_call['id'] = continuation.provider_call_id
        part: dict[str, object] = {'functionCall': function_call}
        if continuation.thought_signature is not None:
            part['thoughtSignature'] = continuation.thought_signature
        return part

    def _register_tool_continuation(
        self,
        provider_call_id: str | None,
        thought_signature: str | None,
    ) -> str:
        call_id = f'model-call-{uuid4().hex}'
        self._tool_continuations[call_id] = _GoogleToolContinuation(
            provider_call_id=provider_call_id,
            thought_signature=thought_signature,
        )
        return call_id

    @staticmethod
    def _provider_tool_name(name: str) -> str:
        return name.replace('.', '_')

    @classmethod
    def _provider_tool_names(cls, request: ModelRequest) -> dict[str, str]:
        domain_names = (
            {tool.name for tool in request.tools}
            | {call.name for message in request.messages for call in message.tool_calls}
            | {message.name for message in request.messages if message.name is not None}
        )
        if request.required_tool_name is not None:
            domain_names.add(request.required_tool_name)
        provider_names = {name: cls._provider_tool_name(name) for name in domain_names}
        if len(set(provider_names.values())) != len(provider_names):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return provider_names

    def _raise_for_status(self, status_code: int) -> None:
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise ModelGatewayError(
                ModelGatewayErrorCode.AUTHENTICATION,
                provider_model=self._config.model,
            )
        if status_code == 408:
            raise ModelGatewayError(
                ModelGatewayErrorCode.TIMEOUT,
                retryable=True,
                provider_model=self._config.model,
            )
        if status_code == 429:
            raise ModelGatewayError(
                ModelGatewayErrorCode.RATE_LIMIT,
                retryable=True,
                provider_model=self._config.model,
            )
        raise ModelGatewayError(
            ModelGatewayErrorCode.PROVIDER,
            retryable=status_code >= 500,
            provider_model=self._config.model,
        )

    def _normalise_response(
        self,
        payload: object,
        request: ModelRequest,
        headers: httpx.Headers,
    ) -> ModelResponse:
        if not isinstance(payload, dict):
            raise TypeError
        candidates = payload.get('candidates')
        if not isinstance(candidates, list):
            raise TypeError
        if not candidates:
            return self._normalise_blocked_response(payload, headers)
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise TypeError
        finish_reason = candidate.get('finishReason')
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise TypeError
        completion_status = self._completion_status(finish_reason)
        content = candidate.get('content')
        if not isinstance(content, dict) or not isinstance(content.get('parts'), list):
            raise TypeError

        provider_to_domain = {
            self._provider_tool_name(tool.name): tool.name for tool in request.tools
        }
        text_parts: list[str] = []
        tool_calls: list[ModelToolCall] = []
        for part in content['parts']:
            if not isinstance(part, dict):
                raise TypeError
            if 'text' in part:
                if not isinstance(part['text'], str):
                    raise TypeError
                text_parts.append(part['text'])
                continue
            function_call = part.get('functionCall')
            if not isinstance(function_call, dict):
                raise TypeError
            provider_name = function_call.get('name')
            arguments = function_call.get('args')
            provider_call_id = function_call.get('id')
            thought_signature = part.get('thoughtSignature')
            if (
                not isinstance(provider_name, str)
                or provider_name not in provider_to_domain
                or not isinstance(arguments, dict)
                or (provider_call_id is not None and not isinstance(provider_call_id, str))
                or (thought_signature is not None and not isinstance(thought_signature, str))
            ):
                raise TypeError
            call_id = self._register_tool_continuation(provider_call_id, thought_signature)
            tool_calls.append(
                ModelToolCall(
                    call_id=call_id,
                    name=provider_to_domain[provider_name],
                    arguments=arguments,
                )
            )

        text = ''.join(text_parts)
        structured_output: dict[str, object] | None = None
        if (
            request.response_schema is not None
            and completion_status is ModelCompletionStatus.COMPLETE
            and not tool_calls
        ):
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise TypeError
            structured_output = parsed
        usage = self._normalise_usage(payload.get('usageMetadata'))
        model = payload.get('modelVersion', self._config.model)
        if not isinstance(model, str):
            raise TypeError
        request_id = payload.get('responseId') or headers.get('x-request-id')
        if request_id is not None and not isinstance(request_id, str):
            raise TypeError
        return ModelResponse(
            text=text or None,
            structured_output=structured_output,
            tool_calls=tool_calls,
            completion_status=completion_status,
            finish_reason=finish_reason,
            usage=usage,
            provider_model=model,
            provider_request_id=request_id,
        )

    def _normalise_blocked_response(
        self,
        payload: dict[str, object],
        headers: httpx.Headers,
    ) -> ModelResponse:
        feedback = payload.get('promptFeedback')
        if not isinstance(feedback, dict) or not isinstance(feedback.get('blockReason'), str):
            raise TypeError
        model = payload.get('modelVersion', self._config.model)
        request_id = payload.get('responseId') or headers.get('x-request-id')
        if not isinstance(model, str) or (
            request_id is not None and not isinstance(request_id, str)
        ):
            raise TypeError
        return ModelResponse(
            completion_status=ModelCompletionStatus.REFUSED,
            finish_reason=feedback['blockReason'],
            usage=self._normalise_usage(payload.get('usageMetadata')),
            provider_model=model,
            provider_request_id=request_id,
        )

    @staticmethod
    def _completion_status(finish_reason: str | None) -> ModelCompletionStatus:
        if finish_reason == 'STOP':
            return ModelCompletionStatus.COMPLETE
        if finish_reason == 'MAX_TOKENS':
            return ModelCompletionStatus.INCOMPLETE
        if finish_reason in {
            'SAFETY',
            'RECITATION',
            'BLOCKLIST',
            'PROHIBITED_CONTENT',
            'SPII',
            'IMAGE_SAFETY',
        }:
            return ModelCompletionStatus.REFUSED
        return ModelCompletionStatus.UNKNOWN

    @staticmethod
    def _normalise_usage(value: object) -> ModelUsage | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError
        candidate_tokens = value.get('candidatesTokenCount')
        thought_tokens = value.get('thoughtsTokenCount')
        if candidate_tokens is not None and not isinstance(candidate_tokens, int):
            raise TypeError
        if thought_tokens is not None and not isinstance(thought_tokens, int):
            raise TypeError
        output_tokens = None
        if candidate_tokens is not None or thought_tokens is not None:
            output_tokens = (candidate_tokens or 0) + (thought_tokens or 0)
        return ModelUsage(
            input_tokens=value.get('promptTokenCount'),
            output_tokens=output_tokens,
            total_tokens=value.get('totalTokenCount'),
            cache_read_input_tokens=value.get('cachedContentTokenCount'),
        )


def default_model_gateway_registry() -> ModelGatewayRegistry:
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', OpenAICompatibleModelGateway)
    registry.register('bedrock_converse', BedrockConverseModelGateway)
    registry.register('google_generate_content', GoogleGenerateContentModelGateway)
    return registry
