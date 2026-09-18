import base64
import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import (
    BedrockConverseModelGateway,
    GoogleGenerateContentModelGateway,
    ModelGatewayConfig,
    ModelGatewayRegistry,
    OpenAICompatibleModelGateway,
    _optional_cache_token_count,
    default_model_gateway_registry,
)
from backend.app import create_app
from backend.core.auth import Principal
from backend.core.config import AgentRuntimeProfile, DataRuntimeProfile, IdentityMode, Settings
from backend.core.model_gateway import ConfigurationBackedModelGateway
from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeBinding,
    now_utc,
)
from backend.domain.external_service_registry import (
    ExternalLifecycleStatus,
    build_lifecycle_projection,
)
from backend.domain.external_services import (
    ASSESSOR_REQUESTED_ACTION,
    ASSESSOR_SERVICE_IDENTITY,
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeRetrievalUnavailable,
    KnowledgeSearch,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
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
    ModelTool,
    ModelToolCall,
    ModelUsage,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentProposalSource,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    AuthorityOutcome,
    Channel,
    ContentsItem,
    ContentsLossType,
    ContentsOwnership,
    CustomerNextStep,
    FieldSelectionState,
    FormSource,
    FormStatus,
    FraudSignal,
    IntegrationSource,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    SupportNeed,
    WorkingClaim,
)
from backend.domain.operations import OperationState
from backend.prompts import (
    MOTOR_CLAIMANT_PROMPT_ID,
    load_motor_claimant_prompt,
    load_staff_assistant_prompt,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository
from backend.repositories.operations import OperationRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.agent import (
    AgentEvidenceReference,
    AgentTurnContext,
    InvariantGuardedAgent,
    authorised_state_changes,
    validate_proposal,
)
from backend.services.model_agent import GatewayAgent, KnowledgeGroundedAgent
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.prompt_composer import load_response_schemas
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)
from backend.services.workbench import get_workbench_claim_detail


def gateway_config(
    *,
    base_url: str = 'https://relay.example.test/v1',
    model: str = 'northwind-test-model',
    credential_environment_variable: str | None = None,
    structured_output: bool = True,
    tools: bool = True,
    image_input: bool = False,
    document_input: bool = False,
    evidence_resolver: object | None = None,
    protocol: str = 'openai_compatible',
    purpose: str = 'agent_turn',
    privacy_class: str = 'synthetic_fnol',
    prompt_version: str = 'current',
    evaluation_status: ModelProfileStatus = ModelProfileStatus.CONFIGURED,
) -> ModelGatewayConfig:
    capabilities = ModelCapabilities(
        structured_output=structured_output,
        tools=tools,
        image_input=image_input,
        document_input=document_input,
    )
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
        evidence_resolver=evidence_resolver,  # type: ignore[arg-type]
    )


class EvidenceResolver:
    def __init__(self, content: bytes | None = b'synthetic-evidence') -> None:
        self.content = content
        self.requests: list[tuple[str, str]] = []

    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        self.requests.append((evidence_id, media_type))
        return self.content


def test_openai_compatible_maps_authorised_evidence_blocks_without_storage_metadata() -> None:
    resolver = EvidenceResolver(b'png-bytes')
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'model': 'vision-model',
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': 'ok'},
                    }
                ],
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(
            image_input=True,
            evidence_resolver=resolver,
        ),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(
                    role=ModelRole.USER,
                    content_blocks=[
                        ModelTextContent(text='Inspect this.'),
                        ModelEvidenceContent(evidence_id='evd_authorised', media_type='image/png'),
                    ],
                )
            ],
            required_capabilities=ModelCapabilities(image_input=True),
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    message = cast(list[dict[str, object]], payload['messages'])[0]
    content = cast(list[dict[str, object]], message['content'])
    assert content[0] == {'type': 'text', 'text': 'Inspect this.'}
    assert content[1]['type'] == 'image_url'
    assert 'storage_key' not in json.dumps(payload)
    assert resolver.requests == [('evd_authorised', 'image/png')]
    assert response.text == 'ok'


def test_openai_compatible_preserves_legacy_text_wire_shape() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]},
        )

    gateway = OpenAICompatibleModelGateway(gateway_config(), transport=httpx.MockTransport(handler))
    gateway.complete(
        ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Return plain text.')])
    )

    payload = cast(dict[str, object], observed['payload'])
    message = cast(list[dict[str, object]], payload['messages'])[0]
    assert message['content'] == 'Return plain text.'


def test_bedrock_converse_maps_authorised_document_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_TOKEN', 'synthetic-token')
    resolver = EvidenceResolver(b'pdf-bytes')
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'output': {
                    'message': {'content': [{'text': 'ok'}]},
                },
                'stopReason': 'end_turn',
            },
        )

    gateway = BedrockConverseModelGateway(
        gateway_config(
            protocol='bedrock_converse',
            credential_environment_variable='TEST_BEDROCK_TOKEN',
            document_input=True,
            evidence_resolver=resolver,
        ),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(
                    role=ModelRole.USER,
                    content_blocks=[
                        ModelEvidenceContent(
                            evidence_id='evd_document',
                            media_type='application/pdf',
                        )
                    ],
                )
            ],
            required_capabilities=ModelCapabilities(document_input=True),
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    message = cast(list[dict[str, object]], payload['messages'])[0]
    content = cast(list[dict[str, object]], message['content'])
    assert content[0]['document'] == {
        'format': 'pdf',
        'name': 'evd_document',
        'source': {'bytes': 'cGRmLWJ5dGVz'},
    }
    assert response.text == 'ok'
    assert resolver.requests == [('evd_document', 'application/pdf')]


def test_multimodal_gateway_fails_closed_when_evidence_is_unavailable() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(image_input=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[
                    ModelMessage(
                        role=ModelRole.USER,
                        content_blocks=[
                            ModelEvidenceContent(
                                evidence_id='evd_missing',
                                media_type='image/jpeg',
                            )
                        ],
                    )
                ],
                required_capabilities=ModelCapabilities(image_input=True),
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE


def test_multimodal_gateway_normalises_resolver_type_errors() -> None:
    class BrokenResolver:
        def resolve(self, _evidence_id: str, _media_type: str) -> bytes:
            raise TypeError('resolver contract broken')

    gateway = OpenAICompatibleModelGateway(
        gateway_config(image_input=True, evidence_resolver=BrokenResolver()),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[
                    ModelMessage(
                        role=ModelRole.USER,
                        content_blocks=[
                            ModelEvidenceContent(evidence_id='evd_broken', media_type='image/jpeg')
                        ],
                    )
                ],
                required_capabilities=ModelCapabilities(image_input=True),
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE


def test_multimodal_gateway_rejects_unsupported_media_type_before_transport() -> None:
    transport_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    gateway = OpenAICompatibleModelGateway(
        gateway_config(image_input=True),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[
                    ModelMessage(
                        role=ModelRole.USER,
                        content_blocks=[
                            ModelEvidenceContent(
                                evidence_id='evd_gif',
                                media_type='image/gif',
                            )
                        ],
                    )
                ],
                required_capabilities=ModelCapabilities(image_input=True),
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert transport_called is False


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
                    'prompt_tokens_details': {'cached_tokens': 6},
                    'cache_creation_input_tokens': 2,
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
    assert response.usage is not None
    assert response.usage.total_tokens == 14
    assert response.usage.cache_read_input_tokens == 6
    assert response.usage.cache_write_input_tokens == 2


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (None, None),
        (-1, None),
        (True, None),
        (1.5, None),
        ('4', None),
        (0, 0),
        (4, 4),
    ],
)
def test_optional_cache_token_count_accepts_only_non_negative_integers(
    value: object,
    expected: int | None,
) -> None:
    assert _optional_cache_token_count(value) == expected


def test_openai_compatible_ignores_malformed_optional_cache_telemetry() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'choices': [
                        {
                            'finish_reason': 'stop',
                            'message': {'content': '{"answer":"ok"}'},
                        }
                    ],
                    'usage': {
                        'prompt_tokens': 10,
                        'completion_tokens': 4,
                        'total_tokens': 14,
                        'prompt_tokens_details': ['not', 'an', 'object'],
                        'cache_read_input_tokens': -1,
                        'cache_creation_input_tokens': True,
                    },
                },
            )
        ),
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

    assert response.structured_output == {'answer': 'ok'}
    assert response.usage is not None
    assert response.usage.total_tokens == 14
    assert response.usage.cache_read_input_tokens is None
    assert response.usage.cache_write_input_tokens is None


def test_openai_compatible_keeps_core_usage_validation_strict() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}],
                    'usage': {'prompt_tokens': -1},
                },
            )
        ),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


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


def test_every_v7_schema_materializes_for_openai_and_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_V7_BEDROCK_TOKEN', 'synthetic-token')
    schemas = load_response_schemas()
    assert len(schemas) == 7

    for schema_id, schema in schemas.items():
        openai_payload: dict[str, object] = {}

        def openai_handler(
            request: httpx.Request,
            target: dict[str, object] = openai_payload,
        ) -> httpx.Response:
            target.update(cast(dict[str, object], json.loads(request.content)))
            return httpx.Response(
                200,
                json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]},
            )

        OpenAICompatibleModelGateway(
            gateway_config(),
            transport=httpx.MockTransport(openai_handler),
        ).complete(
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=schema_id)],
                response_schema=schema,
                max_output_tokens=287,
            )
        )
        response_format = cast(dict[str, object], openai_payload['response_format'])
        strict_wrapper = cast(dict[str, object], response_format['json_schema'])
        strict_schema = cast(dict[str, object], strict_wrapper['schema'])
        assert strict_schema['additionalProperties'] is False
        assert strict_schema['required'] == list(
            cast(dict[str, object], strict_schema['properties'])
        )
        assert openai_payload['max_tokens'] == 287

        bedrock_payload: dict[str, object] = {}

        def bedrock_handler(
            request: httpx.Request,
            target: dict[str, object] = bedrock_payload,
            current_schema_id: str = schema_id,
        ) -> httpx.Response:
            target.update(cast(dict[str, object], json.loads(request.content)))
            return httpx.Response(
                200,
                json={
                    'output': {
                        'message': {
                            'content': [
                                {
                                    'toolUse': {
                                        'toolUseId': f'out-{current_schema_id}',
                                        'name': 'northwind_agent_proposal',
                                        'input': {},
                                    }
                                }
                            ]
                        }
                    },
                    'stopReason': 'tool_use',
                },
            )

        BedrockConverseModelGateway(
            gateway_config(
                protocol='bedrock_converse',
                credential_environment_variable='TEST_V7_BEDROCK_TOKEN',
                tools=False,
            ),
            transport=httpx.MockTransport(bedrock_handler),
        ).complete(
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=schema_id)],
                response_schema=schema,
                max_output_tokens=287,
            )
        )
        tool_config = cast(dict[str, object], bedrock_payload['toolConfig'])
        tool_spec = cast(
            dict[str, object],
            cast(list[dict[str, object]], tool_config['tools'])[0]['toolSpec'],
        )
        assert tool_spec['inputSchema'] == {'json': schema}
        assert bedrock_payload['inferenceConfig'] == {'maxTokens': 287}


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
                'usage': {
                    'inputTokens': 15,
                    'outputTokens': 5,
                    'totalTokens': 20,
                    'cacheReadInputTokens': 8,
                    'cacheWriteInputTokens': 3,
                },
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
    assert response.usage is not None
    assert response.usage.total_tokens == 20
    assert response.usage.cache_read_input_tokens == 8
    assert response.usage.cache_write_input_tokens == 3


