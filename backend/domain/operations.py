from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.models import PageInfo


class OperationKind(StrEnum):
    CONFIGURATION_VALIDATION = 'configuration_validation'
    KNOWLEDGE_INGESTION = 'knowledge_ingestion'
    KNOWLEDGE_INDEXING = 'knowledge_indexing'
    RETRIEVAL_CHECK = 'retrieval_check'
    EVALUATION = 'evaluation'
    INTEGRATION_HEALTH_CHECK = 'integration_health_check'
    MODEL_INVOCATION = 'model_invocation'


class OperationState(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    UNKNOWN = 'unknown'
    CANCELLED = 'cancelled'


class OperationRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    operation_id: str
    kind: OperationKind
    subject_type: str = Field(min_length=1, max_length=80)
    subject_id: str = Field(min_length=1, max_length=200)
    state: OperationState
    revision: int = Field(ge=1)
    status_url: str = Field(min_length=1, max_length=500)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    result: dict[str, object] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    created_at: datetime
    updated_at: datetime


class OperationPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[OperationRecord]
    page: PageInfo


class ModelUsageMetrics(BaseModel):
    model_config = ConfigDict(extra='forbid')

    calls: int = Field(ge=0)
    reported_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ModelCostMetrics(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['configured', 'partial', 'unconfigured']
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    estimated_microunits: int = Field(ge=0)
    priced_calls: int = Field(ge=0)
    unpriced_calls: int = Field(ge=0)
    configuration_id: str | None = None
    configuration_revision: int | None = Field(default=None, ge=1)


class RateLimitMetrics(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['clear', 'limited', 'unconfigured']
    events_in_window: int = Field(ge=0)
    window_seconds: int | None = Field(default=None, ge=60, le=86400)
    latest_event_at: datetime | None = None


class OperationalAlertProjection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    alert_code: str = Field(min_length=1, max_length=100)
    metric: Literal['total_tokens', 'estimated_cost_microunits', 'rate_limit_events']
    status: Literal['clear', 'triggered', 'unknown']
    observed: int | None = Field(default=None, ge=0)
    threshold: int = Field(ge=1)


class OperationMetricsProjection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    total: int = Field(ge=0)
    by_state: dict[str, int]
    by_kind: dict[str, int]
    usage: ModelUsageMetrics
    cost: ModelCostMetrics
    rate_limit: RateLimitMetrics
    alerts: list[OperationalAlertProjection]
    source: Literal['control_plane_operation_repository'] = 'control_plane_operation_repository'
