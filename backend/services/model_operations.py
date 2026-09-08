"""Persist bounded model invocation telemetry for Control Plane operations."""

from datetime import UTC, datetime

from backend.domain.model_gateway import ModelGatewayError, ModelResponse
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.repositories.operations import OperationRepository


class ModelOperationsRecorder:
    """Write provider-neutral model usage and failure records without prompt content."""

    def __init__(self, repository: OperationRepository) -> None:
        self._repository = repository

    def succeeded(self, purpose: str, response: ModelResponse, latency_ms: float) -> None:
        """Record one successful model invocation.

        Args:
            purpose: Provider-neutral purpose supplied to the model gateway.
            response: Normalised model response containing bounded usage metadata.
            latency_ms: End-to-end invocation latency in milliseconds.

        Returns:
            None.
        """

        self._record(
            purpose=purpose,
            state=OperationState.SUCCEEDED,
            latency_ms=latency_ms,
            response=response,
        )

    def failed(
        self,
        purpose: str,
        error: ModelGatewayError,
        latency_ms: float,
        response: ModelResponse | None = None,
    ) -> None:
        """Record one controlled model invocation failure.

        Args:
            purpose: Provider-neutral purpose supplied to the model gateway.
            error: Normalised model gateway failure.
            latency_ms: End-to-end invocation latency in milliseconds.
            response: Optional response received before validation failed.

        Returns:
            None.
        """

        self._record(
            purpose=purpose,
            state=OperationState.FAILED,
            latency_ms=latency_ms,
            response=response,
            error_code=f'MODEL_{error.code.value.upper()}',
        )

    def _record(
        self,
        *,
        purpose: str,
        state: OperationState,
        latency_ms: float,
        response: ModelResponse | None,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        usage = response.usage if response is not None else None
        provider_model = response.provider_model if response is not None else None
        operation_id = self._repository.new_operation_id()
        self._repository.create(
            OperationRecord(
                operation_id=operation_id,
                kind=OperationKind.MODEL_INVOCATION,
                subject_type='model_purpose',
                subject_id=purpose,
                state=state,
                revision=1,
                status_url=f'/internal/v1/admin/operations/{operation_id}',
                progress_percent=100,
                result={
                    'purpose': purpose,
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
