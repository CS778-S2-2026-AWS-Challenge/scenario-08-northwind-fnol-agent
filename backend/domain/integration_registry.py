from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.models import PageInfo


class IntegrationHealthState(StrEnum):
    USING_FIXTURE = 'using_fixture'
    VERIFIED = 'verified'
    CONFIGURED_SERVICE = 'configured_service'
    PENDING_CONFIRMATION = 'pending_confirmation'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'


class IntegrationStatusProjection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    integration_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=160)
    capability: str = Field(min_length=1, max_length=100)
    health: IntegrationHealthState
    implementation: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=80)
    configuration_ids: list[str] = Field(default_factory=list, max_length=100)
    latency_ms: float | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, max_length=100)
    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class IntegrationStatusPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[IntegrationStatusProjection]
    page: PageInfo