def test_bedrock_converse_ignores_malformed_optional_cache_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_BEARER_TOKEN', 'synthetic-bedrock-token')
    gateway = BedrockConverseModelGateway(
        gateway_config(
            base_url='https://bedrock-runtime.us-east-1.amazonaws.com',
            model='amazon.nova-2-lite-v1:0',
            credential_environment_variable='TEST_BEDROCK_BEARER_TOKEN',
            tools=False,
        ),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'output': {'message': {'content': [{'text': 'ok'}]}},
                    'stopReason': 'end_turn',
                    'usage': {
                        'inputTokens': 15,
                        'outputTokens': 5,
                        'totalTokens': 20,
                        'cacheReadInputTokens': 1.5,
                        'cacheWriteInputTokens': '3',
                    },
                },
            )
        ),
    )

    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Return a test response.')]
        )
    )

    assert response.text == 'ok'
    assert response.usage is not None
    assert response.usage.total_tokens == 20
    assert response.usage.cache_read_input_tokens is None
    assert response.usage.cache_write_input_tokens is None


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
    assert captured.value.provider_model == 'amazon.nova-2-lite-v1:0'


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
    assert captured.value.provider_model == 'northwind-test-model'


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


def test_google_generate_content_maps_structured_multimodal_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    resolver = EvidenceResolver(b'png-bytes')
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['url'] = str(request.url)
        observed['credential'] = request.headers.get('x-goog-api-key')
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'candidates': [
                    {
                        'finishReason': 'STOP',
                        'content': {
                            'role': 'model',
                            'parts': [{'text': '{"answer":"assessment offered"}'}],
                        },
                    }
                ],
                'usageMetadata': {
                    'promptTokenCount': 12,
                    'candidatesTokenCount': 4,
                    'thoughtsTokenCount': 2,
                    'totalTokenCount': 18,
                    'cachedContentTokenCount': 3,
                },
                'modelVersion': 'gemini-3.5-flash-lite-001',
                'responseId': 'google-response-1',
            },
        )

    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            base_url='https://generativelanguage.googleapis.com/v1beta',
            model='gemini-3.5-flash-lite',
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
            image_input=True,
            evidence_resolver=resolver,
        ),
        transport=httpx.MockTransport(handler),
    )
    schema = {
        'type': 'object',
        'properties': {'answer': {'type': 'string'}},
        'required': ['answer'],
    }
    response = gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content='Follow Northwind authority.'),
                ModelMessage(
                    role=ModelRole.USER,
                    content_blocks=[
                        ModelTextContent(text='Review this damage.'),
                        ModelEvidenceContent(
                            evidence_id='evd_google_image',
                            media_type='image/png',
                        ),
                    ],
                ),
            ],
            response_schema=schema,
            max_output_tokens=200,
            required_capabilities=ModelCapabilities(
                structured_output=True,
                image_input=True,
            ),
        )
    )

    assert observed['url'] == (
        'https://generativelanguage.googleapis.com/v1beta/'
        'models/gemini-3.5-flash-lite:generateContent'
    )
    assert observed['credential'] == 'synthetic-google-key'
    payload = cast(dict[str, object], observed['payload'])
    assert payload['systemInstruction'] == {'parts': [{'text': 'Follow Northwind authority.'}]}
    contents = cast(list[dict[str, object]], payload['contents'])
    parts = cast(list[dict[str, object]], contents[0]['parts'])
    assert parts[0] == {'text': 'Review this damage.'}
    assert parts[1] == {'inlineData': {'mimeType': 'image/png', 'data': 'cG5nLWJ5dGVz'}}
    assert payload['generationConfig'] == {
        'maxOutputTokens': 200,
        'responseMimeType': 'application/json',
        'responseJsonSchema': schema,
    }
    assert resolver.requests == [('evd_google_image', 'image/png')]
    assert response.structured_output == {'answer': 'assessment offered'}
    assert response.completion_status is ModelCompletionStatus.COMPLETE
    assert response.provider_model == 'gemini-3.5-flash-lite-001'
    assert response.provider_request_id == 'google-response-1'
    assert response.usage == ModelUsage(
        input_tokens=12,
        output_tokens=6,
        total_tokens=18,
        cache_read_input_tokens=3,
    )


def test_google_generate_content_maps_function_call_and_result_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    observed: list[dict[str, object]] = []
    thought_signature = 'provider-private-signature-' + ('x' * 500)

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(cast(dict[str, object], json.loads(request.content)))
        if len(observed) == 1:
            return httpx.Response(
                200,
                json={
                    'candidates': [
                        {
                            'finishReason': 'STOP',
                            'content': {
                                'parts': [
                                    {
                                        'functionCall': {
                                            'name': 'context_resolve',
                                            'args': {
                                                'ref': 'policy:motor',
                                                'selector': 'summary',
                                            },
                                        },
                                        'thoughtSignature': thought_signature,
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            headers={'x-request-id': 'google-header-request'},
            json={
                'candidates': [
                    {
                        'finishReason': 'STOP',
                        'content': {'parts': [{'text': '{"answer":"covered"}'}]},
                    }
                ]
            },
        )

    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(handler),
    )
    tool = ModelTool(
        name='context.resolve',
        description='Resolve one bounded context reference.',
        input_schema={'type': 'object'},
    )
    first = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Check my policy.')],
            tools=[tool],
            required_tool_name='context.resolve',
        )
    )

    assert len(first.tool_calls) == 1
    assert first.tool_calls[0].call_id.startswith('model-call-')
    assert len(first.tool_calls[0].call_id) <= 120
    assert thought_signature not in first.tool_calls[0].call_id
    encoded_signature = base64.urlsafe_b64encode(thought_signature.encode()).decode().rstrip('=')
    assert encoded_signature not in first.tool_calls[0].call_id
    assert first.tool_calls[0].name == 'context.resolve'
    assert first.tool_calls[0].arguments == {
        'ref': 'policy:motor',
        'selector': 'summary',
    }
    assert observed[0]['toolConfig'] == {
        'functionCallingConfig': {
            'mode': 'ANY',
            'allowedFunctionNames': ['context_resolve'],
        }
    }
    schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}}
    continuation_request = ModelRequest(
        messages=[
            ModelMessage(role=ModelRole.USER, content='Check my policy.'),
            ModelMessage(role=ModelRole.ASSISTANT, tool_calls=first.tool_calls),
            ModelMessage(
                role=ModelRole.TOOL,
                name='context.resolve',
                tool_call_id=first.tool_calls[0].call_id,
                content='{"result":"covered"}',
            ),
        ],
        response_schema=schema,
    )
    continuation = gateway.complete(continuation_request)

    continuation_contents = cast(list[dict[str, object]], observed[1]['contents'])
    assert continuation_contents[1]['parts'] == [
        {
            'functionCall': {
                'name': 'context_resolve',
                'args': {'ref': 'policy:motor', 'selector': 'summary'},
            },
            'thoughtSignature': thought_signature,
        }
    ]
    assert continuation_contents[2]['parts'] == [
        {
            'functionResponse': {
                'name': 'context_resolve',
                'response': {'result': 'covered'},
            }
        }
    ]
    assert continuation.structured_output == {'answer': 'covered'}
    assert continuation.provider_request_id == 'google-header-request'

    with pytest.raises(ModelGatewayError) as stale:
        gateway.complete(continuation_request)
    assert stale.value.code is ModelGatewayErrorCode.CONFIGURATION

    another_exchange = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ModelGatewayError) as missing:
        another_exchange.complete(continuation_request)
    assert missing.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert len(observed) == 2


