import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import (
    BedrockConverseModelGateway,
    ModelGatewayConfig,
    ModelGatewayRegistry,
    OpenAICompatibleModelGateway,
)
from backend.app import create_app
from backend.core.auth import Principal
from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.model_gateway import ConfigurationBackedModelGateway
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    now_utc,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelProfile,
    ModelProfileStatus,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTool,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentProposalSource,
    AuthorityOutcome,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    FraudSignal,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import (
    AgentTurnContext,
    InvariantGuardedAgent,
    authorised_state_changes,
    validate_proposal,
)
from backend.services.model_agent import GatewayAgent
from backend.services.workbench import get_workbench_claim_detail


def gateway_config(
    *,
    base_url: str = 'https://relay.example.test/v1',
    model: str = 'northwind-test-model',
    credential_environment_variable: str | None = None,
    structured_output: bool = True,
    tools: bool = True,
    protocol: str = 'openai_compatible',
    purpose: str = 'agent_turn',
    privacy_class: str = 'synthetic_fnol',
    prompt_version: str = 'current',
    evaluation_status: ModelProfileStatus = ModelProfileStatus.CONFIGURED,
) -> ModelGatewayConfig:
    capabilities = ModelCapabilities(structured_output=structured_output, tools=tools)
    return ModelGatewayConfig(
        base_url=base_url,
        model=model,
        credential_environment_variable=credential_environment_variable,
        timeout_seconds=5.0,
        capabilities=capabilities,
        profile=ModelProfile(
            profile_id='test-profile',
            protocol=protocol,
            provider='synthetic-provider',
            model_identifier=model,
            credential_reference=credential_environment_variable,
            purpose=purpose,
            privacy_class=privacy_class,
            capabilities=capabilities,
            timeout_seconds=5.0,
            prompt_version=prompt_version,
            evaluation_status=evaluation_status,
        ),
    )


@pytest.mark.parametrize(
    ('base_url', 'model'),
    [
        ('https://api.provider.example/v1', 'official-model'),
        ('https://relay.example/v1', 'relay-model'),
        ('http://127.0.0.1:11434/v1', 'local-model'),
    ],
    ids=['official', 'relay', 'local'],
)
def test_openai_compatible_endpoints_switch_through_configuration_only(
    base_url: str,
    model: str,
) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['url'] = str(request.url)
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={'x-request-id': 'provider-request-1'},
            json={
                'id': 'completion-1',
                'model': model,
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': '{"answer":"ok"}'},
                    }
                ],
                'usage': {
                    'prompt_tokens': 10,
                    'completion_tokens': 4,
                    'total_tokens': 14,
                },
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(base_url=base_url, model=model),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Return a test object.')],
            response_schema={
                'type': 'object',
                'properties': {'answer': {'type': 'string'}},
                'required': ['answer'],
            },
        )
    )

    assert observed['url'] == f'{base_url}/chat/completions'
    payload = cast(dict[str, object], observed['payload'])
    assert payload['model'] == model
    assert cast(dict[str, object], payload['response_format'])['type'] == 'json_schema'
    assert response.structured_output == {'answer': 'ok'}
    assert response.provider_request_id == 'provider-request-1'
    assert response.usage is not None and response.usage.total_tokens == 14


def test_openai_compatible_translates_optional_fields_to_strict_schema() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {
                            'role': 'assistant',
                            'content': '{"answer":"ok","can_resume":null,"next":{"status":"done"}}',
                        },
                    }
                ]
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(handler),
    )
    gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Return a test object.')],
            response_schema={
                'type': 'object',
                'properties': {
                    'answer': {'type': 'string'},
                    'can_resume': {
                        'anyOf': [{'type': 'boolean'}, {'type': 'null'}],
                        'default': None,
                    },
                    'next': {
                        'type': 'object',
                        'properties': {'status': {'type': 'string'}},
                    },
                    'value': {'title': 'Value'},
                    'forbidden_items': {
                        'type': 'array',
                        'items': {'type': 'object'},
                        'maxItems': 0,
                    },
                },
                'required': ['answer'],
            },
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    response_format = cast(dict[str, object], payload['response_format'])
    json_schema = cast(dict[str, object], response_format['json_schema'])
    schema = cast(dict[str, object], json_schema['schema'])
    assert schema['required'] == [
        'answer',
        'can_resume',
        'next',
        'value',
        'forbidden_items',
    ]
    assert schema['additionalProperties'] is False
    properties = cast(dict[str, dict[str, object]], schema['properties'])
    assert 'default' not in properties['can_resume']
    assert properties['next']['required'] == ['status']
    assert properties['next']['additionalProperties'] is False
    assert properties['value']['anyOf'] == [
        {'type': 'string'},
        {'type': 'number'},
        {'type': 'boolean'},
        {'type': 'null'},
    ]
    forbidden_items = cast(dict[str, object], properties['forbidden_items']['items'])
    assert forbidden_items['properties'] == {}
    assert forbidden_items['required'] == []
    assert forbidden_items['additionalProperties'] is False


def test_bedrock_converse_normalises_structured_response_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')

    def handler(request: httpx.Request) -> httpx.Response:
        observed['url'] = str(request.url)
        observed['authorization'] = request.headers['Authorization']
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={'x-amzn-requestid': 'bedrock-request-1'},
            json={
                'output': {
                    'message': {
                        'role': 'assistant',
                        'content': [
                            {
                                'toolUse': {
                                    'toolUseId': 'structured-output-1',
                                    'name': 'northwind_agent_proposal',
                                    'input': {'answer': 'ok'},
                                }
                            }
                        ],
                    }
                },
                'stopReason': 'tool_use',
                'usage': {'inputTokens': 15, 'outputTokens': 5, 'totalTokens': 20},
            },
        )

    gateway = BedrockConverseModelGateway(
        gateway_config(
            base_url='https://bedrock-runtime.us-east-1.amazonaws.com',
            model='amazon.nova-2-lite-v1:0',
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content='System instruction.'),
                ModelMessage(role=ModelRole.USER, content='Return a test object.'),
            ],
            response_schema={
                'type': 'object',
                'properties': {'answer': {'type': 'string'}},
                'required': ['answer'],
            },
        )
    )

    assert observed['url'] == (
        'https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.nova-2-lite-v1%3A0/converse'
    )
    assert observed['authorization'] == 'Bearer synthetic-bedrock-token'
    payload = cast(dict[str, object], observed['payload'])
    assert payload['messages'] == [{'role': 'user', 'content': [{'text': 'Return a test object.'}]}]
    system = cast(list[dict[str, str]], payload['system'])[0]['text']
    assert system == 'System instruction.'
    tool_config = cast(dict[str, object], payload['toolConfig'])
    assert tool_config['toolChoice'] == {'tool': {'name': 'northwind_agent_proposal'}}
    tool_spec = cast(
        dict[str, object],
        cast(list[dict[str, object]], tool_config['tools'])[0]['toolSpec'],
    )
    assert tool_spec['inputSchema'] == {
        'json': {
            'type': 'object',
            'properties': {'answer': {'type': 'string'}},
            'required': ['answer'],
        }
    }
    assert response.structured_output == {'answer': 'ok'}
    assert response.completion_status is ModelCompletionStatus.COMPLETE
    assert response.provider_model == 'amazon.nova-2-lite-v1:0'
    assert response.provider_request_id == 'bedrock-request-1'
    assert response.finish_reason == 'tool_use'
    assert response.usage is not None and response.usage.total_tokens == 20


