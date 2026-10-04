import base64
import json
import os
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.knowledge import FixtureKnowledgeDocumentStore, FixtureKnowledgeRetriever
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
from backend.core.config import AgentRuntimeProfile, DataRuntimeProfile, IdentityMode, Settings
from backend.core.model_gateway import ConfigurationBackedModelGateway
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    now_utc,
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
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    MessageVisibility,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.prompts import load_staff_assistant_prompt
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.fixture import FixtureRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.model_agent import GatewayAgent, KnowledgeGroundedAgent
from backend.services.prompt_composer import load_response_schemas
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)
from tests.journey_v8_support import envelope
from tests.test_agent_context_runtime_v7 import _context, _knowledge_chunk, _RecordingGateway


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
    structured_output_method: str = 'json_schema',
    reasoning_mode: str = 'provider_default',
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
        structured_output_method=structured_output_method,
        profile=ModelProfile(
            profile_id='test-profile',
            protocol=protocol,
            provider='synthetic-provider',
            model_identifier=model,
            credential_reference=credential_environment_variable,
            purpose=purpose,
            privacy_class=privacy_class,
            capabilities=capabilities,
            structured_output_method=structured_output_method,
            timeout_seconds=5.0,
            prompt_version=prompt_version,
            evaluation_status=evaluation_status,
        ),
        reasoning_mode=reasoning_mode,
        evidence_resolver=evidence_resolver,  # type: ignore[arg-type]
    )


class EvidenceResolver:
    def __init__(self, content: bytes | None = b'synthetic-evidence') -> None:
        self.content = content
        self.requests: list[tuple[str, str]] = []

    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        self.requests.append((evidence_id, media_type))
        return self.content


@pytest.mark.parametrize(
    ('media_type', 'required_capabilities', 'expected_block'),
    [
        (
            'image/png',
            ModelCapabilities(image_input=True),
            {
                'type': 'image_url',
                'image_url': {'url': 'data:image/png;base64,c3ludGhldGljLWV2aWRlbmNl'},
            },
        ),
        (
            'application/pdf',
            ModelCapabilities(document_input=True),
            {
                'type': 'file',
                'file': {
                    'file_data': ('data:application/pdf;base64,c3ludGhldGljLWV2aWRlbmNl'),
                    'filename': 'evd_authorised',
                },
            },
        ),
    ],
)
def test_openai_compatible_maps_authorised_evidence_blocks_without_storage_metadata(
    media_type: str,
    required_capabilities: ModelCapabilities,
    expected_block: dict[str, object],
) -> None:
    resolver = EvidenceResolver()
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
            image_input=required_capabilities.image_input,
            document_input=required_capabilities.document_input,
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
                        ModelEvidenceContent(
                            evidence_id='evd_authorised',
                            media_type=media_type,
                        ),
                    ],
                )
            ],
            required_capabilities=required_capabilities,
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    message = cast(list[dict[str, object]], payload['messages'])[0]
    content = cast(list[dict[str, object]], message['content'])
    assert content[0] == {'type': 'text', 'text': 'Inspect this.'}
    assert content[1] == expected_block
    assert 'storage_key' not in json.dumps(payload)
    assert resolver.requests == [('evd_authorised', media_type)]
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


def test_openai_compatible_disables_provider_thinking_from_binding() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]},
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(reasoning_mode='disabled'),
        transport=httpx.MockTransport(handler),
    )
    gateway.complete(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content='Answer.')]))

    payload = cast(dict[str, object], observed['payload'])
    assert payload['chat_template_kwargs'] == {'enable_thinking': False}


def test_openai_compatible_json_object_mode_avoids_provider_grammar_schema() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'content': '{"answer":"ok"}'},
                    }
                ]
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(structured_output_method='json_object'),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Answer.')],
            response_schema={
                'type': 'object',
                'properties': {'answer': {'type': 'string'}},
                'required': ['answer'],
            },
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    assert payload['response_format'] == {'type': 'json_object'}
    messages = cast(list[dict[str, object]], payload['messages'])
    assert messages[0]['role'] == 'system'
    assert '"answer":{"type":"string"}' in str(messages[0]['content'])
    assert response.structured_output == {'answer': 'ok'}


def test_qwen_json_object_mode_flattens_consumed_tool_history() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'content': '{"answer":"ok"}'},
                    }
                ]
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(
            structured_output_method='json_object',
            model='qwen3.8-27b',
        ),
        transport=httpx.MockTransport(handler),
    )
    gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.USER, content='Read the Claim.'),
                ModelMessage(
                    role=ModelRole.ASSISTANT,
                    content='',
                    tool_calls=[ModelToolCall(call_id='call-1', name='claim.read', arguments={})],
                ),
                ModelMessage(
                    role=ModelRole.TOOL,
                    name='claim.read',
                    tool_call_id='call-1',
                    content='{"claim_id":"clm_test"}',
                ),
            ],
            response_schema={'type': 'object'},
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    messages = cast(list[dict[str, object]], payload['messages'])
    assert messages[2] == {'role': 'assistant', 'content': ''}
    assert messages[3] == {
        'role': 'user',
        'content': 'Tool result (claim.read): {"claim_id":"clm_test"}',
    }


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