def test_google_exchange_keeps_long_continuation_state_out_of_runtime_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    # Keep the formal v7 manifest while isolating this persistence regression from token budgets.
    monkeypatch.setattr(
        'backend.services.initial_runtime_release.load_fragment_contents',
        lambda manifest: {
            item.fragment_id: f'Follow {item.fragment_id}.' for item in manifest.fragments
        },
    )
    thought_signature = 'provider-private-signature-' + ('x' * 500)
    provider_call_id = 'provider-private-call-' + ('y' * 300)
    observed: list[dict[str, object]] = []
    exchanges: list[GoogleGenerateContentModelGateway] = []

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            return [value, *strings(decoded)]
        if isinstance(value, list):
            return [item for child in value for item in strings(child)]
        if isinstance(value, dict):
            return [item for child in value.values() for item in strings(child)]
        return []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = cast(dict[str, object], json.loads(request.content))
        observed.append(payload)
        if len(observed) == 1:
            references = [
                value
                for value in strings(payload)
                if value.startswith('ctxref:') and value.endswith(':claim-history.customer')
            ]
            assert len(references) == 1, [value for value in strings(payload) if 'ctxref:' in value]
            return httpx.Response(
                200,
                json={
                    'candidates': [
                        {
                            'finishReason': 'STOP',
                            'content': {
                                'parts': [
                                    {
                                        'functionCall': {
                                            'id': provider_call_id,
                                            'name': 'context_resolve',
                                            'args': {
                                                'ref': references[0],
                                                'selector': 'relevant_claims',
                                                'max_tokens': 80,
                                            },
                                        },
                                        'thoughtSignature': thought_signature,
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'candidates': [
                    {
                        'finishReason': 'STOP',
                        'content': {
                            'parts': [
                                {
                                    'text': json.dumps(
                                        {
                                            'reply': 'No prior claims are available.',
                                            'next_step': 'Continue the current report.',
                                            'reason_codes': ['CLAIM_HISTORY_REPORTED'],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            },
        )

    def build_exchange(config: ModelGatewayConfig) -> ModelGateway:
        exchange = GoogleGenerateContentModelGateway(
            config,
            transport=httpx.MockTransport(handler),
        )
        exchanges.append(exchange)
        return exchange

    registry = ModelGatewayRegistry()
    registry.register('google_generate_content', build_exchange)
    repository = FixtureRepository()
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    bindings = tuple(
        ModelRuntimeBinding(
            profile_id=profile_id,
            protocol='google_generate_content',
            provider='synthetic-google',
            model_identifier='gemini-3.5-flash-lite',
            base_url='https://generativelanguage.googleapis.com/v1beta',
            credential_environment_variable='TEST_GEMINI_API_KEY',
            purpose='agent_turn',
            privacy_class='synthetic_fnol',
            prompt_version='northwind-fnol-claimant-v7',
            structured_output=True,
            tools=True,
        )
        for profile_id in (
            'qwen-local',
            'nowcoding-gpt55',
            'google-gemini35-flash-lite',
        )
    )
    settings = replace(
        model_gateway_settings('google_generate_content'),
        model_profile_id='google-gemini35-flash-lite',
        model_supports_tools=True,
        model_runtime_bindings=bindings,
    )

    with TestClient(
        create_app(
            settings,
            repository=repository,
            model_gateway_registry=registry,
        ),
        raise_server_exceptions=False,
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'google-exchange-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']
        claim = repository.get_claim(claim_id, 'cus_demo')
        assert claim is not None
        exchanges.clear()

        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': 'google-exchange-message',
                'If-Match': str(claim.revision),
            },
            json={
                'client_message_id': 'google-exchange-client-message',
                'content': {
                    'type': 'text',
                    'text': 'Previous claims? Motor.',
                },
                'evidence_refs': [],
            },
        )

    assert response.status_code == 200, response.text
    assert len(exchanges) == 1
    assert len(observed) == 2
    continuation_payload = json.dumps(observed[1], sort_keys=True)
    assert thought_signature in continuation_payload
    assert provider_call_id in continuation_payload
    trigger_message_id = response.json()['claimant_message']['message_id']
    trace = repository.find_runtime_trace_for_trigger(claim_id, trigger_message_id, 'cus_demo')
    runtime_turn = repository.get_runtime_turn_for_trigger(
        claim_id,
        trigger_message_id,
        'cus_demo',
    )
    assert trace is not None
    assert runtime_turn is not None
    assert len(runtime_turn.tool_results) == 1
    tool_result = runtime_turn.tool_results[0]
    assert trace.tool_call_id == tool_result.tool_call_id
    assert trace.tool_call_id is not None
    assert trace.tool_call_id.startswith('model-call-')
    assert len(trace.tool_call_id) <= 120
    persisted = json.dumps(
        {
            'trace': trace.model_dump(mode='json'),
            'runtime_turn': runtime_turn.model_dump(mode='json'),
        },
        sort_keys=True,
    )
    assert thought_signature not in persisted
    assert provider_call_id not in persisted
    assert 'gemini-continuation.' not in persisted
    encoded_signature = base64.urlsafe_b64encode(thought_signature.encode()).decode().rstrip('=')
    assert encoded_signature not in persisted


@pytest.mark.parametrize(
    ('status_code', 'code', 'retryable'),
    [
        (401, ModelGatewayErrorCode.AUTHENTICATION, False),
        (408, ModelGatewayErrorCode.TIMEOUT, True),
        (429, ModelGatewayErrorCode.RATE_LIMIT, True),
        (500, ModelGatewayErrorCode.PROVIDER, True),
        (400, ModelGatewayErrorCode.PROVIDER, False),
    ],
)
def test_google_generate_content_maps_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    code: ModelGatewayErrorCode,
    retryable: bool,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is code
    assert captured.value.retryable is retryable
    assert captured.value.provider_model == 'northwind-test-model'


def test_google_generate_content_normalises_a_blocked_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    'candidates': [],
                    'promptFeedback': {'blockReason': 'SAFETY'},
                    'modelVersion': 'gemini-3.5-flash-lite',
                    'responseId': 'blocked-response',
                },
            )
        ),
    )

    response = gateway.complete(
        ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
    )

    assert response.completion_status is ModelCompletionStatus.REFUSED
    assert response.finish_reason == 'SAFETY'
    assert response.provider_request_id == 'blocked-response'


@pytest.mark.parametrize(
    'credential_name',
    [None, 'MISSING_GEMINI_API_KEY'],
    ids=['missing-reference', 'missing-environment-value'],
)
def test_google_generate_content_requires_an_environment_owned_credential(
    monkeypatch: pytest.MonkeyPatch,
    credential_name: str | None,
) -> None:
    monkeypatch.delenv('MISSING_GEMINI_API_KEY', raising=False)
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable=credential_name,
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert 'MISSING_GEMINI_API_KEY' not in str(captured.value)


@pytest.mark.parametrize(
    ('transport_error', 'code'),
    [
        (httpx.ReadTimeout('Synthetic timeout.'), ModelGatewayErrorCode.TIMEOUT),
        (httpx.ConnectError('Synthetic connection failure.'), ModelGatewayErrorCode.PROVIDER),
    ],
    ids=['timeout', 'request-error'],
)
def test_google_generate_content_maps_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
    transport_error: httpx.RequestError,
    code: ModelGatewayErrorCode,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')

    def handler(request: httpx.Request) -> httpx.Response:
        transport_error.request = request
        raise transport_error

    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is code
    assert captured.value.retryable is True
    assert captured.value.provider_model == 'northwind-test-model'


@pytest.mark.parametrize(
    ('model_request', 'structured_output', 'tools'),
    [
        (
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Return JSON.')],
                response_schema={'type': 'object'},
            ),
            False,
            True,
        ),
        (
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Use a tool.')],
                tools=[ModelTool(name='context.resolve', description='Resolve.', input_schema={})],
            ),
            True,
            False,
        ),
    ],
    ids=['structured-output', 'tools'],
)
def test_google_generate_content_rejects_undeclared_capabilities(
    model_request: ModelRequest,
    structured_output: bool,
    tools: bool,
) -> None:
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='UNUSED_GEMINI_API_KEY',
            structured_output=structured_output,
            tools=tools,
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(model_request)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_google_generate_content_rejects_a_malformed_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Synthetic input.')])
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE
    assert captured.value.provider_model == 'northwind-test-model'


@pytest.mark.parametrize(
    'tool_content',
    [None, 'not-json', '[]'],
    ids=['missing-content', 'invalid-json', 'non-object-json'],
)
def test_google_generate_content_rejects_an_invalid_tool_result(
    monkeypatch: pytest.MonkeyPatch,
    tool_content: str | None,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[
                    ModelMessage(
                        role=ModelRole.TOOL,
                        name='context.resolve',
                        tool_call_id='provider-call-1',
                        content=tool_content,
                    )
                ]
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION


def test_default_model_gateway_registry_constructs_google_adapter() -> None:
    gateway = default_model_gateway_registry().create(
        'google_generate_content',
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
    )

    assert isinstance(gateway, GoogleGenerateContentModelGateway)


def test_openai_compatible_gateway_normalises_tool_calls() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
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
            required_tool_name='find_policy',
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    assert payload['tool_choice'] == {
        'type': 'function',
        'function': {'name': 'find_policy'},
    }
    assert payload['parallel_tool_calls'] is False
    assert response.tool_calls[0].name == 'find_policy'
    assert response.tool_calls[0].arguments == {'policy_id': 'pol-1'}


def test_openai_compatible_rejects_required_tool_outside_request_manifest() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(
            ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content='Read the claim.')],
                tools=[ModelTool(name='claim.read', description='Read.', input_schema={})],
                required_tool_name='policy.read',
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION


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
    assert timeout_error.value.provider_model == 'northwind-test-model'

    malformed_gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={'choices': []})),
    )
    with pytest.raises(ModelGatewayError) as malformed_error:
        malformed_gateway.complete(ModelRequest(messages=[]))
    assert malformed_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE
    assert malformed_error.value.provider_model == 'northwind-test-model'

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


class SequencedGateway:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = [
            response.model_copy(update={'completion_status': ModelCompletionStatus.COMPLETE})
            for response in responses
        ]
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses[len(self.requests) - 1]


class RuntimeSequenceGateway:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class MultimodalRuntimeGateway(RuntimeSequenceGateway):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(responses)
        self.resolvers: list[object] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            tools=True,
            image_input=True,
            document_input=True,
        )

    def complete_with_evidence(
        self,
        request: ModelRequest,
        resolver: object,
    ) -> ModelResponse:
        self.resolvers.append(resolver)
        self.requests.append(request)
        return self.responses.pop(0)


class MultimodalCompatibilityGateway(MultimodalRuntimeGateway):
    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            tools=False,
            image_input=True,
            document_input=True,
        )


class StaticKnowledgeRetriever:
    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self.chunks = chunks
        self.requests: list[KnowledgeSearch] = []

    def connection_status(self) -> str:
        return 'using_fixture'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        self.requests.append(request)
        return self.chunks


def model_turn_output(
    *,
    action: str = 'UPDATE',
    required_tools: list[dict[str, object]] | None = None,
    form_changes: list[dict[str, object]] | None = None,
    required_items: list[str] | None = None,
) -> ModelResponse:
    return ModelResponse(
        structured_output={
            'action': action,
            'reason_codes': ['BOUNDED_CONTEXT_USED'],
            'customer_reason': 'The bounded context was evaluated.',
            'customer_response': 'I checked the available information safely.',
            'customer_next_step': {
                'status': 'confirmation_required' if form_changes else 'more_information_needed',
                'summary': 'Review the result or continue with the report.',
                'responsible_party': 'claimant',
                'required_items': required_items or [],
            },
            'form_changes': form_changes or [],
            'contents_item_changes': [],
            'state_changes': [{'path': 'claim_state.next_action', 'to': action}],
            'proposed_signals': [],
            'required_tools': required_tools or [],
            'next_action_requirements': required_items or [],
            'handoff_priority': None,
        }
    )


def _runtime_model_output() -> dict[str, object]:
    return {
        'action_code': 'conversation.answer',
        'runtime_action_code': 'runtime.continue',
        'reason_codes': ['CLAIM_CONTEXT_READ'],
        'customer_reason': 'The current claim context was read.',
        'customer_response': 'I have read the current claim context.',
        'customer_next_step': {
            'status': 'continue_current_report',
            'summary': 'Continue the report when ready.',
            'responsible_party': 'claimant',
            'required_items': [],
        },
        'source_refs': [],
    }


def test_gateway_agent_keeps_attached_evidence_scoped_across_the_tool_round() -> None:
    resolver = EvidenceResolver(b'claimant-image')
    gateway = MultimodalRuntimeGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='read-claim', name='claim.read', arguments={})],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                provider_model='vision-model',
                provider_request_id='vision-request',
                structured_output={
                    **_runtime_model_output(),
                    'form_changes': [
                        {
                            'field_code': 'vehicle.damage_description',
                            'value': 'Rear bumper damage is visible.',
                            'confidence': 0.84,
                            'source_evidence_id': 'evd_photo',
                        }
                    ],
                },
            ),
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-multimodal',
            trigger_message_id='msg-multimodal',
            message_text='Please review the attached photo.',
            evidence_refs=['evd_photo'],
            evidence=(
                AgentEvidenceReference(
                    evidence_id='evd_photo',
                    media_type='image/png',
                ),
            ),
            evidence_resolver=resolver,
        )
    )

    assert len(gateway.requests) == 2
    assert gateway.resolvers == [resolver, resolver]
    for request in gateway.requests:
        assert request.required_capabilities.image_input is True
        assert request.required_capabilities.document_input is False
        evidence_blocks = [
            block
            for block in request.messages[1].content_blocks
            if isinstance(block, ModelEvidenceContent)
        ]
        assert evidence_blocks == [
            ModelEvidenceContent(evidence_id='evd_photo', media_type='image/png')
        ]
    context_block = cast(ModelTextContent, gateway.requests[0].messages[1].content_blocks[0])
    model_context = json.loads(context_block.text)
    assert model_context['attached_evidence'] == [
        {'evidence_id': 'evd_photo', 'media_type': 'image/png'}
    ]
    change = proposal.form_changes[0]
    assert change.source is FormSource.IMAGE
    assert change.status is FormStatus.PROPOSED
    assert change.source_evidence_id == 'evd_photo'
    assert proposal.runtime_trace is not None
    assert [item.model_dump() for item in proposal.runtime_trace.evidence] == [
        {
            'evidence_id': 'evd_photo',
            'media_type': 'image/png',
            'outcome': 'submitted',
        }
    ]