@pytest.mark.parametrize(
    ('status_code', 'code', 'retryable'),
    [
        (401, ModelGatewayErrorCode.AUTHENTICATION, False),
        (403, ModelGatewayErrorCode.AUTHENTICATION, False),
        (429, ModelGatewayErrorCode.RATE_LIMIT, True),
        (500, ModelGatewayErrorCode.PROVIDER, True),
    ],
)
def test_bedrock_converse_maps_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    code: ModelGatewayErrorCode,
    retryable: bool,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')
    gateway = BedrockConverseModelGateway(
        gateway_config(
            base_url='https://bedrock-runtime.us-east-1.amazonaws.com',
            model='amazon.nova-2-lite-v1:0',
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is code
    assert captured.value.retryable is retryable


@pytest.mark.parametrize(
    ('credential_name', 'environment_value'),
    [
        (None, None),
        ('MISSING_BEDROCK_TOKEN', None),
    ],
    ids=['missing-reference', 'missing-environment-value'],
)
def test_bedrock_converse_requires_configured_credentials(
    monkeypatch: pytest.MonkeyPatch,
    credential_name: str | None,
    environment_value: str | None,
) -> None:
    if credential_name and environment_value is None:
        monkeypatch.delenv(credential_name, raising=False)
    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable=credential_name,
            tools=False,
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    if credential_name:
        assert credential_name not in str(captured.value)


@pytest.mark.parametrize(
    ('structured_output', 'tools', 'model_request'),
    [
        (
            False,
            False,
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Return JSON.')],
                response_schema={'type': 'object'},
            ),
        ),
        (
            True,
            False,
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Use a tool.')],
                tools=[
                    ModelTool(
                        name='synthetic_tool',
                        description='A synthetic tool.',
                        input_schema={'type': 'object'},
                    )
                ],
            ),
        ),
    ],
    ids=['structured-output', 'tools'],
)
def test_bedrock_converse_rejects_unsupported_declared_capabilities(
    structured_output: bool,
    tools: bool,
    model_request: ModelRequest,
) -> None:
    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable='UNUSED_BEDROCK_TOKEN',
            structured_output=structured_output,
            tools=tools,
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(model_request)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize(
    'model_request',
    [
        ModelRequest(messages=[]),
        ModelRequest(messages=[ModelMessage(role=ModelRole.TOOL, content='Synthetic result.')]),
    ],
    ids=['empty-messages', 'tool-role'],
)
def test_bedrock_converse_rejects_unrepresentable_messages(
    monkeypatch: pytest.MonkeyPatch,
    model_request: ModelRequest,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')
    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(model_request)

    expected = (
        ModelGatewayErrorCode.CONFIGURATION
        if not model_request.messages
        else ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    )
    assert captured.value.code is expected


@pytest.mark.parametrize(
    ('transport_error', 'code'),
    [
        (httpx.ReadTimeout('Synthetic timeout.'), ModelGatewayErrorCode.TIMEOUT),
        (httpx.ConnectError('Synthetic connection failure.'), ModelGatewayErrorCode.PROVIDER),
    ],
    ids=['timeout', 'request-error'],
)
def test_bedrock_converse_maps_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    transport_error: httpx.RequestError,
    code: ModelGatewayErrorCode,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')

    def handler(request: httpx.Request) -> httpx.Response:
        transport_error.request = request
        raise transport_error

    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is code
    assert captured.value.retryable is True


def test_bedrock_converse_normalises_plain_text_and_metadata_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')
    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    'output': {
                        'message': {
                            'role': 'assistant',
                            'content': [{'text': 'Synthetic '}, {'text': 'answer.'}],
                        }
                    },
                    '$metadata': {'requestId': 'bedrock-metadata-request'},
                },
            )
        ),
    )

    response = gateway.complete(
        ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
    )

    assert response.text == 'Synthetic answer.'
    assert response.structured_output is None
    assert response.usage is None
    assert response.finish_reason is None
    assert response.provider_request_id == 'bedrock-metadata-request'


