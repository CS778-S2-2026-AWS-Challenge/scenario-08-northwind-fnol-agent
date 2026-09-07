from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.integration_registry import IntegrationHealthState


class IntegrationHealthCheckRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    check_id: str = Field(min_length=1, max_length=100)
    integration_id: str = Field(min_length=1, max_length=100)
    health: IntegrationHealthState
    source: str = Field(min_length=1, max_length=80)
    implementation: str = Field(min_length=1, max_length=160)
    latency_ms: float = Field(ge=0)
    failure_code: str | None = Field(default=None, max_length=100)
    operation_id: str | None = Field(default=None, max_length=100)
    checked_at: datetime


class IntegrationHealthCheckPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[IntegrationHealthCheckRecord]
    page: dict[str, str | None]