@pytest.mark.parametrize(
    ('target_evidence_id', 'target_media_type'),
    [
        ('evd_photo', 'image/png'),
        ('evd_inventory', 'application/pdf'),
    ],
)
def test_gateway_agent_preserves_contents_attachment_provenance(
    target_evidence_id: str,
    target_media_type: str,
) -> None:
    gateway = MultimodalRuntimeGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(call_id='read-contents', name='claim.read', arguments={})
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    **_runtime_model_output(),
                    'contents_item_changes': [
                        {
                            'description': 'Laptop computer',
                            'category': 'electronics',
                            'quantity': 1,
                            'loss_type': 'damaged',
                            'ownership': 'owned',
                            'confidence': 0.88,
                            'source_evidence_id': target_evidence_id,
                        }
                    ],
                },
            ),
        ]
    )
    evidence = (
        AgentEvidenceReference(evidence_id='evd_photo', media_type='image/png'),
        AgentEvidenceReference(evidence_id='evd_inventory', media_type='application/pdf'),
    )

    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-contents-evidence',
            trigger_message_id='msg-contents-evidence',
            message_text='My laptop was damaged. Please review these attachments.',
            evidence_refs=[item.evidence_id for item in evidence],
            evidence=evidence,
            evidence_resolver=EvidenceResolver(b'contents-evidence'),
        )
    )

    assert proposal.contents_item_changes[0].source_evidence_id == target_evidence_id
    assert len(gateway.requests) == 2
    assert all(request.required_capabilities.image_input for request in gateway.requests)
    assert all(request.required_capabilities.document_input for request in gateway.requests)
    assert target_media_type in {item.media_type for item in evidence}


def test_gateway_agent_compatibility_path_preserves_contents_attachment_provenance() -> None:
    response = model_turn_output()
    gateway = MultimodalCompatibilityGateway(
        [
            response.model_copy(
                update={
                    'completion_status': ModelCompletionStatus.COMPLETE,
                    'structured_output': {
                        **cast(dict[str, object], response.structured_output),
                        'contents_item_changes': [
                            {
                                'description': 'Laptop computer',
                                'category': 'electronics',
                                'quantity': 1,
                                'loss_type': 'damaged',
                                'ownership': 'owned',
                                'source_evidence_id': 'evd_inventory',
                            }
                        ],
                    },
                }
            )
        ]
    )
    evidence = (
        AgentEvidenceReference(evidence_id='evd_photo', media_type='image/png'),
        AgentEvidenceReference(evidence_id='evd_inventory', media_type='application/pdf'),
    )

    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-contents-evidence-compatibility',
            trigger_message_id='msg-contents-evidence-compatibility',
            message_text='My laptop was damaged. Please review these attachments.',
            evidence_refs=[item.evidence_id for item in evidence],
            evidence=evidence,
            evidence_resolver=EvidenceResolver(b'contents-evidence'),
        )
    )

    assert proposal.contents_item_changes[0].source_evidence_id == 'evd_inventory'
    assert len(gateway.requests) == 1


def test_gateway_agent_rejects_unattached_contents_evidence_source() -> None:
    gateway = MultimodalRuntimeGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(call_id='read-contents', name='claim.read', arguments={})
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    **_runtime_model_output(),
                    'contents_item_changes': [
                        {
                            'description': 'Laptop computer',
                            'category': 'electronics',
                            'quantity': 1,
                            'loss_type': 'damaged',
                            'ownership': 'owned',
                            'source_evidence_id': 'evd_not_attached',
                        }
                    ],
                },
            ),
        ]
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-unattached-contents',
                trigger_message_id='msg-unattached-contents',
                message_text='Review the attached contents photo.',
                evidence_refs=['evd_photo'],
                evidence=(AgentEvidenceReference(evidence_id='evd_photo', media_type='image/png'),),
                evidence_resolver=EvidenceResolver(b'contents-evidence'),
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


def test_gateway_agent_rejects_an_unattached_model_evidence_source() -> None:
    resolver = EvidenceResolver()
    gateway = MultimodalRuntimeGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='read-claim', name='claim.read', arguments={})],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    **_runtime_model_output(),
                    'form_changes': [
                        {
                            'field_code': 'vehicle.damage_description',
                            'value': 'Unsupported damage claim.',
                            'source_evidence_id': 'evd_other_claim',
                        }
                    ],
                },
            ),
        ]
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-source-guard',
                trigger_message_id='msg-source-guard',
                message_text='Review this attachment.',
                evidence_refs=['evd_photo'],
                evidence=(
                    AgentEvidenceReference(
                        evidence_id='evd_photo',
                        media_type='image/jpeg',
                    ),
                ),
                evidence_resolver=resolver,
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


def test_gateway_agent_requires_a_turn_scoped_resolver_for_evidence() -> None:
    gateway = MultimodalRuntimeGateway([])

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-no-resolver',
                trigger_message_id='msg-no-resolver',
                message_text='Review this attachment.',
                evidence_refs=['evd_photo'],
                evidence=(
                    AgentEvidenceReference(
                        evidence_id='evd_photo',
                        media_type='image/jpeg',
                    ),
                ),
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE
    assert gateway.requests == []


def test_gateway_runtime_handoff_proposal_remains_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([100.0, 100.01, 100.01, 100.03])
    monkeypatch.setattr('backend.services.model_agent.perf_counter', lambda: next(clock))
    gateway = RuntimeSequenceGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                usage=ModelUsage(input_tokens=20, output_tokens=3, total_tokens=23),
                tool_calls=[
                    ModelToolCall(
                        call_id='handoff-read',
                        name='claim.read',
                        arguments={},
                    )
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                usage=ModelUsage(input_tokens=35, output_tokens=8, total_tokens=43),
                structured_output={
                    'action_code': 'human.create_handoff',
                    'runtime_action_code': 'runtime.pause_for_review',
                    'reason_codes': ['HUMAN_SUPPORT_REQUESTED'],
                    'customer_reason': 'The claimant asked for human support.',
                    'customer_response': 'I will connect you with a claims professional.',
                    'customer_next_step': {
                        'status': 'human_support_requested',
                        'summary': 'A claims professional will continue with you.',
                        'responsible_party': 'claims_professional',
                        'required_items': [],
                    },
                    'form_changes': [],
                    'contents_item_changes': [],
                    'source_refs': [],
                    'handoff_priority': 'standard',
                },
            ),
        ]
    )
    operations = OperationRepository()
    proposal = GatewayAgent(
        gateway,
        operations=ModelOperationsRecorder(operations),
    ).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-runtime-handoff',
            trigger_message_id='msg-runtime-handoff',
            message_text='Please connect me with a person.',
            evidence_refs=[],
        )
    )

    assert proposal.action is AgentAction.HANDOFF
    assert proposal.action_code == 'human.create_handoff'
    assert proposal.controlled_rule_authorised is False
    assert validate_proposal(proposal).outcome is AuthorityOutcome.BLOCKED
    records = operations.metrics_records()
    assert [record.state for record in records] == [
        OperationState.SUCCEEDED,
        OperationState.SUCCEEDED,
    ]
    assert [record.result['total_tokens'] for record in records if record.result is not None] == [
        23,
        43,
    ]
    assert [record.result['latency_ms'] for record in records if record.result is not None] == [
        10.0,
        20.0,
    ]
    assert proposal.runtime_trace is not None
    assert [
        invocation.latency_ms for invocation in proposal.runtime_trace.invocations
    ] == pytest.approx(
        [
            10.0,
            20.0,
        ]
    )


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
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter=protocol,
        model_base_url='https://model.example.test/v1',
        model_identifier='northwind-test-model',
    )


def test_knowledge_grounded_agent_runs_one_scoped_lookup_and_replans_once() -> None:
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What information is needed after vehicle damage?',
                    }
                ]
            ),
            model_turn_output(),
        ]
    )
    chunk = KnowledgeChunk(
        document_id='nw-policy-motor-standard-mvp-2026-1',
        chunk_id='nw-policy-motor-standard-mvp-2026-1#MTR-EXC-01',
        title='Northwind Motor Standard Policy',
        document_type='synthetic_policy_wording',
        version='MVP-2026.1',
        section_path='MTR-EXC-01 - Excesses',
        page=None,
        source_uri='northwind://synthetic-policy/motor/MVP-2026.1',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        checksum='a7e4d4782f90571c7a711823fe14b1d580e13a867613a9a833a33a1fdc1ad989',
        ingested_at=datetime(2026, 8, 25, tzinfo=UTC),
        text=(
            'The base excess and any additional excess come only from the matching policy schedule.'
        ),
    )
    retriever = StaticKnowledgeRetriever([chunk])
    provider = KnowledgeGroundedAgent(GatewayAgent(gateway), retriever)
    claim = _working_claim().model_copy(update={'incident_type': 'motor'})
    branch = BranchRuleEvaluator().evaluate(claim, recomputation_reason='knowledge_test')

    proposal = provider.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses-knowledge',
            trigger_message_id='msg-knowledge',
            message_text='What information do you need about the vehicle damage?',
            evidence_refs=[],
            branch_evaluation=branch,
        )
    )

    assert len(gateway.requests) == 2
    assert len(retriever.requests) == 1
    search = retriever.requests[0]
    assert search.product == 'motor'
    assert search.jurisdiction == 'NZ'
    assert search.authority == 'northwind_synthetic_demo'
    replanned_content = gateway.requests[1].messages[1].content
    assert replanned_content is not None
    replanned_context = json.loads(replanned_content)
    assert replanned_context['knowledge_status'] == 'evidence_found'
    assert replanned_context['knowledge_citations'][0]['chunk_id'] == chunk.chunk_id
    assert replanned_context['knowledge_citations'][0]['checksum'] == chunk.checksum
    assert proposal.tool_results == [
        {
            'tool': 'knowledge_search',
            'status': 'evidence_found',
            'source_refs': [chunk.chunk_id],
            'limitations': [],
        }
    ]