@pytest.mark.parametrize(
    'payload',
    [
        [],
        {'output': []},
        {'output': {'message': {'content': {}}}},
        {'output': {'message': {'content': [{}]}}},
        {
            'output': {'message': {'content': [{'text': '[]'}]}},
            'stopReason': 'tool_use',
        },
        {'output': {'message': {'content': [{'text': '{}'}]}}, 'usage': []},
        {
            'output': {'message': {'content': [{'text': '{}'}]}},
            '$metadata': {'requestId': 123},
        },
        {'output': {'message': {'content': [{'text': '{}'}]}}, 'stopReason': 123},
    ],
    ids=[
        'non-object',
        'invalid-output',
        'invalid-content',
        'invalid-content-block',
        'non-object-structured-output',
        'invalid-usage',
        'invalid-request-id',
        'invalid-stop-reason',
    ],
)
def test_bedrock_converse_rejects_malformed_provider_payloads(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')
    gateway = BedrockConverseModelGateway(
        gateway_config(
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')],
                response_schema={'type': 'object'},
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


def test_openai_compatible_gateway_normalises_tool_calls() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'model': 'tool-model',
                'choices': [
                    {
                        'finish_reason': 'tool_calls',
                        'message': {
                            'role': 'assistant',
                            'content': None,
                            'tool_calls': [
                                {
                                    'id': 'call-1',
                                    'type': 'function',
                                    'function': {
                                        'name': 'find_policy',
                                        'arguments': '{"policy_id":"pol-1"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    gateway = OpenAICompatibleModelGateway(gateway_config(), transport=httpx.MockTransport(handler))
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Find the policy.')],
            tools=[
                ModelTool(
                    name='find_policy',
                    description='Find a policy by ID.',
                    input_schema={
                        'type': 'object',
                        'properties': {'policy_id': {'type': 'string'}},
                    },
                )
            ],
        )
    )

    assert response.tool_calls[0].name == 'find_policy'
    assert response.tool_calls[0].arguments == {'policy_id': 'pol-1'}


@pytest.mark.parametrize(
    ('model_request', 'structured_output', 'tools'),
    [
        (
            ModelRequest(messages=[], response_schema={'type': 'object'}),
            False,
            True,
        ),
        (
            ModelRequest(
                messages=[],
                tools=[ModelTool(name='test', description='Test.', input_schema={})],
            ),
            True,
            False,
        ),
    ],
    ids=['structured-output', 'tools'],
)
def test_capability_failures_are_explicit_and_happen_before_transport(
    model_request: ModelRequest,
    structured_output: bool,
    tools: bool,
) -> None:
    transport_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    gateway = OpenAICompatibleModelGateway(
        gateway_config(structured_output=structured_output, tools=tools),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(model_request)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert transport_called is False


@pytest.mark.parametrize(
    ('request_update', 'config_update'),
    [
        ({'purpose': 'evaluation'}, {}),
        ({'privacy_class': 'restricted_fnol'}, {}),
        ({'prompt_version': 'different-prompt'}, {}),
        (
            {'required_capabilities': ModelCapabilities(structured_output=True)},
            {'structured_output': False},
        ),
        (
            {'required_capabilities': ModelCapabilities(tools=True)},
            {'tools': False},
        ),
    ],
    ids=['purpose', 'privacy', 'prompt', 'explicit-structured-output', 'explicit-tools'],
)
def test_request_profile_mismatches_fail_before_transport(
    request_update: dict[str, object],
    config_update: dict[str, object],
) -> None:
    transport_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    gateway = OpenAICompatibleModelGateway(
        gateway_config(**config_update),  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )
    request = ModelRequest(messages=[]).model_copy(update=request_update)

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(request)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert transport_called is False


@pytest.mark.parametrize(
    'evaluation_status',
    [ModelProfileStatus.DEGRADED, ModelProfileStatus.UNAVAILABLE],
)
def test_non_configured_model_profiles_fail_before_transport(
    evaluation_status: ModelProfileStatus,
) -> None:
    transport_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    gateway = OpenAICompatibleModelGateway(
        gateway_config(evaluation_status=evaluation_status),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert transport_called is False


@pytest.mark.parametrize(
    ('field_name', 'field_value'),
    [
        ('model', 'different-model'),
        ('credential_environment_variable', 'DIFFERENT_CREDENTIAL'),
        ('capabilities', ModelCapabilities(structured_output=False, tools=False)),
        ('timeout_seconds', 9.0),
    ],
    ids=['model', 'credential-reference', 'capabilities', 'timeout'],
)
def test_transport_configuration_cannot_drift_from_model_profile(
    field_name: str,
    field_value: object,
) -> None:
    config = gateway_config()

    with pytest.raises(ModelGatewayError) as captured:
        if field_name == 'model':
            replace(config, model=cast(str, field_value))
        elif field_name == 'credential_environment_variable':
            replace(
                config,
                credential_environment_variable=cast(str, field_value),
            )
        elif field_name == 'capabilities':
            replace(config, capabilities=cast(ModelCapabilities, field_value))
        else:
            replace(config, timeout_seconds=cast(float, field_value))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION


def test_registry_protocol_must_match_model_profile() -> None:
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', OpenAICompatibleModelGateway)

    with pytest.raises(ModelGatewayError) as captured:
        registry.create(
            'openai_compatible',
            gateway_config(protocol='different_protocol'),
        )

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION


@pytest.mark.parametrize(
    ('status_code', 'expected_code', 'retryable'),
    [
        (401, ModelGatewayErrorCode.AUTHENTICATION, False),
        (403, ModelGatewayErrorCode.AUTHENTICATION, False),
        (429, ModelGatewayErrorCode.RATE_LIMIT, True),
        (500, ModelGatewayErrorCode.PROVIDER, True),
    ],
)
def test_provider_http_failures_are_normalised_without_response_details(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_code: ModelGatewayErrorCode,
    retryable: bool,
) -> None:
    secret = 'secret-model-key-value'
    monkeypatch.setenv('TEST_MODEL_API_KEY', secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers['Authorization'] == f'Bearer {secret}'
        return httpx.Response(status_code, text=f'provider body includes {secret}')

    gateway = OpenAICompatibleModelGateway(
        gateway_config(credential_environment_variable='TEST_MODEL_API_KEY'),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert secret not in str(captured.value)


def test_timeout_and_malformed_responses_are_normalised() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout('provider-specific timeout detail', request=request)

    timeout_gateway = OpenAICompatibleModelGateway(
        gateway_config(), transport=httpx.MockTransport(timeout_handler)
    )
    with pytest.raises(ModelGatewayError) as timeout_error:
        timeout_gateway.complete(ModelRequest(messages=[]))
    assert timeout_error.value.code is ModelGatewayErrorCode.TIMEOUT
    assert timeout_error.value.retryable is True

    malformed_gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={'choices': []})),
    )
    with pytest.raises(ModelGatewayError) as malformed_error:
        malformed_gateway.complete(ModelRequest(messages=[]))
    assert malformed_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE

    oversized_provenance_gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'model': 'm' * 301,
                    'choices': [
                        {
                            'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': 'ok'},
                        }
                    ],
                },
            )
        ),
    )
    with pytest.raises(ModelGatewayError) as oversized_provenance_error:
        oversized_provenance_gateway.complete(ModelRequest(messages=[]))
    assert oversized_provenance_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


class StaticGateway:
    def __init__(self, response: ModelResponse) -> None:
        self.response = (
            response.model_copy(update={'completion_status': ModelCompletionStatus.COMPLETE})
            if response.completion_status is ModelCompletionStatus.UNKNOWN
            and response.structured_output is not None
            else response
        )
        self.last_request: ModelRequest | None = None
        self.call_count = 0

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        self.last_request = request
        return self.response


class FailingGateway:
    def __init__(self, code: ModelGatewayErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        self.call_count = 0

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, _request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        raise ModelGatewayError(self.code, retryable=self.retryable)


def model_gateway_settings(protocol: str) -> Settings:
    return Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter=protocol,
        model_base_url='https://model.example.test/v1',
        model_identifier='northwind-test-model',
    )


def submit_model_message(
    gateway: ModelGateway,
    *,
    protocol: str,
    message_text: str = 'A synthetic rear-end incident.',
) -> tuple[httpx.Response, FixtureRepository, WorkingClaim, str, str]:
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    with TestClient(
        create_app(
            model_gateway_settings(protocol),
            repository=repository,
            model_gateway_registry=registry,
        ),
        raise_server_exceptions=False,
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': f'{protocol}-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']
        before_claim = repository.get_claim(claim_id, 'cus_demo')
        assert before_claim is not None
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': f'{protocol}-message',
                'If-Match': '1',
            },
            json={
                'client_message_id': f'{protocol}-client-message',
                'content': {'type': 'text', 'text': message_text},
                'evidence_refs': [],
            },
        )
    return response, repository, before_claim, claim_id, session_id


def assert_model_message_failure_is_atomic(
    repository: FixtureRepository,
    before_claim: WorkingClaim,
    claim_id: str,
    session_id: str,
    protocol: str,
) -> None:
    assert repository.get_claim(claim_id, 'cus_demo') == before_claim
    assert repository.list_messages(claim_id, session_id, 'cus_demo') == []
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    assert repository.find_idempotency('cus_demo', route, f'{protocol}-message') is None


@pytest.mark.parametrize(
    ('adapter', 'provider_reason', 'expected_status'),
    [
        ('openai', 'length', ModelCompletionStatus.INCOMPLETE),
        ('openai', 'refusal', ModelCompletionStatus.REFUSED),
        ('bedrock', 'max_tokens', ModelCompletionStatus.INCOMPLETE),
        ('bedrock', 'guardrail_intervened', ModelCompletionStatus.REFUSED),
    ],
)
def test_non_complete_provider_results_are_bounded_and_atomic_at_message_api(
    monkeypatch: pytest.MonkeyPatch,
    adapter: str,
    provider_reason: str,
    expected_status: ModelCompletionStatus,
) -> None:
    proposal = _model_proposal_output(
        form_changes=[
            {
                'field_code': 'incident.description',
                'value': 'A provider result that must not be persisted.',
            }
        ]
    )
    observed_status: list[ModelCompletionStatus] = []

    if adapter == 'openai':
        finish_reason = 'stop' if provider_reason == 'refusal' else provider_reason
        message: dict[str, object] = {
            'role': 'assistant',
            'content': json.dumps(proposal),
        }
        if provider_reason == 'refusal':
            message['refusal'] = 'The provider refused this synthetic request.'

        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'choices': [{'finish_reason': finish_reason, 'message': message}],
                },
            )
        )
        inner_gateway: ModelGateway = OpenAICompatibleModelGateway(
            gateway_config(
                tools=False,
                prompt_version='northwind-fnol-motor-claimant-v2',
            ),
            transport=transport,
        )
    else:
        monkeypatch.setenv('TEST_BEDROCK_COMPLETION_TOKEN', 'synthetic-bedrock-token')
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'output': {
                        'message': {
                            'role': 'assistant',
                            'content': [{'text': json.dumps(proposal)[:80]}],
                        }
                    },
                    'stopReason': provider_reason,
                },
            )
        )
        inner_gateway = BedrockConverseModelGateway(
            gateway_config(
                credential_environment_variable='TEST_BEDROCK_COMPLETION_TOKEN',
                tools=False,
                prompt_version='northwind-fnol-motor-claimant-v2',
            ),
            transport=transport,
        )

    class ObservedGateway:
        @property
        def capabilities(self) -> ModelCapabilities:
            return inner_gateway.capabilities

        def complete(self, request: ModelRequest) -> ModelResponse:
            result = inner_gateway.complete(request)
            observed_status.append(result.completion_status)
            return result

    protocol = f'{adapter}_{provider_reason}'
    response, repository, before_claim, claim_id, session_id = submit_model_message(
        ObservedGateway(),
        protocol=protocol,
    )

    assert observed_status == [expected_status]
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )


