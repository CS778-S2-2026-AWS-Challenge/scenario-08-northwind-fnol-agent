import json
import logging
from typing import cast

import pytest

from backend.domain.model_gateway import (
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTool,
    ModelUsage,
)
from backend.domain.operations import OperationState
from backend.repositories.operations import OperationRepository
from backend.services.model_operations import ModelOperationsRecorder


def _request() -> ModelRequest:
    return ModelRequest(
        model_profile_id='qwen-local',
        purpose='agent_turn',
        prompt_version='northwind-fnol-claimant-v6',
        messages=[
            ModelMessage(role=ModelRole.SYSTEM, content='private-system-instruction'),
            ModelMessage(role=ModelRole.USER, content='private-claimant-message'),
        ],
        response_schema={
            'type': 'object',
            'properties': {'answer': {'type': 'string'}},
        },
        tools=[
            ModelTool(
                name='claim.read',
                description='private-tool-description',
                input_schema={'type': 'object', 'properties': {}},
            )
        ],
    )


def test_model_observation_records_bounded_sizes_and_provider_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = OperationRepository()
    recorder = ModelOperationsRecorder(repository)
    response = ModelResponse(
        completion_status=ModelCompletionStatus.COMPLETE,
        provider_model='qwen3.8-27b',
        first_token_latency_ms=125.5,
        usage=ModelUsage(
            input_tokens=900,
            output_tokens=80,
            total_tokens=980,
            cache_read_input_tokens=600,
            cache_write_input_tokens=200,
        ),
    )

    with caplog.at_level(logging.INFO, logger='backend.services.model_operations'):
        recorder.succeeded(
            _request(),
            response,
            850.25,
            request_stage='continuation',
            invocation_ordinal=2,
            invocation_count=2,
            context_sizes={
                'claim_context_chars': 4200,
                'conversation_history_chars': 700,
                'knowledge_citation_chars': 0,
                'tool_result_chars': 350,
                'external_service_chars': 120,
                'unbounded_private_size': 999,
            },
        )

    record = repository.metrics_records()[0]
    assert record.state is OperationState.SUCCEEDED
    assert record.result == {
        'purpose': 'agent_turn',
        'model_profile_id': 'qwen-local',
        'prompt_version': 'northwind-fnol-claimant-v6',
        'request_stage': 'continuation',
        'invocation_ordinal': 2,
        'invocation_count': 2,
        'provider_model': 'qwen3.8-27b',
        'input_tokens': 900,
        'output_tokens': 80,
        'total_tokens': 980,
        'latency_ms': 850.25,
    }
    observation = cast(dict[str, object], caplog.records[-1].__dict__['model_observation'])
    assert observation['request_stage'] == 'continuation'
    assert observation['invocation_ordinal'] == 2
    assert observation['invocation_count'] == 2
    assert observation['cache_read_input_tokens'] == 600
    assert observation['cache_write_input_tokens'] == 200
    assert observation['first_token_latency_ms'] == 125.5
    assert observation['claim_context_chars'] == 4200
    assert observation['conversation_history_chars'] == 700
    assert observation['tool_count'] == 1
    assert cast(int, observation['response_schema_chars']) > 0
    assert 'unbounded_private_size' not in observation
    encoded_observation = json.dumps(observation)
    assert '"input_tokens":900' in caplog.text
    assert 'private-system-instruction' not in encoded_observation
    assert 'private-claimant-message' not in encoded_observation
    assert 'private-tool-description' not in encoded_observation
    assert 'private-system-instruction' not in caplog.text
    assert 'private-claimant-message' not in caplog.text
    assert 'private-tool-description' not in caplog.text


def test_model_observation_keeps_missing_usage_explicit_for_success_and_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = OperationRepository()
    recorder = ModelOperationsRecorder(repository)
    request = _request()

    with caplog.at_level(logging.INFO, logger='backend.services.model_operations'):
        recorder.succeeded(
            request,
            ModelResponse(completion_status=ModelCompletionStatus.COMPLETE),
            25.0,
        )
        recorder.failed(
            request,
            ModelGatewayError(
                ModelGatewayErrorCode.TIMEOUT,
                retryable=True,
                provider_model='qwen3.8-27b',
            ),
            40.0,
        )

    records = repository.metrics_records()
    assert [record.state for record in records] == [
        OperationState.SUCCEEDED,
        OperationState.FAILED,
    ]
    assert records[1].error_code == 'MODEL_TIMEOUT'
    assert records[1].result is not None
    assert records[1].result['model_profile_id'] == 'qwen-local'
    assert records[1].result['provider_model'] == 'qwen3.8-27b'
    observations = [
        cast(dict[str, object], record.__dict__['model_observation']) for record in caplog.records
    ]
    assert observations[0]['input_tokens'] is None
    assert observations[0]['cache_read_input_tokens'] is None
    assert observations[0]['first_token_latency_ms'] is None
    assert observations[1]['outcome'] == 'failed'
    assert observations[1]['error_code'] == 'MODEL_TIMEOUT'
    assert observations[1]['total_tokens'] is None