def test_policy_lookup_replan_rejects_deprecated_legacy_action() -> None:
    protocol = 'policy_replan_success'
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'policy_history',
                        'operation': 'search_policy',
                        'policy_reference': 'synthetic-policy-101',
                        'question': 'Confirm the policy reference.',
                    }
                ]
            ),
            model_turn_output(
                action='CONFIRM',
                form_changes=[
                    {
                        'field_code': 'policy.policy_number',
                        'value': 'synthetic-policy-101',
                    }
                ],
                required_items=['policy.policy_number'],
            ),
        ]
    )
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    claimant = {'Authorization': 'Bearer synthetic-claimant'}

    with TestClient(
        create_app(
            model_gateway_settings(protocol),
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**claimant, 'Idempotency-Key': 'policy-replan-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        ).json()
        response = client.post(
            f'/api/v1/claims/{created["claim"]["claim_id"]}/sessions/'
            f'{created["session"]["session_id"]}/messages',
            headers={
                **claimant,
                'Idempotency-Key': 'policy-replan-turn',
                'If-Match': str(created['claim']['revision']),
            },
            json={
                'client_message_id': 'policy-replan-message',
                'content': {
                    'type': 'text',
                    'text': 'Please check policy synthetic-policy-101 for this motor claim.',
                },
                'evidence_refs': [],
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'LEGACY_AGENT_ACTION_DEPRECATED'
    assert len(gateway.requests) == 2
    stored = repository.get_claim(created['claim']['claim_id'], 'cus_demo')
    assert stored is not None
    assert stored.revision == created['claim']['revision']
    assert 'policy.policy_number' not in stored.form


@pytest.mark.parametrize(
    ('policy_reference', 'second_tools', 'expected_status', 'expected_code'),
    [
        ('missing-policy', [], 503, 'AGENT_TOOL_NOT_PERMITTED'),
        (
            'synthetic-policy-101',
            [
                {
                    'tool': 'claim_history',
                    'operation': 'search_claim_history',
                    'history_reference': 'synthetic-history-204',
                    'limit': 10,
                }
            ],
            502,
            'DEPENDENCY_FAILED',
        ),
    ],
)
def test_failed_or_second_context_round_cannot_mutate_claim(
    policy_reference: str,
    second_tools: list[dict[str, object]],
    expected_status: int,
    expected_code: str,
) -> None:
    protocol = f'policy_replan_rejected_{len(second_tools)}'
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'policy_history',
                        'operation': 'search_policy',
                        'policy_reference': policy_reference,
                    }
                ]
            ),
            model_turn_output(
                action='CONFIRM',
                required_tools=second_tools,
                form_changes=(
                    []
                    if second_tools
                    else [{'field_code': 'policy.policy_number', 'value': policy_reference}]
                ),
                required_items=[] if second_tools else ['policy.policy_number'],
            ),
        ]
    )
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    claimant = {'Authorization': 'Bearer synthetic-claimant'}

    with TestClient(
        create_app(
            model_gateway_settings(protocol),
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**claimant, 'Idempotency-Key': f'{protocol}-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        ).json()
        before = repository.get_claim(created['claim']['claim_id'], 'cus_demo')
        response = client.post(
            f'/api/v1/claims/{created["claim"]["claim_id"]}/sessions/'
            f'{created["session"]["session_id"]}/messages',
            headers={
                **claimant,
                'Idempotency-Key': f'{protocol}-turn',
                'If-Match': str(created['claim']['revision']),
            },
            json={
                'client_message_id': f'{protocol}-message',
                'content': {'type': 'text', 'text': 'Check the applicable policy.'},
                'evidence_refs': [],
            },
        )

    assert response.status_code == expected_status
    assert response.json()['error']['code'] == expected_code
    assert repository.get_claim(created['claim']['claim_id'], 'cus_demo') == before
    assert (
        repository.list_messages(
            created['claim']['claim_id'], created['session']['session_id'], 'cus_demo'
        )
        == []
    )
    assert repository.list_agent_decisions(created['claim']['claim_id'], 'cus_demo') == []


def submit_model_message(
    gateway: ModelGateway,
    *,
    protocol: str,
    message_text: str = 'A synthetic rear-end incident.',
    tools: bool = False,
    repository_setup: Callable[[FixtureRepository, str], None] | None = None,
) -> tuple[httpx.Response, FixtureRepository, WorkingClaim, str, str]:
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    with TestClient(
        create_app(
            replace(model_gateway_settings(protocol), model_supports_tools=tools),
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
        if repository_setup is not None:
            repository_setup(repository, claim_id)
        before_claim = repository.get_claim(claim_id, 'cus_demo')
        assert before_claim is not None
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': f'{protocol}-message',
                'If-Match': str(before_claim.revision),
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
                prompt_version='northwind-fnol-claimant-v6',
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
                prompt_version='northwind-fnol-claimant-v6',
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
            usage=ModelUsage(input_tokens=30, output_tokens=10, total_tokens=40),
            structured_output={
                'action': 'CREATE_CLAIM',
                'reason_codes': ['MODEL_SAYS_READY'],
                'customer_reason': 'The supplied details appear ready.',
                'customer_response': 'Your report is ready for the next controlled step.',
                'customer_next_step': {
                    'status': 'review_required',
                    'summary': 'Northwind must review claim creation.',
                    'responsible_party': 'claims_professional',
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
    operations = OperationRepository()
    agent = GatewayAgent(gateway, operations=ModelOperationsRecorder(operations))
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
            evidence_refs=[],
        )
    )

    assert gateway.last_request is not None
    assert gateway.last_request.response_schema is not None
    model_content = gateway.last_request.messages[1].content
    assert model_content is not None
    model_context = json.loads(model_content)
    assert set(model_context) == {
        'branch',
        'claim',
        'external_services',
        'message_text',
        'evidence_reference_count',
        'attached_evidence',
        'professional_review_required',
        'knowledge_status',
        'knowledge_citations',
        'knowledge_limitations',
        'tool_results',
        'provenance_messages',
        'conversation_history',
        'field_value_contracts',
    }
    assert model_context['external_services'] == []
    assert model_context['branch'] is None
    assert model_context['evidence_reference_count'] == 0
    assert model_context['attached_evidence'] == []
    assert model_context['knowledge_status'] == 'not_requested'
    assert model_context['knowledge_citations'] == []
    assert model_context['knowledge_limitations'] == []
    assert set(model_context['claim']) == {
        'channel',
        'locale',
        'incident_type',
        'claim_state',
        'form',
        'contents_items',
        'known_field_codes',
        'evidence_summary',
        'customer_next_step',
    }
    assert model_context['claim']['contents_items'] == []
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
        'precision',
        'source_refs',
    }
    serialised_context = json.dumps(model_context)
    for private_value in (
        'clm_private_gateway',
        'cus_private_gateway',
        'ses_private_gateway',
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
    assert model_context['claim']['form']['incident.description']['source_refs'] == [
        'msg_private_gateway'
    ]
    assert proposal.action is AgentAction.CREATE_CLAIM
    assert proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert proposal.model_provenance is not None
    assert proposal.model_provenance.provider_model == 'provider-model-private'
    assert proposal.model_provenance.provider_request_id == 'provider-request-private'
    assert proposal.model_provenance.prompt_id == 'northwind-fnol-claimant-v6'
    assert proposal.form_changes[0].source is FormSource.INFERENCE
    assert proposal.form_changes[0].status is FormStatus.PROPOSED
    authority = validate_proposal(proposal)
    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(proposal, authority) == []
    operation = operations.metrics_records()[0]
    assert operation.kind.value == 'model_invocation'
    assert operation.subject_id == 'agent_turn'
    assert operation.state.value == 'succeeded'
    assert operation.result is not None
    assert operation.result == {
        'purpose': 'agent_turn',
        'model_profile_id': 'qwen-local',
        'prompt_version': 'northwind-fnol-claimant-v6',
        'request_stage': 'initial',
        'invocation_ordinal': 1,
        'invocation_count': 1,
        'provider_model': 'provider-model-private',
        'input_tokens': 30,
        'output_tokens': 10,
        'total_tokens': 40,
        'latency_ms': operation.result['latency_ms'],
    }


def test_gateway_agent_receives_only_bounded_external_lifecycle_context() -> None:
    gateway = StaticGateway(ModelResponse(structured_output=_model_proposal_output()))
    lifecycle = build_lifecycle_projection(
        service_identity='vehicle_damage_assessment_routing',
        operation_status=ExternalLifecycleStatus.UNKNOWN_OUTCOME,
    )

    GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-external-context',
            trigger_message_id='msg-external-context',
            message_text='Did the assessor receive the request?',
            evidence_refs=[],
            external_services=(lifecycle,),
        )
    )

    assert gateway.last_request is not None
    model_content = gateway.last_request.messages[1].content
    assert model_content is not None
    model_context = json.loads(model_content)
    assert model_context['external_services'] == [lifecycle.model_dump(mode='json')]
    serialised_context = json.dumps(model_context['external_services'])
    assert 'provider_reference' not in serialised_context
    assert 'delivery_evidence' not in serialised_context
    assert 'staff_meaning' not in serialised_context


def test_message_turn_persists_selected_external_lifecycle_coordinates() -> None:
    def seed_external_task(repository: FixtureRepository, claim_id: str) -> None:
        timestamp = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
        repository.save_external_task(
            ExternalTaskRecord(
                task_id='task-runtime-context',
                claim_id=claim_id,
                service_identity=ASSESSOR_SERVICE_IDENTITY,
                requested_action=ASSESSOR_REQUESTED_ACTION,
                integration_source=IntegrationSource.FIXTURE,
                status=ExternalTaskOperationStatus.ACCEPTED,
                delivery=ExternalTaskDelivery.SUBMITTED,
                delivery_evidence='Controlled simulation acknowledgement.',
                provider_reference='simulation-reference',
                created_at=timestamp,
                updated_at=timestamp,
            ),
            'cus_demo',
        )
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None
        repository.save_claim(
            claim.model_copy(
                update={
                    'revision': claim.revision + 1,
                    'assessor_routing': AssessorRoutingResult(
                        routing_status=AssessorRoutingStatus.ASSIGNED,
                        assessor_reference='simulation-reference',
                        queue_reference='queue-runtime-context',
                        next_step='Await the simulated assessment.',
                    ),
                    'assessor_routing_fingerprint': 'runtime-context-fingerprint',
                }
            ),
            expected_revision=claim.revision,
        )

    gateway = RuntimeSequenceGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='external-lifecycle-read',
                        name='claim.read',
                        arguments={},
                    )
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output=_runtime_model_output(),
            ),
        ]
    )
    response, repository, _before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol='external_lifecycle_evidence',
        tools=True,
        repository_setup=seed_external_task,
    )

    assert response.status_code == 200, response.text
    model_context = json.loads(gateway.requests[-1].messages[1].content or '{}')
    assert model_context['external_services'][0]['operation_status'] == 'assigned'
    assert model_context['external_services'][0]['status_label'] == 'Assessor assigned'
    runtime_turn = repository.get_runtime_turn_for_trigger(
        claim_id,
        response.json()['claimant_message']['message_id'],
        'cus_demo',
    )
    assert runtime_turn is not None
    assert runtime_turn.turn_plan.registry_versions == {
        'external_service_lifecycle': 'external-service-lifecycle.v1'
    }
    assert [
        item.model_dump(mode='json') for item in runtime_turn.turn_plan.external_lifecycle_context
    ] == [
        {
            'registry_version': 'external-service-lifecycle.v1',
            'service_identity': ASSESSOR_SERVICE_IDENTITY,
            'operation_status': 'assigned',
            'result_status': None,
            'result_verification': None,
        }
    ]