def _working_claim() -> WorkingClaim:
    timestamp = datetime.now(UTC)
    return WorkingClaim(
        claim_id='clm_gateway',
        customer_id='cus_gateway',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _form_field(
    value: object,
    timestamp: datetime,
    *,
    needed_for: NeededFor = NeededFor.CURRENT_ACTION,
) -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=['msg_private_gateway'],
        status=FormStatus.CONFIRMED,
        needed_for=needed_for,
        confidence=1.0,
        updated_at=timestamp,
        updated_by=ActorReference(
            actor_type=ActorType.CLAIMANT,
            actor_id='cus_private_gateway',
        ),
    )


def _model_proposal_output(
    *,
    action: str = 'UPDATE',
    customer_reason: str = 'The claimant supplied an update.',
    customer_response: str = 'The update was recorded.',
    next_step_summary: str = 'Continue the report.',
    form_changes: list[dict[str, object]] | None = None,
    state_changes: list[dict[str, object]] | None = None,
    proposed_signals: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        'action': action,
        'reason_codes': ['MODEL_UPDATE'],
        'customer_reason': customer_reason,
        'customer_response': customer_response,
        'customer_next_step': {
            'status': 'continue',
            'summary': next_step_summary,
            'responsible_party': 'claimant',
            'required_items': [],
        },
        'form_changes': form_changes or [],
        'state_changes': state_changes or [],
        'proposed_signals': proposed_signals or [],
        'required_tools': [],
        'next_action_requirements': [],
        'handoff_priority': None,
    }


