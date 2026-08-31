from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator

from backend.domain.models import ContractModel


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    document_id: str
    chunk_id: str
    title: str
    document_type: str
    version: str
    section_path: str
    page: int | None
    source_uri: str
    jurisdiction: str
    insurer: str | None
    product: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    authority: str
    visibility: str
    checksum: str
    ingested_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class KnowledgeSearch:
    text: str
    jurisdiction: str
    visibility: str
    document_id: str | None = None
    authority: str | None = None
    version: str | None = None
    insurer: str | None = None
    product: str | None = None
    effective_at: datetime | None = None
    limit: int = 5


class KnowledgePublicationStatus(StrEnum):
    APPROVED = 'approved'
    DRAFT = 'draft'
    WITHDRAWN = 'withdrawn'


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    document_id: str
    source_key: str
    title: str
    document_type: str
    version: str
    source_uri: str
    jurisdiction: str
    insurer: str | None
    product: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    authority: str
    visibility: str
    publication_status: KnowledgePublicationStatus
    expected_checksum: str | None = None


class KnowledgeDocumentStore(Protocol):
    def connection_status(self) -> str:
        raise NotImplementedError

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        raise NotImplementedError


class KnowledgeRetriever(Protocol):
    def connection_status(self) -> str:
        raise NotImplementedError

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        raise NotImplementedError


class KnowledgeRetrievalUnavailable(RuntimeError):
    pass


class KnowledgeSearchRequest(ContractModel):
    question: str = Field(min_length=1, max_length=500)
    jurisdiction: str = Field(min_length=2, max_length=20)
    visibility: str = Field(min_length=1, max_length=100)
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    authority: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    insurer: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=100)
    effective_at: datetime
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator(
        'question',
        'jurisdiction',
        'visibility',
        'document_id',
        'authority',
        'version',
        'insurer',
        'product',
    )
    @classmethod
    def require_canonical_search_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError('knowledge search text fields must be canonical')
        return value

    @field_validator('effective_at')
    @classmethod
    def require_effective_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('effective_at must include a timezone offset')
        return value


class KnowledgeCitation(ContractModel):
    document_id: str
    chunk_id: str
    title: str
    section_path: str
    source_uri: str
    version: str
    checksum: str
    text: str


class KnowledgeSearchResponse(ContractModel):
    status: Literal['evidence_found', 'no_evidence', 'unavailable']
    results: list[KnowledgeCitation]
    limitations: list[str]
