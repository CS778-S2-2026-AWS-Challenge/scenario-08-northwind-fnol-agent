from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.models import PageInfo


class KnowledgeVersionState(StrEnum):
    DRAFT = 'draft'
    VALIDATING = 'validating'
    INDEXED = 'indexed'
    AWAITING_APPROVAL = 'awaiting_approval'
    PUBLISHED = 'published'
    WITHDRAWN = 'withdrawn'
    SUPERSEDED = 'superseded'
    FAILED = 'failed'


class KnowledgeSourceRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    knowledge_id: str = Field(min_length=1, max_length=100)
    document_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    source_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    document_type: str = Field(min_length=1, max_length=100)
    source_uri: str = Field(min_length=1, max_length=500)
    jurisdiction: str = Field(min_length=2, max_length=20)
    insurer: str | None = Field(default=None, max_length=200)
    product: str | None = Field(default=None, max_length=100)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    authority: str = Field(min_length=1, max_length=100)
    visibility: str = Field(min_length=1, max_length=100)
    expected_checksum: str | None = Field(default=None, max_length=64)
    state: KnowledgeVersionState
    revision: int = Field(ge=1)
    author: str = Field(min_length=1, max_length=200)
    ingestion_operation_id: str | None = Field(default=None, max_length=100)
    chunk_count: int | None = Field(default=None, ge=1)
    validation_evidence: dict[str, object] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    previous_version: str | None = Field(default=None, max_length=200)
    updated_at: datetime


class AdminKnowledgeSourceProjection(KnowledgeSourceRecord):
    """Knowledge record plus principal-aware lifecycle actions."""

    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class KnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    document_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    source_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    document_type: str = Field(min_length=1, max_length=100)
    source_uri: str = Field(min_length=1, max_length=500)
    jurisdiction: str = Field(min_length=2, max_length=20)
    insurer: str | None = Field(default=None, max_length=200)
    product: str | None = Field(default=None, max_length=100)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    authority: str = Field(min_length=1, max_length=100)
    visibility: str = Field(min_length=1, max_length=100)
    expected_checksum: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, max_length=2_000_000)


class KnowledgeValidationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_results: list[dict[str, object]] = Field(min_length=1, max_length=100)


class KnowledgeSourcePage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[AdminKnowledgeSourceProjection]
    page: PageInfo