@pytest.mark.parametrize('active_action', [AgentAction.HANDOFF, AgentAction.URGENT_HANDOFF])
def test_active_handoff_cannot_be_replaced_by_model_provider(
    active_action: AgentAction,
) -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output=_model_proposal_output(
                state_changes=[{'path': 'claim_state.next_action', 'to': 'UPDATE'}]
            )
        )
    )
    claim = _working_claim().model_copy(
        update={
            'claim_state': _working_claim().claim_state.model_copy(
                update={'next_action': active_action}
            )
        }
    )

    proposal = InvariantGuardedAgent(GatewayAgent(gateway)).propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses-active-handoff',
            trigger_message_id='msg-active-handoff',
            message_text='I have one more detail to add.',
            evidence_refs=[],
        )
    )

    assert proposal.action is AgentAction.UPDATE
    assert proposal.reason_codes == ['HANDOFF_ALREADY_QUEUED']
    assert proposal.state_changes == []
    assert proposal.customer_next_step == claim.customer_next_step
    assert gateway.call_count == 0


def test_gateway_agent_uses_neutral_contract_and_keeps_authority_external() -> None:
    gateway = StaticGateway(
        ModelResponse(
            provider_model='provider-model-private',
            provider_request_id='provider-request-private',
            structured_output={
                'action': 'CREATE_CLAIM',
                'reason_codes': ['MODEL_SAYS_READY'],
                'customer_reason': 'The supplied details appear ready.',
                'customer_response': 'Your report is ready for the next controlled step.',
                'customer_next_step': {
                    'status': 'review_required',
                    'summary': 'Northwind must review claim creation.',
                    'responsible_party': 'northwind',
                    'required_items': [],
                },
                'form_changes': [
                    {
                        'field_code': 'incident.description',
                        'value': 'A proposed incident description.',
                        'needed_for': 'current_action',
                        'confidence': 0.8,
                    }
                ],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'CREATE_CLAIM'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            },
        )
    )
    agent = GatewayAgent(gateway)
    timestamp = datetime.now(UTC)
    claim = _working_claim().model_copy(
        update={
            'claim_id': 'clm_private_gateway',
            'customer_id': 'cus_private_gateway',
            'route': 'internal-model-route',
            'active_session_id': 'ses_private_gateway',
            'external_claim_fingerprint': 'private-external-fingerprint',
            'assessor_routing_fingerprint': 'private-assessor-fingerprint',
            'claim_state': _working_claim().claim_state.model_copy(
                update={'fraud_signal': FraudSignal.REVIEW_REQUIRED}
            ),
            'form': {
                'incident.description': _form_field('A synthetic rear-end incident.', timestamp),
                'incident.location': _form_field('Synthetic Road', timestamp),
                'policy.policy_number': _form_field(
                    'POLICY-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'vehicle.registration': _form_field(
                    'REG-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'authorities.police_report_reference': _form_field(
                    'POLICE-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'incident.cause': _form_field(
                    'Cause for later action', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
            },
        }
    )
    proposal = agent.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='Please create the claim.',
            evidence_refs=['evd_private_gateway'],
        )
    )

    assert gateway.last_request is not None
    assert gateway.last_request.response_schema is not None
    model_context = json.loads(gateway.last_request.messages[1].content)
    assert set(model_context) == {
        'claim',
        'message_text',
        'evidence_reference_count',
        'professional_review_required',
        'knowledge_status',
        'knowledge_citations',
        'knowledge_limitations',
    }
    assert model_context['evidence_reference_count'] == 1
    assert model_context['knowledge_status'] == 'not_requested'
    assert model_context['knowledge_citations'] == []
    assert model_context['knowledge_limitations'] == []
    assert set(model_context['claim']) == {
        'channel',
        'locale',
        'incident_type',
        'claim_state',
        'form',
        'known_field_codes',
        'evidence_summary',
        'customer_next_step',
    }
    assert 'fraud_signal' not in model_context['claim']['claim_state']
    assert set(model_context['claim']['form']) == {'incident.description'}
    assert set(model_context['claim']['known_field_codes']) == {
        'incident.description',
        'incident.location',
    }
    assert set(model_context['claim']['form']['incident.description']) == {
        'value',
        'source',
        'status',
        'needed_for',
        'confidence',
    }
    serialised_context = json.dumps(model_context)
    for private_value in (
        'clm_private_gateway',
        'cus_private_gateway',
        'ses_private_gateway',
        'msg_private_gateway',
        'evd_private_gateway',
        'private-external-fingerprint',
        'private-assessor-fingerprint',
        'internal-model-route',
        'Synthetic Road',
        'POLICY-PRIVATE',
        'REG-PRIVATE',
        'POLICE-PRIVATE',
        'Cause for later action',
    ):
        assert private_value not in serialised_context
    assert proposal.action is AgentAction.CREATE_CLAIM
    assert proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert proposal.model_provenance is not None
    assert proposal.model_provenance.provider_model == 'provider-model-private'
    assert proposal.model_provenance.provider_request_id == 'provider-request-private'
    assert proposal.model_provenance.prompt_id == 'northwind-fnol-motor-claimant-v2'
    assert proposal.form_changes[0].source is FormSource.INFERENCE
    assert proposal.form_changes[0].status is FormStatus.PROPOSED
    authority = validate_proposal(proposal)
    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(proposal, authority) == []


@pytest.mark.parametrize(
    ('action', 'state_changes', 'expected_outcome'),
    [
        ('UPDATE', [{'path': 'claim_state.next_action', 'to': 'UPDATE'}], 'authorised'),
        (
            'CREATE_CLAIM',
            [{'path': 'claim_state.next_action', 'to': 'CREATE_CLAIM'}],
            'review_required',
        ),
        ('UPDATE', [{'path': 'claim_state.coverage', 'to': 'clear'}], 'blocked'),
    ],
)
def test_model_claimant_text_is_rendered_by_deterministic_authority(
    action: str,
    state_changes: list[dict[str, object]],
    expected_outcome: str,
) -> None:
    unsafe_text = (
        'Your claim is approved and not rejected. Northwind accepts liability, you are '
        'fraudulent, and emergency services were contacted.'
    )
    protocol = f'unsafe_claimant_text_{expected_outcome}'
    gateway = StaticGateway(
        ModelResponse(
            provider_model='private-provider-model',
            provider_request_id='private-provider-request',
            structured_output=_model_proposal_output(
                action=action,
                customer_reason=unsafe_text,
                customer_response=unsafe_text,
                next_step_summary=unsafe_text,
                state_changes=state_changes,
            ),
        )
    )

    response, repository, _before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 200
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.authority.outcome.value == expected_outcome
    claimant_payload = response.text.lower()
    for unsafe_fragment in (
        'approved',
        'rejected',
        'accepts liability',
        'fraudulent',
        'emergency services were contacted',
        'private-provider-model',
        'private-provider-request',
    ):
        assert unsafe_fragment not in claimant_payload
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert unsafe_text not in str([message.content for message in messages])
    assert unsafe_text not in decision.customer_reason
    assert unsafe_text not in decision.customer_response
    assert unsafe_text not in decision.customer_next_step.summary