def test_every_registered_claimant_schema_materializes_for_openai_and_bedrock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_V7_BEDROCK_TOKEN', 'synthetic-token')
    schemas = load_response_schemas()
    assert set(schemas) == {
        'claimant.evidence-action.v1',
        'claimant.sourced-summary.v1',
        'claimant.turn.v1',
    }

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


def test_google_generate_content_uses_provider_compatible_schema_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_GEMINI_API_KEY', 'synthetic-google-key')
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'candidates': [
                    {
                        'finishReason': 'STOP',
                        'content': {
                            'role': 'model',
                            'parts': [{'text': '{"items":[]}'}],
                        },
                    }
                ]
            },
        )

    schema = {
        'type': 'object',
        'additionalProperties': False,
        'required': ['items'],
        'properties': {
            'items': {
                'type': 'array',
                'minItems': 0,
                'maxItems': 3,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['code', 'score'],
                    'properties': {
                        'code': {
                            'type': 'string',
                            'enum': ['damage'],
                            'minLength': 1,
                            'maxLength': 100,
                            'pattern': '^[a-z]+$',
                        },
                        'score': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    },
                },
            }
        },
    }
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            protocol='google_generate_content',
            credential_environment_variable='TEST_GEMINI_API_KEY',
        ),
        transport=httpx.MockTransport(handler),
    )

    gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Return a bounded result.')],
            response_schema=schema,
        )
    )

    payload = cast(dict[str, object], observed['payload'])
    generation_config = cast(dict[str, object], payload['generationConfig'])
    provider_schema = cast(dict[str, object], generation_config['responseJsonSchema'])
    serialised = json.dumps(provider_schema)
    for omitted in (
        'additionalProperties',
        'maxItems',
        'maxLength',
        'maximum',
        'minItems',
        'minLength',
        'minimum',
        'pattern',
    ):
        assert omitted not in serialised
    assert provider_schema['required'] == ['items']
    assert '"enum": ["damage"]' in serialised
    assert schema['additionalProperties'] is False


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
        (
            {'required_capabilities': ModelCapabilities(document_input=True)},
            {'document_input': False},
        ),
    ],
    ids=[
        'purpose',
        'privacy',
        'prompt',
        'explicit-structured-output',
        'explicit-tools',
        'explicit-document-input',
    ],
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


@pytest.mark.parametrize('clause_ids', [['MTR-BEN-03', 'UNKNOWN'], [], ['UNKNOWN']])
def test_knowledge_grounded_lookup_selects_full_clauses_and_records_trace(
    clause_ids: list[str],
) -> None:
    context = _context('Will my policy pay for a rental car while mine is repaired?')
    assert context.runtime_configuration_snapshot is not None
    context = replace(
        context,
        runtime_configuration_snapshot=replace(
            context.runtime_configuration_snapshot, release_set_id=None
        ),
        claim=context.claim.model_copy(
            update={
                'form': {
                    'claim.product_family': StructuredFormField(
                        value='motor',
                        source=FormSource.CLAIMANT,
                        status=FormStatus.CONFIRMED,
                        needed_for=NeededFor.CURRENT_ACTION,
                        updated_at=datetime.now(UTC),
                        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_v7'),
                    ),
                }
            }
        ),
        policy_context_loader=lambda _limit: {
            'status': 'evidence_found',
            'facts': {'coverage_sections': ['alternative_transport']},
        },
    )
    text = 'A complete synthetic rental benefit. ' * 24 + 'Only if the schedule includes it.'
    chunk = replace(
        _knowledge_chunk(),
        chunk_id='nw-policy-motor-standard#MTR-BEN-03',
        version='2026.2',
        section_path='MTR-BEN-03 - Hire car and rental car',
        text=text,
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='call_selected_clauses',
                        name='context.resolve',
                        arguments={
                            'ref': 'ctxref:ses_v7:policy.current',
                            'selector': 'matching_facts_and_guidance',
                            'max_tokens': 1200,
                            'clause_ids': clause_ids,
                        },
                    )
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output=envelope(reply='Staff can confirm the policy terms.'),
            ),
        ]
    )
    agent = KnowledgeGroundedAgent(
        GatewayAgent(gateway), FixtureKnowledgeRetriever(FixtureKnowledgeDocumentStore((chunk,)))
    )
    proposal = agent.propose_turn(context)
    assert len(gateway.requests) == 2
    initial = json.dumps([message.content for message in gateway.requests[0].messages])
    assert 'policy_clause_directory' in initial
    assert 'Hire car and rental car' in initial
    tool_message = next(
        message for message in gateway.requests[1].messages if message.role is ModelRole.TOOL
    )
    result = json.loads(str(tool_message.content))['content']
    guidance = result['approved_guidance']
    expected = ['MTR-BEN-03'] if 'MTR-BEN-03' in clause_ids else []
    assert guidance['returned_clause_ids'] == expected
    assert guidance['not_found'] == (['UNKNOWN'] if 'UNKNOWN' in clause_ids else [])
    assert result['policy']['facts']['coverage_sections'] == ['alternative_transport']
    if expected:
        assert guidance['chunks'][0]['text'] == text
        assert len(text) > 600
        assert set(guidance['chunks'][0]) == {'chunk_id', 'text'}
    else:
        assert guidance['chunks'] == []
    if not clause_ids:
        assert guidance['guidance_status'] == 'no_clause_selected'
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.tool_arguments['clause_ids'] == clause_ids
    if clause_ids:
        assert proposal.runtime_trace.tool_output['requested_clause_ids'] == clause_ids
    assert proposal.runtime_trace.tool_output['returned_clause_ids'] == expected
    assert proposal.runtime_trace.tool_output['policy_clause_directory'] == [
        {'clause_id': 'MTR-BEN-03', 'title': 'Hire car and rental car'}
    ]