def test_gateway_agent_receives_bounded_branch_context() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'ASK',
                'reason_codes': ['CONTINUE_INTAKE'],
                'customer_reason': 'More information is required.',
                'customer_response': 'Where did the incident happen?',
                'customer_next_step': {
                    'status': 'information_required',
                    'summary': 'Provide the incident location.',
                    'responsible_party': 'claimant',
                    'required_items': ['incident.location'],
                },
                'form_changes': [],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )
    agent = GatewayAgent(gateway)
    timestamp = datetime.now(UTC)
    claim = _working_claim().model_copy(
        update={
            'incident_type': 'motor',
            'form': {
                'incident.type': _form_field('collision', timestamp),
                'incident.description': _form_field('A rear-end collision.', timestamp),
                'vehicle.registration': _form_field('ABC123', timestamp),
                'property.address': _form_field('1 Example Street', timestamp),
                'claimant.client_number': _form_field('CLIENT-PRIVATE', timestamp),
            },
            'contents_items': [
                ContentsItem(
                    item_id='itm_existing',
                    description='Laptop computer',
                    category='electronics',
                    quantity=1,
                    loss_type=ContentsLossType.DAMAGED,
                    ownership=ContentsOwnership.OWNED,
                    source=FormSource.CLAIMANT,
                    source_refs=['msg_contents'],
                    status=FormStatus.CONFIRMED,
                    needed_for=NeededFor.CURRENT_ACTION,
                    confidence=1.0,
                    updated_at=timestamp,
                    updated_by=ActorReference(
                        actor_type=ActorType.CLAIMANT,
                        actor_id='cus_gateway',
                    ),
                )
            ],
        }
    )
    branch = BranchRuleEvaluator().evaluate(claim, recomputation_reason='model_context')
    branch = branch.model_copy(
        update={
            'field_selection': [
                item.model_copy(update={'selection_state': FieldSelectionState.SYSTEM_OWNED})
                if item.field_code == 'claimant.client_number'
                else item
                for item in branch.field_selection
            ]
        }
    )

    agent.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='Continue my motor claim.',
            evidence_refs=[],
            branch_evaluation=branch,
        )
    )

    assert gateway.last_request is not None
    model_content = gateway.last_request.messages[1].content
    assert model_content is not None
    model_context = json.loads(model_content)
    assert model_context['branch']['selected_family'] == 'motor'
    assert 'family.motor' in model_context['branch']['active_branches']
    assert 'vehicle.registration' in model_context['branch']['allowed_field_codes']
    assert 'property.address' not in model_context['branch']['allowed_field_codes']
    assert 'claimant.client_number' not in model_context['branch']['allowed_field_codes']
    assert model_context['claim']['form']['vehicle.registration']['value'] == 'ABC123'
    assert 'vehicle.registration' in model_context['claim']['known_field_codes']
    assert 'property.address' not in model_context['claim']['form']
    assert 'claimant.client_number' not in model_context['claim']['known_field_codes']
    assert model_context['claim']['contents_items'][0] == {
        'item_id': 'itm_existing',
        'description': 'Laptop computer',
        'category': 'electronics',
        'quantity': 1,
        'loss_type': 'damaged',
        'ownership': 'owned',
        'estimated_value': None,
        'source': 'claimant',
        'source_refs': ['msg_contents'],
        'status': 'confirmed',
        'resolution_state': 'resolved',
    }
    assert set(model_context['branch']) == {
        'field_registry_version',
        'branch_rules_version',
        'selected_family',
        'unresolved_family_conflict',
        'active_branches',
        'candidate_branches',
        'allowed_field_codes',
        'field_selection',
        'work_item_intents',
        'interruption_result',
        'permitted_actions',
        'permitted_tools',
        'satisfied_requirements',
        'missing_required_now',
        'pending_later',
        'next_required_item',
        'ready',
    }


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

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'LEGACY_AGENT_ACTION_DEPRECATED'
    assert_model_message_failure_is_atomic(
        repository,
        _before_claim,
        claim_id,
        session_id,
        protocol,
    )


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
    assert detail.work_summary.risk_signals == []


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

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'LEGACY_AGENT_ACTION_DEPRECATED'
    assert_model_message_failure_is_atomic(
        repository,
        _before_claim,
        claim_id,
        _session_id,
        protocol,
    )


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
                    'responsible_party': 'claims_professional',
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

    response, repository, before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol=protocol,
        message_text=message_text,
    )

    assert response.status_code == 200
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.revision == before_claim.revision + 1
    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].type.value == expected_type
    assert handoffs[0].trigger.value == expected_trigger
    assert handoffs[0].reason_codes == [expected_reason]
    assert gateway.call_count == 0


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

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'LEGACY_AGENT_ACTION_DEPRECATED'
    assert gateway.call_count == 1
    assert_model_message_failure_is_atomic(
        repository,
        _before_claim,
        claim_id,
        _session_id,
        protocol,
    )


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


def test_namespaced_model_handoff_on_routine_message_does_not_create_handoff() -> None:
    gateway = RuntimeSequenceGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='routine-read',
                        name='claim.read',
                        arguments={},
                    )
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    'action_code': 'human.create_handoff',
                    'runtime_action_code': 'runtime.pause_for_review',
                    'reason_codes': ['HUMAN_SUPPORT_REQUESTED'],
                    'customer_reason': 'Human support was requested.',
                    'customer_response': 'A staff member will review this report.',
                    'customer_next_step': {
                        'status': 'human_support_requested',
                        'summary': 'A staff member will review this report.',
                        'responsible_party': 'claims_professional',
                        'required_items': [],
                    },
                    'form_changes': [],
                    'contents_item_changes': [],
                    'source_refs': [],
                    'handoff_priority': 'standard',
                },
            ),
        ]
    )

    response, repository, before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol='runtime_forged_handoff',
        message_text='A routine update with no request for support.',
        tools=True,
    )

    assert response.status_code == 200
    assert repository.list_handoffs(claim_id, 'cus_demo') == []
    body = response.json()
    safe_response = (
        'I have recorded what you shared, but I could not safely apply the proposed next '
        'step. Your current report remains available.'
    )
    assert body['handoff'] is None
    assert body['agent_message']['content']['text'] == safe_response
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.revision == before_claim.revision + 1
    assert stored_claim.customer_next_step.status == 'action_not_applied'
    assert stored_claim.customer_next_step.responsible_party is ResponsibleParty.SYSTEM
    messages = repository.list_messages(claim_id, _session_id, 'cus_demo')
    assert any(message.actor is ActorType.CLAIMANT for message in messages)
    agent_messages = [message for message in messages if message.actor is ActorType.AGENT]
    assert len(agent_messages) == 1
    assert agent_messages[0].content['text'] == safe_response
    runtime_turn = repository.get_runtime_turn_for_trigger(
        claim_id,
        body['claimant_message']['message_id'],
        'cus_demo',
    )
    assert runtime_turn is not None
    assert runtime_turn.execution_plan.status == 'rejected'
    assert runtime_turn.result.status == 'blocked'
    assert runtime_turn.result.customer_response == safe_response
    assert 'staff member' not in runtime_turn.result.customer_response.casefold()