def test_model_signal_injection_is_rejected_before_workbench_persistence() -> None:
    protocol = 'invented_model_signal'
    gateway = StaticGateway(
        ModelResponse(
            structured_output=_model_proposal_output(
                proposed_signals=[
                    {
                        'signal_id': 'fraud_confirmed',
                        'code': 'FRAUD_CONFIRMED',
                        'status': 'confirmed',
                    }
                ]
            )
        )
    )

    response, repository, before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 502
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )
    detail = get_workbench_claim_detail(
        repository,
        Principal(subject='stf_demo', actor_type='staff'),
        claim_id,
    )
    assert detail.signals == []


def test_model_provenance_is_persisted_without_claimant_exposure() -> None:
    protocol = 'model_provenance'
    gateway = StaticGateway(
        ModelResponse(
            provider_model='provider-model-audit-only',
            provider_request_id='provider-request-audit-only',
            structured_output=_model_proposal_output(
                form_changes=[
                    {
                        'field_code': 'incident.description',
                        'value': 'A model-proposed incident description.',
                    }
                ],
                state_changes=[{'path': 'claim_state.next_action', 'to': 'UPDATE'}],
            ),
        )
    )

    response, repository, _before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 200
    assert 'provider-model-audit-only' not in response.text
    assert 'provider-request-audit-only' not in response.text
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert decision.model_provenance is not None
    assert decision.model_provenance.provider_model == 'provider-model-audit-only'
    assert decision.model_provenance.provider_request_id == 'provider-request-audit-only'
    assert decision.form_changes['incident.description'].updated_by.actor_id == 'model_gateway'


def test_gateway_agent_cannot_claim_controlled_rule_authority() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'HANDOFF',
                'reason_codes': ['HUMAN_SUPPORT_REQUESTED'],
                'customer_reason': 'Human support was requested.',
                'customer_response': 'Northwind support will review this request.',
                'customer_next_step': {
                    'status': 'review_required',
                    'summary': 'Northwind must review the proposed handoff.',
                    'responsible_party': 'northwind',
                    'required_items': [],
                },
                'form_changes': [],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'HANDOFF'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': 'standard',
                'controlled_rule_authorised': True,
            }
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='I want a person.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ('metadata_name', 'metadata_value'),
    [
        ('source', 'claimant'),
        ('source', 'staff'),
        ('source', 'policy'),
        ('status', 'confirmed'),
    ],
)
def test_gateway_agent_rejects_model_controlled_fact_metadata(
    metadata_name: str,
    metadata_value: str,
) -> None:
    form_change = {
        'field_code': 'incident.description',
        'value': 'A model-proposed description.',
        metadata_name: metadata_value,
    }
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_FACT_PROPOSAL'],
                'customer_reason': 'A fact was proposed.',
                'customer_response': 'Please review the proposed information.',
                'customer_next_step': {
                    'status': 'review_proposal',
                    'summary': 'Review the proposed information.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [form_change],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='A synthetic incident.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


def test_model_fact_metadata_rejection_is_bounded_and_atomic_at_message_api() -> None:
    protocol = 'malicious_fact_metadata'
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_FACT_PROPOSAL'],
                'customer_reason': 'A fact was proposed.',
                'customer_response': 'Please review the proposed information.',
                'customer_next_step': {
                    'status': 'review_proposal',
                    'summary': 'Review the proposed information.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [
                    {
                        'field_code': 'incident.description',
                        'value': 'A model-controlled description.',
                        'source': 'claimant',
                        'status': 'confirmed',
                    }
                ],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )

    response, repository, before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 502
    assert response.json()['error'] == {
        'code': 'DEPENDENCY_FAILED',
        'message': 'The model service could not complete the request. The claim is unchanged.',
        'request_id': response.headers['X-Request-ID'],
        'retryable': False,
    }
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )


@pytest.mark.parametrize(
    ('gateway_code', 'gateway_retryable', 'status_code', 'api_code', 'api_retryable'),
    [
        (ModelGatewayErrorCode.TIMEOUT, True, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (ModelGatewayErrorCode.RATE_LIMIT, True, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (ModelGatewayErrorCode.AUTHENTICATION, False, 502, 'DEPENDENCY_FAILED', False),
        (ModelGatewayErrorCode.CONFIGURATION, False, 502, 'DEPENDENCY_FAILED', False),
    ],
)
def test_model_gateway_failures_are_bounded_and_atomic_at_message_api(
    gateway_code: ModelGatewayErrorCode,
    gateway_retryable: bool,
    status_code: int,
    api_code: str,
    api_retryable: bool,
) -> None:
    protocol = f'failing_{gateway_code.value}'
    response, repository, before_claim, claim_id, session_id = submit_model_message(
        FailingGateway(gateway_code, retryable=gateway_retryable),
        protocol=protocol,
    )

    assert response.status_code == status_code
    error = response.json()['error']
    assert error['code'] == api_code
    assert error['retryable'] is api_retryable
    assert 'model.example.test' not in response.text
    assert gateway_code.value not in response.text
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )


@pytest.mark.parametrize('failure_kind', ['timeout', 'malformed'])
@pytest.mark.parametrize(
    ('message_text', 'expected_action', 'expected_reason', 'expected_type', 'expected_trigger'),
    [
        (
            'A passenger is injured and the road is still unsafe.',
            'URGENT_HANDOFF',
            'EXPLICIT_SAFETY_SIGNAL',
            'urgent_support',
            'urgent_safety_risk',
        ),
        (
            'I want to speak to a person.',
            'HANDOFF',
            'HUMAN_SUPPORT_REQUESTED',
            'human_support',
            'claimant_support_request',
        ),
    ],
)
def test_deterministic_interrupts_precede_model_gateway(
    failure_kind: str,
    message_text: str,
    expected_action: str,
    expected_reason: str,
    expected_type: str,
    expected_trigger: str,
) -> None:
    gateway: StaticGateway | FailingGateway
    if failure_kind == 'timeout':
        gateway = FailingGateway(ModelGatewayErrorCode.TIMEOUT, retryable=True)
    else:
        gateway = StaticGateway(ModelResponse(structured_output=None))
    protocol = f'interrupt_{failure_kind}_{expected_action.lower()}'

    response, repository, _before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol=protocol,
        message_text=message_text,
    )

    assert response.status_code == 200
    turn = response.json()
    assert turn['decision']['action'] == expected_action
    assert turn['decision']['reason_codes'] == [expected_reason]
    assert gateway.call_count == 0
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.authority.outcome is AuthorityOutcome.AUTHORISED
    assert decision.proposal_source is AgentProposalSource.CONTROLLED_AGENT
    assert decision.model_provenance is None
    handoff = repository.list_handoffs(claim_id, 'cus_demo')[0]
    assert handoff.type.value == expected_type
    assert handoff.trigger.value == expected_trigger
    assert handoff.priority.value == turn['handoff']['priority']
    assert handoff.source_message_id == turn['claimant_message']['message_id']