@pytest.mark.parametrize('product', ['motor', 'home', 'contents'])
def test_knowledge_grounded_lookup_fits_three_longest_current_clauses_with_schedule(
    product: str,
) -> None:
    corpus = (
        Path(__file__).resolve().parents[1]
        / 'config'
        / 'knowledge-source-corpus'
        / f'northwind-{product}-standard-policy-2026.2.md'
    ).read_text(encoding='utf-8')
    sections = sorted(
        re.finditer(r'(?ms)^## ([A-Z]{3}-[A-Z]+-\d+) - ([^\n]+)\n.*?(?=^## |\Z)', corpus),
        key=lambda item: len(item.group()),
        reverse=True,
    )
    assert len(sections) >= 3
    selected = sections[:3]
    clause_ids = [item.group(1) for item in selected]
    context = _context('What does my policy say about this damage?', incident_type=product)
    assert context.runtime_configuration_snapshot is not None
    context = replace(
        context,
        runtime_configuration_snapshot=replace(
            context.runtime_configuration_snapshot, release_set_id=None
        ),
        claim=context.claim.model_copy(
            update={
                'form': {
                    'claim.product_family': StructuredFormField(
                        value=product,
                        source=FormSource.CLAIMANT,
                        status=FormStatus.CONFIRMED,
                        needed_for=NeededFor.CURRENT_ACTION,
                        updated_at=datetime.now(UTC),
                        updated_by=ActorReference(
                            actor_type=ActorType.CLAIMANT, actor_id='cus_v7'
                        ),
                    ),
                }
            }
        ),
        policy_context_loader=lambda _limit: {
            'status': 'evidence_found',
            'source_refs': ['ret_synthetic_policy'],
            'facts': {
                'policy_reference': 'NW-MTR-204518',
                'product': product,
                'status': 'active',
                'effective_from': '2026-01-01T00:00:00Z',
                'effective_to': '2027-01-01T00:00:00Z',
                'excess_amount': 500,
                'currency': 'NZD',
                'coverage_sections': [
                    'accidental_damage',
                    'third_party_liability',
                    'alternative_transport',
                ],
            },
            'uncertainty': [],
            'limitations': [],
        },
    )
    chunks = tuple(
        replace(
            _knowledge_chunk(),
            document_id=f'nw-policy-{product}-standard',
            chunk_id=f'nw-policy-{product}-standard#{item.group(1)}',
            product=product,
            version='2026.2',
            section_path=f'{item.group(1)} - {item.group(2)}',
            text=item.group().strip(),
        )
        for item in selected
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id='call_three_clauses',
                        name='context.resolve',
                        arguments={
                            'ref': 'ctxref:ses_v7:policy.current',
                            'selector': 'matching_facts_and_guidance',
                            'max_tokens': 1200,
                            'clause_ids': clause_ids,
                        },
                    )
                ],
            ),
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output=envelope(reply='Staff can confirm the policy terms.'),
            ),
        ]
    )
    proposal = KnowledgeGroundedAgent(
        GatewayAgent(gateway), FixtureKnowledgeRetriever(FixtureKnowledgeDocumentStore(chunks))
    ).propose_turn(context)
    tool_message = next(
        message for message in gateway.requests[1].messages if message.role is ModelRole.TOOL
    )
    resolved = json.loads(str(tool_message.content))
    assert resolved['actual_tokens'] <= 1200
    guidance = resolved['content']['approved_guidance']
    assert guidance['returned_clause_ids'] == clause_ids
    assert [item['text'] for item in guidance['chunks']] == [
        item.group().strip() for item in selected
    ]
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.tool_output['returned_clause_ids'] == clause_ids


