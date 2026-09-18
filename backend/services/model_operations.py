"""Persist bounded model invocation telemetry for Control Plane operations."""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from backend.domain.model_gateway import (
    ModelEvidenceContent,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelTextContent,
)
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.repositories.operations import OperationRepository

logger = logging.getLogger(__name__)

_CONTEXT_SIZE_KEYS = frozenset(
    {
        'claim_context_chars',
        'conversation_history_chars',
        'knowledge_citation_chars',
        'tool_result_chars',
        'external_service_chars',
    }
)


def _json_chars(value: object) -> int:
    return len(json.dumps(value, separators=(',', ':'), sort_keys=True))


def _request_size_metrics(request: ModelRequest) -> dict[str, int]:
    role_chars = {'system': 0, 'user': 0, 'assistant': 0, 'tool': 0}
    evidence_blocks = 0
    for message in request.messages:
        content_chars = len(message.content or '')
        for block in message.content_blocks:
            if isinstance(block, ModelTextContent):
                content_chars += len(block.text)
            elif isinstance(block, ModelEvidenceContent):
                evidence_blocks += 1
        role_chars[message.role.value] += content_chars

    messages = [message.model_dump(mode='json') for message in request.messages]
    tools = [tool.model_dump(mode='json') for tool in request.tools]
    return {
        'message_count': len(request.messages),
        'serialized_message_chars': _json_chars(messages),
        'system_message_chars': role_chars['system'],
        'user_message_chars': role_chars['user'],
        'assistant_message_chars': role_chars['assistant'],
        'tool_message_chars': role_chars['tool'],
        'response_schema_chars': _json_chars(request.response_schema or {}),
        'tool_definition_chars': _json_chars(tools),
        'tool_count': len(request.tools),
        'evidence_block_count': evidence_blocks,
    }


class ModelOperationsRecorder:
    """Write provider-neutral model usage and failure records without prompt content."""

    def __init__(self, repository: OperationRepository) -> None:
        self._repository = repository

    def succeeded(
        self,
        request: ModelRequest,
        response: ModelResponse,
        latency_ms: float,
        *,
        request_stage: str = 'single',
        invocation_ordinal: int = 1,
        invocation_count: int = 1,
        context_sizes: Mapping[str, int] | None = None,
    ) -> None:
        """Record one successful model invocation.

        Args:
            request: Provider-neutral request sent to the model gateway.
            response: Normalised model response containing bounded usage metadata.
            latency_ms: End-to-end invocation latency in milliseconds.
            request_stage: Stable stage label within the current turn.
            invocation_ordinal: One-based invocation position within the turn.
            invocation_count: Total provider invocations made for the turn.
            context_sizes: Optional claimant-context category sizes with no content.

        Returns:
            None.
        """

        self._record(
            request=request,
            state=OperationState.SUCCEEDED,
            latency_ms=latency_ms,
            response=response,
            request_stage=request_stage,
            invocation_ordinal=invocation_ordinal,
            invocation_count=invocation_count,
            context_sizes=context_sizes,
        )

    def failed(
        self,
        request: ModelRequest,
        error: ModelGatewayError,
        latency_ms: float,
        response: ModelResponse | None = None,
        *,
        request_stage: str = 'single',
        invocation_ordinal: int = 1,
        invocation_count: int = 1,
        context_sizes: Mapping[str, int] | None = None,
    ) -> None:
        """Record one controlled model invocation failure.

        Args:
            request: Provider-neutral request sent to the model gateway.
            error: Normalised model gateway failure.
            latency_ms: End-to-end invocation latency in milliseconds.
            response: Optional response received before validation failed.
            request_stage: Stable stage label within the current turn.
            invocation_ordinal: One-based invocation position within the turn.
            invocation_count: Total provider invocations made for the turn.
            context_sizes: Optional claimant-context category sizes with no content.

        Returns:
            None.
        """

        self._record(
            request=request,
            state=OperationState.FAILED,
            latency_ms=latency_ms,
            response=response,
            failure_provider_model=error.provider_model,
            error_code=f'MODEL_{error.code.value.upper()}',
            request_stage=request_stage,
            invocation_ordinal=invocation_ordinal,
            invocation_count=invocation_count,
            context_sizes=context_sizes,
        )

    def _record(
        self,
        *,
        request: ModelRequest,
        state: OperationState,
        latency_ms: float,
        response: ModelResponse | None,
        failure_provider_model: str | None = None,
        error_code: str | None = None,
        request_stage: str,
        invocation_ordinal: int,
        invocation_count: int,
        context_sizes: Mapping[str, int] | None,
    ) -> None:
        now = datetime.now(UTC)
        usage = response.usage if response is not None else None
        provider_model = response.provider_model if response is not None else failure_provider_model
        safe_context_sizes = {
            key: value
            for key, value in (context_sizes or {}).items()
            if key in _CONTEXT_SIZE_KEYS and isinstance(value, int) and value >= 0
        }
        observation: dict[str, object] = {
            'model_purpose': request.purpose,
            'model_profile_id': request.model_profile_id,
            'prompt_version': request.prompt_version,
            'request_stage': request_stage,
            'invocation_ordinal': invocation_ordinal,
            'invocation_count': invocation_count,
            'outcome': state.value,
            'provider_model': provider_model,
            'input_tokens': usage.input_tokens if usage is not None else None,
            'output_tokens': usage.output_tokens if usage is not None else None,
            'total_tokens': usage.total_tokens if usage is not None else None,
            'cache_read_input_tokens': (
                usage.cache_read_input_tokens if usage is not None else None
            ),
            'cache_write_input_tokens': (
                usage.cache_write_input_tokens if usage is not None else None
            ),
            'first_token_latency_ms': (
                response.first_token_latency_ms if response is not None else None
            ),
            'latency_ms': round(max(latency_ms, 0.0), 3),
            'error_code': error_code,
            **_request_size_metrics(request),
            **safe_context_sizes,
        }
        logger.info(
            'model_invocation.observed %s',
            json.dumps(observation, separators=(',', ':'), sort_keys=True),
            extra={'model_observation': observation},
        )
        operation_id = self._repository.new_operation_id()
        self._repository.create(
            OperationRecord(
                operation_id=operation_id,
                kind=OperationKind.MODEL_INVOCATION,
                subject_type='model_purpose',
                subject_id=request.purpose,
                state=state,
                revision=1,
                status_url=f'/internal/v1/admin/operations/{operation_id}',
                progress_percent=100,
                result={
                    'purpose': request.purpose,
                    'model_profile_id': request.model_profile_id,
                    'prompt_version': request.prompt_version,
                    'request_stage': request_stage,
                    'invocation_ordinal': invocation_ordinal,
                    'invocation_count': invocation_count,
                    'provider_model': provider_model,
                    'input_tokens': usage.input_tokens if usage is not None else None,
                    'output_tokens': usage.output_tokens if usage is not None else None,
                    'total_tokens': usage.total_tokens if usage is not None else None,
                    'latency_ms': round(max(latency_ms, 0.0), 3),
                },
                error_code=error_code,
                created_at=now,
                updated_at=now,
            )
        )