@pytest.mark.parametrize(
    'message_text',
    [
        'No one is injured and we are no longer in danger.',
        'A support person emailed me yesterday.',
    ],
)
def test_non_interrupt_input_delegates_to_model_gateway(message_text: str) -> None:
    gateway = StaticGateway(ModelResponse(structured_output=_model_proposal_output()))
    protocol = f'non_interrupt_{gateway.call_count}_{len(message_text)}'

    response, repository, _before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol=protocol,
        message_text=message_text,
    )

    assert response.status_code == 200
    assert response.json()['decision']['action'] == 'UPDATE'
    assert gateway.call_count == 1
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.proposal_source is AgentProposalSource.MODEL_GATEWAY


@pytest.mark.parametrize(
    ('action', 'reason_code'),
    [
        ('HANDOFF', 'MODEL_PROPOSED_HANDOFF'),
        ('URGENT_HANDOFF', 'MODEL_PROPOSED_URGENT_HANDOFF'),
    ],
)
def test_model_proposed_handoffs_remain_advisory(action: str, reason_code: str) -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output=_model_proposal_output(
                action=action,
                state_changes=[{'path': 'claim_state.next_action', 'to': action}],
            )
            | {'reason_codes': [reason_code], 'handoff_priority': 'urgent'},
        )
    )

    candidate = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='A routine synthetic update.',
            evidence_refs=[],
        )
    )
    authority = validate_proposal(candidate)

    assert candidate.controlled_rule_authorised is False
    assert candidate.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(candidate, authority) == []


def test_motor_mvp_journey_reaches_creation_pending_evidence_and_human_support() -> None:
    protocol = 'motor_mvp_journey'
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'CONFIRM',
                'reason_codes': ['MOTOR_FACTS_PROPOSED'],
                'customer_reason': 'The incident facts need claimant confirmation.',
                'customer_response': 'Please review the incident facts.',
                'customer_next_step': {
                    'status': 'confirmation_required',
                    'summary': 'Review the proposed incident facts.',
                    'responsible_party': 'claimant',
                    'required_items': ['loss.description'],
                },
                'form_changes': [
                    {'field_code': 'incident.type', 'value': 'motor'},
                    {
                        'field_code': 'incident.description',
                        'value': 'Another car hit the rear of mine on Queen Street.',
                    },
                    {'field_code': 'incident.occurred_at', 'value': 'around 10 this morning'},
                    {'field_code': 'incident.location', 'value': 'Queen Street'},
                    {'field_code': 'incident.injury_or_danger', 'value': False},
                    {
                        'field_code': 'vehicle.damage_description',
                        'value': 'The rear bumper is damaged.',
                    },
                    {'field_code': 'vehicle.drivable', 'value': True},
                ],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'CONFIRM'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    claimant = {'Authorization': 'Bearer synthetic-claimant'}
    staff = {'Authorization': 'Bearer synthetic-staff'}

    with TestClient(
        create_app(
            model_gateway_settings(protocol),
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**claimant, 'Idempotency-Key': 'motor-mvp-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': None},
        ).json()
        claim_id = created['claim']['claim_id']
        session_id = created['session']['session_id']

        intake = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **claimant,
                'Idempotency-Key': 'motor-mvp-intake',
                'If-Match': str(created['claim']['revision']),
            },
            json={
                'client_message_id': 'motor-mvp-intake-message',
                'content': {
                    'type': 'text',
                    'text': (
                        'Another car hit the rear of mine on Queen Street at around 10 this '
                        'morning. The rear bumper is damaged, nobody was injured, the scene is '
                        'safe, and the car is still drivable.'
                    ),
                },
                'evidence_refs': [],
            },
        )
        assert intake.status_code == 200, intake.text
        intake_body = intake.json()
        field_codes = {change['field_code'] for change in intake_body['form_changes']}
        assert 'vehicle.damage_description' in field_codes
        assert 'loss.description' in field_codes
        assert 'What was damaged or lost?' not in intake_body['agent_message']['content']['text']

        confirmed = client.post(
            f'/api/v1/claims/{claim_id}/form/confirmations',
            headers={
                **claimant,
                'Idempotency-Key': 'motor-mvp-confirm',
                'If-Match': str(intake_body['claim_revision']),
            },
            json={'field_codes': sorted(field_codes)},
        )
        assert confirmed.status_code == 200, confirmed.text
        confirmed_body = confirmed.json()
        assert confirmed_body['customer_next_step']['status'] == 'ready_to_create'

        pending = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **claimant,
                'Idempotency-Key': 'motor-mvp-pending',
                'If-Match': str(confirmed_body['revision']),
            },
            json={
                'client_message_id': 'motor-mvp-pending-message',
                'content': {
                    'type': 'text',
                    'text': (
                        'I reported the accident to Police, but the formal report has not been '
                        'issued yet. I can provide it later.'
                    ),
                },
                'evidence_refs': [],
            },
        )
        assert pending.status_code == 200, pending.text
        pending_body = pending.json()
        assert pending_body['decision']['customer_next_step']['status'] == 'ready_to_create'
        evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=claimant).json()[
            'items'
        ]
        assert [(item['kind'], item['status']) for item in evidence] == [
            ('police_report', 'pending_generation')
        ]

        external_claim = client.post(
            f'/api/v1/claims/{claim_id}/creation',
            headers={
                **claimant,
                'Idempotency-Key': 'motor-mvp-create',
                'If-Match': str(pending_body['claim_revision']),
            },
        )
        assert external_claim.status_code == 201, external_claim.text
        external_claim_body = external_claim.json()
        assert external_claim_body['external_claim']['creation_status'] == 'created'

        handoff_turn = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **claimant,
                'Idempotency-Key': 'motor-mvp-handoff',
                'If-Match': str(external_claim_body['revision']),
            },
            json={
                'client_message_id': 'motor-mvp-handoff-message',
                'content': {
                    'type': 'text',
                    'text': (
                        "I'm not comfortable continuing on my own. Could I speak with a person?"
                    ),
                },
                'evidence_refs': [],
            },
        )
        assert handoff_turn.status_code == 200, handoff_turn.text
        handoff_body = handoff_turn.json()
        assert handoff_body['handoff']['status'] == 'queued'
        assert handoff_body['decision']['action'] == 'HANDOFF'
        assert gateway.call_count == 1

        detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff).json()
        handoff_id = detail['handoffs'][0]['handoff_id']
        accepted = client.post(
            f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
            headers={
                **staff,
                'Idempotency-Key': 'motor-mvp-accept',
                'If-Match': str(detail['revision']),
            },
            json={},
        )
        assert accepted.status_code == 200, accepted.text
        accepted_body = accepted.json()
        staff_reply = 'You can provide the Police report later. I have the incident details here.'
        reply = client.post(
            f'/api/v1/workbench/claims/{claim_id}/messages',
            headers={
                **staff,
                'Idempotency-Key': 'motor-mvp-staff-reply',
                'If-Match': str(accepted_body['revision']),
            },
            json={'content': {'type': 'text', 'text': staff_reply}},
        )
        assert reply.status_code == 200, reply.text
        history = client.get(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages', headers=claimant
        ).json()['items']
        assert any(message['content'].get('text') == staff_reply for message in history)