@pytest.mark.parametrize('failure', ['manifest', 'store', 'disabled', 'unresolved'])
def test_knowledge_grounded_lookup_unavailable_has_no_citable_chunks(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    context = _context('What does my policy say?')
    context = replace(context, runtime_configuration_snapshot=None)
    if failure != 'unresolved':
        context = replace(
            context,
            claim=context.claim.model_copy(
                update={
                    'form': {
                        'claim.product_family': StructuredFormField(
                            value='motor',
                            source=FormSource.CLAIMANT,
                            status=FormStatus.CONFIRMED,
                            needed_for=NeededFor.CURRENT_ACTION,
                            updated_at=datetime.now(UTC),
                            updated_by=ActorReference(
                                actor_type=ActorType.CLAIMANT, actor_id='cus_v7'
                            ),
                        ),
                    }
                }
            ),
        )
    retriever = FixtureKnowledgeRetriever(FixtureKnowledgeDocumentStore())
    if failure == 'manifest':
        monkeypatch.setattr(
            'backend.services.model_agent.approved_version_for_product', lambda _: None
        )
    elif failure == 'store':

        def unavailable(_scope: KnowledgeSearch) -> list[KnowledgeChunk]:
            raise KnowledgeRetrievalUnavailable('Synthetic outage')

        monkeypatch.setattr(retriever, 'list_clauses', unavailable)
        monkeypatch.setattr(retriever, 'get_clauses', lambda scope, _ids: unavailable(scope))
    elif failure == 'disabled':
        assert context.runtime_policy is not None
        context = replace(
            context,
            runtime_policy=replace(
                context.runtime_policy,
                features=context.runtime_policy.features.model_copy(
                    update={'knowledge_retrieval': False}
                ),
            ),
        )
    else:
        context = replace(context, claim=context.claim.model_copy(update={'incident_type': None}))
    agent = KnowledgeGroundedAgent(GatewayAgent(_RecordingGateway([])), retriever)
    scope = agent._knowledge_scope(context)
    directory = agent._clause_directory(scope)
    result = agent._v7_knowledge_context(scope, 1200, ['MTR-BEN-03'])
    assert directory['policy_clause_directory'] == []
    assert result['chunks'] == []
    assert result['returned_clause_ids'] == []
    assert result['status'] == ('no_evidence' if failure == 'unresolved' else 'unavailable')


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
        model_profile_id='synthetic-model',
        model_provider='synthetic-provider',
        model_base_url='https://model.example.test/v1',
        model_identifier='northwind-test-model',
    )


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
    *,
    idempotency_suffix: str = 'message',
) -> None:
    """Failure saves inbound once but applies no proposed Claim or lifecycle facts."""
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.revision == before_claim.revision + 1
    assert stored.model_dump(exclude={'revision', 'updated_at'}) == before_claim.model_dump(
        exclude={'revision', 'updated_at'}
    )
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert len(messages) == 1
    assert messages[0].actor is ActorType.CLAIMANT
    assert messages[0].visibility is MessageVisibility.CLAIMANT_VISIBLE
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    checkpoint = repository.find_idempotency('cus_demo', route, f'{protocol}-{idempotency_suffix}')
    assert checkpoint is not None
    assert checkpoint.message_id == messages[0].message_id
    assert checkpoint.revision_before_message == before_claim.revision


def assert_saved_model_recovery(
    response: httpx.Response,
    expected_rule_id: str,
) -> None:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['agent_message'] is None
    assert body['decision'] is None
    assert body['form_changes'] == []
    assert body['claimant_message']['recovery']['rule_id'] == expected_rule_id
    assert body['claimant_message']['recovery']['resume_entrypoint'] == 'submit_message'


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
        model_profile_id='synthetic-model',
        model_provider='synthetic-provider',
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
        model_profile_id='synthetic-model',
        model_provider='synthetic-provider',
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
        load_staff_assistant_prompt()


def test_snapshot_gateway_rejects_missing_model_configuration() -> None:
    gateway = ConfigurationBackedModelGateway(
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_protocol_adapter='openai_compatible',
            model_base_url='https://model.example.test/v1',
            model_profile_id='synthetic-model',
            model_provider='synthetic-provider',
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
        gateway.complete(ModelRequest(model_profile_id='openrouter-gpt4o-mini', messages=[]))

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
        model_profile_id='synthetic-model',
        model_provider='synthetic-provider',
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
