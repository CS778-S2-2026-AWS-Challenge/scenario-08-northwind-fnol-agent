from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.configuration import ConfigurationRecord, ValidationScenarioResult
from backend.domain.knowledge_admin import KnowledgeSourceRecord
from backend.domain.models import PageInfo


class ReleaseSetState(StrEnum):
    DRAFT = 'draft'
    VALIDATION = 'validation'
    PUBLISHED = 'published'
    SUPERSEDED = 'superseded'
    WITHDRAWN = 'withdrawn'


class ConfigurationReference(BaseModel):
    model_config = ConfigDict(extra='forbid')

    configuration_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)


class KnowledgeReference(BaseModel):
    """Reference to one immutable, published knowledge version."""

    model_config = ConfigDict(extra='forbid')

    knowledge_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)


class ReleaseSetRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    release_set_id: str
    environment: str = Field(min_length=1, max_length=50)
    runtime_profile: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1)
    state: ReleaseSetState
    configuration_refs: dict[str, ConfigurationReference]
    integration_refs: dict[str, ConfigurationReference] = Field(default_factory=dict)
    knowledge_refs: dict[str, KnowledgeReference] = Field(default_factory=dict)
    author: str
    reason: str = Field(min_length=1, max_length=500)
    validation_evidence: dict[str, object] | None = None
    effective_time: datetime | None = None
    previous_release_set_id: str | None = None
    rollback_target: str | None = None
    updated_at: datetime


class AdminReleaseSetProjection(ReleaseSetRecord):
    """Release Set record plus server-derived lifecycle actions."""

    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminReleaseSetPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[AdminReleaseSetProjection]
    page: PageInfo


class ReleaseSetCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    environment: str = Field(min_length=1, max_length=50)
    runtime_profile: str = Field(min_length=1, max_length=80)
    configuration_refs: dict[str, ConfigurationReference] = Field(min_length=1)
    integration_refs: dict[str, ConfigurationReference] = Field(default_factory=dict)
    knowledge_refs: dict[str, KnowledgeReference] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class ReleaseSetValidationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_results: list[ValidationScenarioResult] = Field(min_length=1, max_length=100)


class ReleaseSetTransitionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reason: str = Field(min_length=1, max_length=500)
    rollback_target: str | None = None


class ReleaseSetAuditEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')

    event_id: str
    release_set_id: str
    revision: int
    previous_revision: int | None = None
    actor: str
    action: str
    reason: str
    outcome: str
    created_at: datetime


class RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')

    release_set_id: str
    environment: str
    runtime_profile: str
    loaded_at: datetime
    configurations: dict[str, ConfigurationRecord]
    integrations: dict[str, ConfigurationRecord] = Field(default_factory=dict)
    knowledge: dict[str, KnowledgeSourceRecord] = Field(default_factory=dict)


def now_utc() -> datetime:
    return datetime.now(UTC)