def test_explicit_human_request_uses_runtime_interrupt_before_model_gateway() -> None:
    gateway = RuntimeSequenceGateway([])

    response, repository, before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol='runtime_explicit_handoff',
        message_text='I want to speak to a staff member now.',
        tools=True,
    )

    assert response.status_code == 200
    assert gateway.requests == []
    handoffs = repository.list_handoffs(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert handoffs[0].support_need is SupportNeed.HUMAN_REQUESTED
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.revision == before_claim.revision + 1


def test_legacy_model_motor_journey_is_rejected_before_side_effects() -> None:
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
                    {'field_code': 'claim.product_family', 'value': 'motor'},
                    {'field_code': 'incident.type', 'value': 'collision'},
                    {
                        'field_code': 'incident.description',
                        'value': 'Another car hit the rear of mine on Queen Street.',
                    },
                    {'field_code': 'incident.occurred_at', 'value': 'around 10 this morning'},
                    {'field_code': 'incident.location', 'value': 'Queen Street'},
                    {'field_code': 'incident.injury_or_danger', 'value': False},
                    {'field_code': 'parties.other_parties', 'value': True},
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
        assert intake.status_code == 422, intake.text
        assert intake.json()['error']['code'] == 'LEGACY_AGENT_ACTION_DEPRECATED'
        stored_claim = repository.get_claim(claim_id, 'cus_demo')
        assert stored_claim is not None
        assert stored_claim.revision == 1
        assert repository.list_messages(claim_id, session_id, 'cus_demo') == []
        assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
        return
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
        handoffs = client.get(
            f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff
        ).json()['items']
        handoff_id = handoffs[0]['handoff_id']
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


def test_gateway_agent_preserves_structured_tool_request_for_runtime_validation() -> None:
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

    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='Look up my policy.',
            evidence_refs=[],
        )
    )

    assert proposal.required_tools == [{'tool': 'policy_history', 'operation': 'search_policy'}]


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


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('base_url', 'https://unapproved.example/v1'),
        ('credential_environment_variable', 'UNAPPROVED_PROCESS_SECRET'),
        ('purpose', 'batch_evaluation'),
        ('privacy_class', 'unrestricted'),
        ('prompt_version', 'northwind-fnol-motor-claimant-v2'),
        ('structured_output', False),
    ],
)
def test_published_model_cannot_override_runtime_authority(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_base_url='https://approved-model.example/v1',
        model_identifier='approved-model',
        model_api_key_env='NORTHWIND_MODEL_API_KEY',
    )
    repository = ConfigurationRepository()
    values: dict[str, object] = {
        'protocol': 'openai_compatible',
        'provider': 'untrusted-provider',
        'model_identifier': 'untrusted-model',
        'base_url': 'https://approved-model.example/v1',
        'credential_environment_variable': 'NORTHWIND_MODEL_API_KEY',
        'profile_id': 'untrusted-profile',
        'purpose': 'agent_turn',
        'privacy_class': 'synthetic_fnol',
        'prompt_version': 'northwind-fnol-motor-claimant-v4',
        'evaluation_status': 'configured',
        'timeout_seconds': 30,
        'structured_output': True,
        'tools': False,
    }
    values[field] = value
    repository.create(
        ConfigurationRecord(
            configuration_id='cfg_malicious',
            revision=3,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            domain='model',
            values=values,
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


def test_published_model_capabilities_project_image_and_document_support() -> None:
    settings = Settings(
        environment='test',
        data_runtime_profile=DataRuntimeProfile.FIXTURE,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='vision-profile',
        model_provider='synthetic-provider',
        model_identifier='vision-model',
        model_base_url='https://model.example.test/v1',
        model_supports_image_input=True,
        model_supports_document_input=True,
    )
    repository = ConfigurationRepository()
    repository.create(
        ConfigurationRecord(
            configuration_id='cfg_vision',
            configuration_key='vision-profile',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            domain='model',
            values={
                'protocol': 'openai_compatible',
                'provider': 'synthetic-provider',
                'model_identifier': 'vision-model',
                'base_url': 'https://model.example.test/v1',
                'credential_environment_variable': None,
                'profile_id': 'vision-profile',
                'purpose': 'agent_turn',
                'privacy_class': 'synthetic_fnol',
                'prompt_version': settings.model_prompt_version,
                'evaluation_status': 'configured',
                'timeout_seconds': 30,
                'structured_output': True,
                'tools': True,
                'image_input': True,
                'document_input': True,
            },
            secret_references={},
            author='test',
            reason='Publish multimodal test profile.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )

    gateway = ConfigurationBackedModelGateway(settings, repository, ModelGatewayRegistry())
    assert gateway.capabilities == ModelCapabilities(
        structured_output=True,
        tools=True,
        image_input=True,
        document_input=True,
    )


def test_configuration_backed_gateway_injects_only_the_call_resolver() -> None:
    resolver = EvidenceResolver(b'authorised-image')
    constructed: list[ModelGatewayConfig] = []
    registry = ModelGatewayRegistry()

    def build_recording_gateway(config: ModelGatewayConfig) -> ModelGateway:
        constructed.append(config)
        return StaticGateway(
            ModelResponse(text='ok', completion_status=ModelCompletionStatus.COMPLETE)
        )

    registry.register('openai_compatible', build_recording_gateway)
    settings = Settings(
        environment='test',
        data_runtime_profile=DataRuntimeProfile.FIXTURE,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='vision-profile',
        model_provider='synthetic-provider',
        model_identifier='vision-model',
        model_base_url='https://model.example.test/v1',
        model_supports_image_input=True,
    )
    gateway = ConfigurationBackedModelGateway(
        settings,
        ConfigurationRepository(),
        registry,
    )
    request = ModelRequest(
        model_profile_id='vision-profile',
        messages=[
            ModelMessage(
                role=ModelRole.USER,
                content_blocks=[
                    ModelEvidenceContent(evidence_id='evd_photo', media_type='image/png')
                ],
            )
        ],
        required_capabilities=ModelCapabilities(image_input=True),
    )

    gateway.complete_with_evidence(request, resolver)

    assert len(constructed) == 1
    assert constructed[0].evidence_resolver is resolver


def test_current_prompt_declares_the_namespaced_runtime_contract() -> None:
    prompt = load_motor_claimant_prompt()

    assert MOTOR_CLAIMANT_PROMPT_ID == 'northwind-fnol-claimant-v6'
    assert 'Prompt ID: `northwind-fnol-claimant-v6`' in prompt
    assert '`action_code` and `runtime_action_code`' in prompt
    assert '`conversation.answer` with `runtime.wait_for_user`' in prompt
    assert '`human.create_handoff` with `runtime.pause_for_review`' in prompt
    assert '`runtime.confirm_claimant_facts` is not a registered' in prompt
    assert 'Never return the deprecated `action`' in prompt


def test_prompt_identifier_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class InvalidPromptResource:
        def joinpath(self, _name: str) -> 'InvalidPromptResource':
            return self

        def read_text(self, **_kwargs: object) -> str:
            return 'Prompt ID: invalid'

    monkeypatch.setattr(
        'backend.prompts.files',
        lambda _package: InvalidPromptResource(),
    )

    with pytest.raises(RuntimeError, match='prompt ID does not match'):
        load_motor_claimant_prompt()
    with pytest.raises(RuntimeError, match='prompt ID does not match'):
        load_staff_assistant_prompt()


def test_snapshot_gateway_rejects_missing_model_configuration() -> None:
    gateway = ConfigurationBackedModelGateway(
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_protocol_adapter='openai_compatible',
            model_base_url='https://model.example.test/v1',
            model_identifier='northwind-test-model',
        ),
        ConfigurationRepository(),
        runtime_configuration_resolver=RuntimeConfigurationResolver(
            ConfigurationRepository(),
            ReleaseSetRepository(),
            environment='test',
            runtime_profile='fixture',
        ),
    )
    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel-missing-model',
        configurations={},
        integrations={},
        knowledge={},
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete_for_snapshot(ModelRequest(messages=[]), snapshot)

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION


def test_explicit_unpublished_profile_fails_closed_instead_of_falling_back() -> None:
    settings = Settings(
        environment='test',
        data_runtime_profile=DataRuntimeProfile.FIXTURE,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='qwen-local',
        model_provider='qwen-local',
        model_identifier='qwen3.8-27b',
        model_base_url='http://qwen.example.test/v1',
    )
    repository = ConfigurationRepository()
    repository.create(
        ConfigurationRecord(
            configuration_id='cfg_qwen_active',
            configuration_key='qwen-local',
            revision=1,
            state=ConfigurationState.PUBLISHED,
            impact=ConfigurationImpact.HIGH,
            domain='model',
            values={
                'protocol': 'openai_compatible',
                'provider': 'qwen-local',
                'model_identifier': 'qwen3.8-27b',
                'base_url': 'http://qwen.example.test/v1',
                'credential_environment_variable': None,
                'profile_id': 'qwen-local',
                'purpose': 'agent_turn',
                'privacy_class': 'synthetic_fnol',
                'prompt_version': settings.model_prompt_version,
                'evaluation_status': 'configured',
                'timeout_seconds': 30,
                'structured_output': True,
                'tools': True,
            },
            author='test',
            reason='Published Qwen profile must not capture an explicit GPT turn.',
            updated_at=now_utc(),
        )
    )
    constructed: list[ModelGatewayConfig] = []
    registry = ModelGatewayRegistry()

    def build_recording_gateway(config: ModelGatewayConfig) -> ModelGateway:
        constructed.append(config)
        return StaticGateway(
            ModelResponse(text='ok', completion_status=ModelCompletionStatus.COMPLETE)
        )

    registry.register('openai_compatible', build_recording_gateway)
    gateway = ConfigurationBackedModelGateway(
        settings,
        repository,
        registry,
        runtime_configuration_resolver=RuntimeConfigurationResolver(
            repository,
            ReleaseSetRepository(),
            environment='test',
            runtime_profile='fixture',
        ),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(model_profile_id='nowcoding-gpt54mini', messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert constructed == []


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


def test_gateway_agent_uses_the_published_snapshot_completion_path() -> None:
    response = model_turn_output()

    class SnapshotGateway(StaticGateway):
        def complete(self, _request: ModelRequest) -> ModelResponse:
            raise AssertionError('the snapshot completion path should be selected')

        def complete_for_snapshot(
            self, request: ModelRequest, snapshot: RuntimeConfigurationSnapshot
        ) -> ModelResponse:
            self.call_count += 1
            self.last_request = request
            self.snapshot = snapshot
            return self.response

    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel_vp',
        configurations={},
        integrations={},
        knowledge={},
    )
    gateway = SnapshotGateway(response)
    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-snapshot',
            trigger_message_id='msg-snapshot',
            message_text='A routine update.',
            evidence_refs=[],
            runtime_configuration_snapshot=snapshot,
        )
    )

    assert proposal.action is AgentAction.UPDATE
    assert gateway.call_count == 1
    assert gateway.snapshot is snapshot


def test_snapshot_tool_continuation_rejects_invalid_output() -> None:
    class SnapshotRuntimeGateway(RuntimeSequenceGateway):
        def complete(self, _request: ModelRequest) -> ModelResponse:
            raise AssertionError('snapshot completion must be used for both calls')

        def complete_for_snapshot(
            self, request: ModelRequest, snapshot: RuntimeConfigurationSnapshot
        ) -> ModelResponse:
            self.requests.append(request)
            self.snapshot = snapshot
            return self.responses.pop(0)

    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel-vp-runtime',
        configurations={},
        integrations={},
        knowledge={},
    )
    gateway = SnapshotRuntimeGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='call-1', name='claim.read', arguments={})],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={'not': 'a runtime proposal'},
            ),
        ]
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-snapshot-runtime',
                trigger_message_id='msg-snapshot-runtime',
                message_text='Read the current report.',
                evidence_refs=[],
                runtime_configuration_snapshot=snapshot,
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE
    assert len(gateway.requests) == 2
    assert gateway.snapshot is snapshot


@pytest.mark.parametrize(
    ('response', 'expected_code'),
    [
        (
            ModelResponse(completion_status=ModelCompletionStatus.INCOMPLETE),
            ModelGatewayErrorCode.INCOMPLETE_RESPONSE,
        ),
        (
            ModelResponse(completion_status=ModelCompletionStatus.REFUSED),
            ModelGatewayErrorCode.REFUSED_RESPONSE,
        ),
        (
            ModelResponse(completion_status=ModelCompletionStatus.UNKNOWN),
            ModelGatewayErrorCode.MALFORMED_RESPONSE,
        ),
        (
            ModelResponse(completion_status=ModelCompletionStatus.COMPLETE),
            ModelGatewayErrorCode.MALFORMED_RESPONSE,
        ),
        (
            ModelResponse(
                structured_output=_model_proposal_output(),
                tool_calls=[ModelToolCall(call_id='call-1', name='unknown', arguments={})],
            ),
            ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
        ),
    ],
)
def test_gateway_agent_rejects_non_complete_or_unsafe_provider_results(
    response: ModelResponse,
    expected_code: ModelGatewayErrorCode,
) -> None:
    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(StaticGateway(response)).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-invalid-response',
                trigger_message_id='msg-invalid-response',
                message_text='A routine update.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is expected_code


@pytest.mark.parametrize(
    ('first_response', 'continuation'),
    [
        (
            ModelResponse(completion_status=ModelCompletionStatus.COMPLETE),
            None,
        ),
        (
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(call_id='call-1', name='claim.read', arguments={}),
                    ModelToolCall(call_id='call-2', name='claim.read', arguments={}),
                ],
            ),
            None,
        ),
        (
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='call-1', name='unknown', arguments={})],
            ),
            None,
        ),
        (
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='call-1', name='claim.read', arguments={'unexpected': True}
                    )
                ],
            ),
            None,
        ),
        (
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='call-1', name='claim.read', arguments={})],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    **_runtime_model_output(),
                    'action_code': 'legacy.update',
                },
            ),
        ),
        (
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[ModelToolCall(call_id='call-1', name='claim.read', arguments={})],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    **_runtime_model_output(),
                    'runtime_action_code': 'runtime.execute',
                },
            ),
        ),
    ],
)
def test_runtime_gateway_rejects_tool_loop_contract_errors(
    first_response: ModelResponse,
    continuation: ModelResponse | None,
) -> None:
    responses = [first_response]
    if continuation is not None:
        responses.append(continuation)
    gateway = RuntimeSequenceGateway(responses)

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-runtime-error',
                trigger_message_id='msg-runtime-error',
                message_text='Read the current report.',
                evidence_refs=[],
            )
        )

    assert captured.value.code in {
        ModelGatewayErrorCode.MALFORMED_RESPONSE,
        ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
    }


