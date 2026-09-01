from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConfigurationState(StrEnum):
    DRAFT = 'draft'
    VALIDATION = 'validation'
    AWAITING_APPROVAL = 'awaiting_approval'
    PUBLISHED = 'published'
    WITHDRAWN = 'withdrawn'
    SUPERSEDED = 'superseded'


class ConfigurationImpact(StrEnum):
    NORMAL = 'normal'
    HIGH = 'high'


class DataRuntimeProfileValue(StrEnum):
    FIXTURE = 'fixture'
    LOCAL_MVP = 'local_mvp'
    CLOUDFLARE = 'cloudflare'
    MONGODB = 'mongodb'
    AWS = 'aws'


class ObjectStorageAdapterValue(StrEnum):
    FIXTURE = 'fixture'
    S3_COMPATIBLE = 's3_compatible'


class DataProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')

    data_runtime_profile: DataRuntimeProfileValue
    object_storage_adapter: ObjectStorageAdapterValue


class ConfigurationRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    configuration_id: str
    domain: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    state: ConfigurationState
    impact: ConfigurationImpact
    values: dict[str, object]
    secret_references: dict[str, str] = Field(default_factory=dict)
    author: str
    reason: str
    validation_evidence: dict[str, object] | None = None
    effective_time: datetime | None = None
    previous_version: str | None = None
    rollback_target: str | None = None
    updated_at: datetime


class ConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    domain: str = Field(min_length=1, max_length=80)
    impact: ConfigurationImpact = ConfigurationImpact.NORMAL
    values: dict[str, object] = Field(default_factory=dict)
    secret_references: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class ConfigurationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    values: dict[str, object] | None = None
    secret_references: dict[str, str] | None = None
    reason: str = Field(min_length=1, max_length=500)


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_results: list['ValidationScenarioResult'] = Field(min_length=1, max_length=100)


class ValidationScenarioResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_id: str = Field(min_length=1, max_length=120)
    outcome: Literal['passed', 'failed']
    evidence: str = Field(min_length=1, max_length=500)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reason: str = Field(min_length=1, max_length=500)
    rollback_target: str | None = None


class AuditEvent(BaseModel):
    event_id: str
    configuration_id: str
    revision: int
    actor: str
    action: str
    reason: str
    outcome: str
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEvent]
    page: dict[str, str | None]


def now_utc() -> datetime:
    return datetime.now(UTC)