def test_gateway_agent_rejects_model_requested_server_tools() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_TOOL_REQUEST'],
                'customer_reason': 'A model requested a server tool.',
                'customer_response': 'No tool has run.',
                'customer_next_step': {
                    'status': 'continue',
                    'summary': 'Continue without executing an untrusted tool request.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [{'tool': 'policy_history', 'operation': 'search_policy'}],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='Look up my policy.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_custom_protocol_registration_composes_without_route_changes() -> None:
    response = ModelResponse(
        structured_output={
            'action': 'UPDATE',
            'reason_codes': ['TEST'],
            'customer_reason': 'Test.',
            'customer_response': 'Test.',
            'customer_next_step': {
                'status': 'test',
                'summary': 'Test.',
                'responsible_party': 'claimant',
                'required_items': [],
            },
            'form_changes': [],
            'state_changes': [],
            'proposed_signals': [],
            'required_tools': [],
            'next_action_requirements': [],
            'handoff_priority': None,
        }
    )
    registry = ModelGatewayRegistry()
    registry.register('custom_test', lambda _config: StaticGateway(response))
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='custom_test',
        model_base_url='https://custom.example/model',
        model_identifier='custom-model',
    )

    with TestClient(create_app(settings, model_gateway_registry=registry)) as client:
        readiness = client.get('/health/ready')
        openapi = client.get('/openapi.json').json()

    assert readiness.json()['checks']['agent'] == 'configured'
    assert all('model' not in path for path in openapi['paths'])


def test_published_model_cannot_override_deployment_endpoint_or_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_base_url='https://approved-model.example/v1',
        model_identifier='approved-model',
        model_api_key_env='NORTHWIND_MODEL_API_KEY',
    )
    repository = ConfigurationRepository()
    repository.create(
        ConfigurationRecord(
            configuration_id='cfg_malicious',
            revision=3,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            domain='model',
            values={
                'protocol': 'openai_compatible',
                'provider': 'untrusted-provider',
                'model_identifier': 'untrusted-model',
                'base_url': 'https://unapproved.example/v1',
                'credential_environment_variable': 'UNAPPROVED_PROCESS_SECRET',
                'profile_id': 'untrusted-profile',
                'purpose': 'agent_turn',
                'privacy_class': 'synthetic_fnol',
                'prompt_version': 'northwind-fnol-motor-claimant-v2',
                'evaluation_status': 'configured',
                'timeout_seconds': 30,
                'structured_output': True,
                'tools': False,
            },
            secret_references={},
            author='adm_demo',
            reason='Simulate a storage-boundary bypass.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )
    registry = ModelGatewayRegistry()
    provider_constructions: list[ModelGatewayConfig] = []
    environment_reads: list[str] = []

    def record_environment_read(name: str) -> str | None:
        environment_reads.append(name)
        return 'must-not-be-read'

    def record_provider_construction(config: ModelGatewayConfig) -> ModelGateway:
        provider_constructions.append(config)
        return OpenAICompatibleModelGateway(config)

    monkeypatch.setattr(os, 'getenv', record_environment_read)
    registry.register('openai_compatible', record_provider_construction)
    gateway = ConfigurationBackedModelGateway(settings, repository, registry)

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert provider_constructions == []
    assert environment_reads == []


def test_gateway_agent_requires_structured_output_at_composition() -> None:
    registry = ModelGatewayRegistry()
    registry.register(
        'no_structured_output',
        lambda _config: OpenAICompatibleModelGateway(gateway_config(structured_output=False)),
    )
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='no_structured_output',
        model_base_url='https://custom.example/model',
        model_identifier='custom-model',
        model_supports_structured_output=False,
    )

    with pytest.raises(ModelGatewayError) as captured:
        create_app(settings, model_gateway_registry=registry)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_missing_credential_reference_fails_without_naming_or_echoing_a_secret() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(credential_environment_variable='MISSING_MODEL_SECRET')
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert 'MISSING_MODEL_SECRET' not in str(captured.value)


def test_endpoint_credentials_are_rejected_as_configuration() -> None:
    with pytest.raises(ModelGatewayError) as captured:
        gateway_config(base_url='https://embedded:secret@provider.example/v1')

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert 'embedded' not in str(captured.value)
    assert 'secret' not in str(captured.value)


@pytest.mark.parametrize('credential_name', ['MODEL-KEY', 'MODEL KEY', 'MODEL=KEY'])
def test_invalid_credential_environment_names_fail_closed(
    credential_name: str,
) -> None:
    with pytest.raises(ModelGatewayError) as captured:
        gateway_config(credential_environment_variable=credential_name)

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert credential_name not in str(captured.value)