def test_gateway_agent_preserves_claimant_support_and_marks_inference() -> None:
    gateway = StaticGateway(
        ModelResponse(
            provider_model='vp-model',
            provider_request_id='vp-request',
            structured_output=_model_proposal_output(
                form_changes=[
                    {
                        'field_code': 'incident.description',
                        'value': 'rear bumper',
                        'reported_text': 'The rear bumper',
                    },
                    {
                        'field_code': 'claim.product_family',
                        'value': 'motor',
                        'reported_text': 'motor claim',
                    },
                    {
                        'field_code': 'property.affected_areas',
                        'value': 'kitchen and roof',
                        'reported_text': 'the kitchen and roof',
                    },
                    {
                        'field_code': 'incident.injury_or_danger',
                        'value': 'false',
                        'reported_text': 'nobody was injured',
                    },
                    {
                        'field_code': 'parties.other_parties',
                        'value': True,
                        'reported_text': 'another vehicle was involved',
                    },
                    {
                        'field_code': 'incident.occurred_at',
                        'value': 123,
                        'reported_text': 'yesterday',
                    },
                ]
            ),
        )
    )
    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-provenance',
            trigger_message_id='msg-provenance',
            message_text=(
                'This is a motor claim. The rear bumper was damaged in the kitchen and roof. '
                'Nobody was injured, another vehicle was involved, and it happened yesterday.'
            ),
            evidence_refs=[],
        )
    )

    sources = {change.field_code: change.source for change in proposal.form_changes}
    assert sources['incident.description'] is FormSource.CLAIMANT
    assert sources['claim.product_family'] is FormSource.CLAIMANT
    assert sources['property.affected_areas'] is FormSource.CLAIMANT
    assert next(
        change.value
        for change in proposal.form_changes
        if change.field_code == 'property.affected_areas'
    ) == ['kitchen', 'roof']
    assert sources['incident.injury_or_danger'] is FormSource.CLAIMANT
    assert (
        next(
            change.value
            for change in proposal.form_changes
            if change.field_code == 'incident.injury_or_danger'
        )
        is False
    )
    assert sources['parties.other_parties'] is FormSource.CLAIMANT
    assert sources['incident.occurred_at'] is FormSource.INFERENCE


def test_gateway_agent_rejects_unquoted_and_unmapped_claimant_evidence() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output=_model_proposal_output(
                form_changes=[
                    {
                        'field_code': 'incident.description',
                        'value': 'rear bumper',
                        'reported_text': '   ',
                    },
                    {
                        'field_code': 'claim.product_family',
                        'value': 'motor',
                        'reported_text': 'vehicle incident',
                    },
                ]
            )
        )
    )
    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-unquoted-evidence',
            trigger_message_id='msg-unquoted-evidence',
            message_text='A vehicle incident happened; it is a motor claim.',
            evidence_refs=[],
        )
    )

    assert proposal.form_changes[0].source is FormSource.INFERENCE
    assert proposal.form_changes[1].source is FormSource.CLAIMANT


def test_knowledge_grounded_agent_returns_no_evidence_without_confirmed_product() -> None:
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    }
                ]
            ),
            model_turn_output(),
        ]
    )
    proposal = KnowledgeGroundedAgent(
        GatewayAgent(gateway), StaticKnowledgeRetriever([])
    ).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-no-product',
            trigger_message_id='msg-no-product',
            message_text='What happens next?',
            evidence_refs=[],
        )
    )

    assert proposal.tool_results[0]['status'] == 'no_evidence'
    assert proposal.tool_results[0]['source_refs'] == []
    assert gateway.requests[1]


def test_knowledge_grounded_agent_fails_closed_when_release_has_no_product() -> None:
    class MissingKnowledgeRelease:
        def resolve_knowledge(self, product: str) -> object:
            assert product == 'motor'
            raise RuntimeConfigurationResolutionError('knowledge is not selected')

    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    }
                ]
            ),
            model_turn_output(),
        ]
    )
    resolver = cast(RuntimeConfigurationResolver, MissingKnowledgeRelease())
    proposal = KnowledgeGroundedAgent(
        GatewayAgent(gateway),
        StaticKnowledgeRetriever([]),
        runtime_configuration_resolver=resolver,
    ).propose_turn(
        AgentTurnContext(
            claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
            session_id='ses-no-release-knowledge',
            trigger_message_id='msg-no-release-knowledge',
            message_text='What happens next?',
            evidence_refs=[],
        )
    )

    assert proposal.tool_results[0]['status'] == 'unavailable'
    assert proposal.tool_results[0]['source_refs'] == []


def test_knowledge_grounded_agent_honours_snapshot_knowledge_selection() -> None:
    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel_without_motor_knowledge',
        configurations={},
        integrations={},
        knowledge={},
    )
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    }
                ]
            ),
            model_turn_output(),
        ]
    )
    proposal = KnowledgeGroundedAgent(
        GatewayAgent(gateway), StaticKnowledgeRetriever([])
    ).propose_turn(
        AgentTurnContext(
            claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
            session_id='ses-snapshot-knowledge',
            trigger_message_id='msg-snapshot-knowledge',
            message_text='What happens next?',
            evidence_refs=[],
            runtime_configuration_snapshot=snapshot,
        )
    )

    assert proposal.tool_results[0]['status'] == 'unavailable'
    assert proposal.tool_results[0]['source_refs'] == []


@pytest.mark.parametrize(
    ('runtime_policy', 'knowledge_status'),
    [
        (
            type(
                'Policy',
                (),
                {
                    'instruction': type(
                        'Instruction',
                        (),
                        {'system_prompt': 'test', 'prompt_version': 'test'},
                    )(),
                    'tool_policy': type('Tools', (), {'allowed_tool_names': []})(),
                    'features': type('Features', (), {'knowledge_retrieval': True})(),
                },
            )(),
            'not_requested',
        ),
        (
            type(
                'Policy',
                (),
                {
                    'instruction': type(
                        'Instruction',
                        (),
                        {'system_prompt': 'test', 'prompt_version': 'test'},
                    )(),
                    'tool_policy': type(
                        'Tools', (), {'allowed_tool_names': ['knowledge_search']}
                    )(),
                    'features': type('Features', (), {'knowledge_retrieval': True})(),
                },
            )(),
            'evidence_found',
        ),
    ],
)
def test_knowledge_grounded_agent_rejects_disallowed_or_repeated_context_lookup(
    runtime_policy: object,
    knowledge_status: str,
) -> None:
    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    }
                ]
            )
        ]
    )
    with pytest.raises(ModelGatewayError) as captured:
        KnowledgeGroundedAgent(GatewayAgent(gateway), StaticKnowledgeRetriever([])).propose_turn(
            AgentTurnContext(
                claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
                session_id='ses-policy-lookup',
                trigger_message_id='msg-policy-lookup',
                message_text='What happens next?',
                evidence_refs=[],
                knowledge_status=knowledge_status,
                runtime_policy=runtime_policy,  # type: ignore[arg-type]
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize('retrieval_result', ['empty', 'unavailable'])
def test_knowledge_grounded_agent_preserves_bounded_retrieval_failure(
    retrieval_result: str,
) -> None:
    class Retriever:
        def connection_status(self) -> str:
            return 'fixture'

        def search(self, _request: KnowledgeSearch) -> list[KnowledgeChunk]:
            if retrieval_result == 'unavailable':
                raise KnowledgeRetrievalUnavailable('temporary outage')
            return []

    gateway = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    }
                ]
            ),
            model_turn_output(),
        ]
    )
    proposal = KnowledgeGroundedAgent(GatewayAgent(gateway), Retriever()).propose_turn(
        AgentTurnContext(
            claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
            session_id='ses-retrieval-outcome',
            trigger_message_id='msg-retrieval-outcome',
            message_text='What happens next?',
            evidence_refs=[],
        )
    )

    assert proposal.tool_results[0]['status'] == (
        'unavailable' if retrieval_result == 'unavailable' else 'no_evidence'
    )
    assert proposal.tool_results[0]['source_refs'] == []


def test_knowledge_grounded_agent_rejects_malformed_or_repeated_tool_requests() -> None:
    malformed = SequencedGateway(
        [
            model_turn_output(
                required_tools=[{'tool': 'knowledge_search', 'operation': 'search', 'query': ''}]
            )
        ]
    )
    with pytest.raises(ModelGatewayError) as malformed_error:
        KnowledgeGroundedAgent(GatewayAgent(malformed), StaticKnowledgeRetriever([])).propose_turn(
            AgentTurnContext(
                claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
                session_id='ses-malformed-tool',
                trigger_message_id='msg-malformed-tool',
                message_text='Search for the next step.',
                evidence_refs=[],
            )
        )
    assert malformed_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE

    repeated = SequencedGateway(
        [
            model_turn_output(
                required_tools=[
                    {
                        'tool': 'knowledge_search',
                        'operation': 'search',
                        'query': 'What is the next step?',
                    },
                    {
                        'tool': 'policy_history',
                        'operation': 'search_policy',
                        'query': 'What is my policy?',
                    },
                ]
            )
        ]
    )
    with pytest.raises(ModelGatewayError) as repeated_error:
        KnowledgeGroundedAgent(GatewayAgent(repeated), StaticKnowledgeRetriever([])).propose_turn(
            AgentTurnContext(
                claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
                session_id='ses-repeated-tool',
                trigger_message_id='msg-repeated-tool',
                message_text='Search for the next step.',
                evidence_refs=[],
            )
        )
    assert repeated_error.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_knowledge_grounded_agent_rejects_a_second_context_tool_after_replan() -> None:
    request: dict[str, object] = {
        'tool': 'knowledge_search',
        'operation': 'search',
        'query': 'What is the next step?',
    }
    gateway = SequencedGateway(
        [model_turn_output(required_tools=[request]), model_turn_output(required_tools=[request])]
    )

    with pytest.raises(ModelGatewayError) as captured:
        KnowledgeGroundedAgent(GatewayAgent(gateway), StaticKnowledgeRetriever([])).propose_turn(
            AgentTurnContext(
                claim=_working_claim().model_copy(update={'incident_type': 'motor'}),
                session_id='ses-second-tool',
                trigger_message_id='msg-second-tool',
                message_text='Search for the next step.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
